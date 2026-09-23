"""NQ-014 - Parse OSM opening_hours into poi_opening_hours rows.

Deliberately implements the COMMON SUBSET only. Measured against real data:
8.7% of POIs (1,288 of 14,851) carry an opening_hours tag at all, and the
top patterns are simple. The full OSM grammar is not worth chasing - 90%
coverage is a day, 99% is a month.

Handles:
  24/7
  HH:MM-HH:MM              (implicitly every day)
  HH:MM - HH:MM            (spaces tolerated)
  Mo-Su HH:MM-HH:MM
  Mo-Fr HH:MM-HH:MM
  Mo,We,Fr HH:MM-HH:MM
  Sa-Su off / Su off
  multiple rules separated by ';'
  cross-midnight (split into two intervals)

Everything else -> category default at confidence 0.3.

CONFIDENCE drives optimizer behaviour: rows below 0.5 are a SOFT constraint
with a penalty, never a hard filter. With 91% of POIs on defaults, hard
filtering would delete almost the entire dataset from every itinerary.
"""
from __future__ import annotations

import argparse
import os
import re
from collections import Counter

import psycopg

DSN = os.environ.get(
    "PG_DSN", "postgresql://navigiq:navigiq_local_dev@localhost:5433/navigiq"
)

DAYS = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
ALL_DAYS = list(range(7))

TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
DAYSPEC_RE = re.compile(r"^((?:mo|tu|we|th|fr|sa|su)(?:\s*[-,]\s*(?:mo|tu|we|th|fr|sa|su))*)",
                        re.IGNORECASE)

# Fallback when nothing parses. Conservative: a wide window that will not
# wrongly exclude a POI, paired with low confidence so the optimizer treats
# it softly.
CATEGORY_DEFAULTS = {
    "cafe": (8 * 60, 22 * 60), "restaurant": (11 * 60, 23 * 60),
    "street_food": (8 * 60, 22 * 60), "bar": (12 * 60, 23 * 60 + 30),
    "dessert": (10 * 60, 22 * 60), "historical": (9 * 60, 17 * 60),
    "temple": (6 * 60, 20 * 60), "museum": (10 * 60, 17 * 60),
    "art_gallery": (10 * 60, 18 * 60), "park": (5 * 60, 20 * 60),
    "lake": (6 * 60, 18 * 60), "viewpoint": (6 * 60, 19 * 60),
    "sunset": (16 * 60, 20 * 60), "nature": (6 * 60, 18 * 60),
    "shopping": (10 * 60, 21 * 60), "market": (6 * 60, 20 * 60),
    "bookstore": (10 * 60, 21 * 60), "nightlife": (18 * 60, 23 * 60 + 59),
    "entertainment": (10 * 60, 22 * 60), "landmark": (0, 1440),
}


def expand_days(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.lower().split(","):
        part = part.strip()
        if "-" in part:
            a, b = (p.strip() for p in part.split("-", 1))
            if a in DAYS and b in DAYS:
                i, j = DAYS[a], DAYS[b]
                out.extend(range(i, j + 1) if i <= j
                           else list(range(i, 7)) + list(range(0, j + 1)))
        elif part in DAYS:
            out.append(DAYS[part])
    return sorted(set(out))


def parse(value: str) -> list[tuple[int, int, int, bool]] | None:
    """Return [(dow, open_min, close_min, is_24h)] or None if unparseable."""
    v = value.strip()
    if not v:
        return None

    if v.lower() in ("24/7", "24x7", "24 hours", "open 24 hours"):
        return [(d, 0, 1440, True) for d in ALL_DAYS]

    rows: list[tuple[int, int, int, bool]] = []
    closed: set[int] = set()
    matched_any = False

    for rule in v.split(";"):
        rule = rule.strip()
        if not rule:
            continue

        m = DAYSPEC_RE.match(rule)
        if m:
            days = expand_days(m.group(1))
            rest = rule[m.end():].strip()
        else:
            days, rest = ALL_DAYS, rule

        if rest.lower() in ("off", "closed"):
            closed.update(days)
            matched_any = True
            continue

        times = TIME_RE.findall(rest)
        if not times:
            continue

        matched_any = True
        for h1, m1, h2, m2 in times:
            o = int(h1) * 60 + int(m1)
            c = int(h2) * 60 + int(m2)
            if o > 1440 or c > 1440:
                continue
            for d in days:
                if c > o:
                    rows.append((d, o, c, False))
                elif c < o:
                    # cross-midnight: split across the day boundary
                    rows.append((d, o, 1440, False))
                    rows.append(((d + 1) % 7, 0, c, False))

    if not matched_any:
        return None
    return [r for r in rows if r[0] not in closed]


def main() -> None:
    ap = argparse.ArgumentParser(description="NQ-014 opening hours")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stats = Counter()
    unparsed: Counter = Counter()

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT p.id, p.tags->>'opening_hours', c.key
            FROM pois p JOIN poi_categories c ON c.id = p.primary_category
            WHERE p.active
        """)
        rows = cur.fetchall()

        pending: list[tuple] = []
        for poi_id, oh, cat in rows:
            stats["pois"] += 1
            parsed = parse(oh) if oh else None

            if parsed:
                stats["parsed"] += 1
                for d, o, c, is24 in parsed:
                    pending.append((poi_id, d, o, c, is24, "osm_parsed", 1.0))
            else:
                if oh:
                    stats["failed"] += 1
                    unparsed[oh] += 1
                else:
                    stats["no_tag"] += 1
                o, c = CATEGORY_DEFAULTS.get(cat, (8 * 60, 20 * 60))
                for d in ALL_DAYS:
                    pending.append((poi_id, d, o, c, False,
                                    "inferred_category_default", 0.3))

        print(f"pois {stats['pois']:,} | parsed {stats['parsed']:,} | "
              f"tag present but unparseable {stats['failed']:,} | "
              f"no tag {stats['no_tag']:,}")
        pct = 100.0 * stats["parsed"] / stats["pois"] if stats["pois"] else 0
        print(f"real-hours coverage: {pct:.1f}%  "
              f"({100 - pct:.1f}% on category defaults at confidence 0.3)")

        if unparsed:
            print("\ntop unparseable values:")
            for val, n in unparsed.most_common(10):
                print(f"  {n:>4}  {val[:70]}")

        if args.dry_run:
            print("\n--dry-run: nothing written")
            return

        cur.execute("TRUNCATE poi_opening_hours")
        cur.executemany(
            """INSERT INTO poi_opening_hours
               (poi_id, day_of_week, open_min, close_min, is_24h,
                closed_all_day, source, confidence)
               VALUES (%s,%s,%s,%s,%s,false,%s,%s)
               ON CONFLICT DO NOTHING""",
            pending,
        )
        conn.commit()
        print(f"\nwrote {len(pending):,} interval rows")


if __name__ == "__main__":
    main()
