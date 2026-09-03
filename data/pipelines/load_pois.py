"""NQ-013 (pass 1) - Load staging JSONL into the pois table.

Scope of this pass: normalize, apply the category mapping and drop list,
deduplicate, load. Wikidata/Wikipedia enrichment and full prominence scoring
are a follow-up commit.

Reads : data/artifacts/pois_staging.jsonl
        data/mappings/osm_categories.yaml
Writes: pois, poi_category_links

Idempotent: rerunning on unchanged input writes zero rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

import psycopg
import yaml

DSN = os.environ.get(
    "PG_DSN", "postgresql://navigiq:navigiq_local_dev@localhost:5433/navigiq"
)

# natural=water requires a name (see osm_categories.yaml). Polygon area is not
# available in staging - NQ-011 stores centroids only - so min_area_sqm cannot
# be applied in this pass. Name presence alone removes the bulk of the ~28k
# unnamed rural ponds. Recorded as a known limitation.
NAME_REQUIRED_FALLBACK = True


def normalize_name(name: str) -> str:
    """unaccent + lower + collapse whitespace. Used for trigram dedup."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def content_hash(rec: dict) -> str:
    payload = json.dumps(
        {"ref": rec["source_ref"], "name": rec["name"],
         "lat": rec["lat"], "lon": rec["lon"], "tags": rec["tags"]},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Mapping:
    def __init__(self, path: Path):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.rules = {k: v for k, v in raw.items() if "=" in k}
        self.drop = set(raw.get("drop", []))
        self.landmarks = {normalize_name(n) for n in raw.get("landmark_names", [])}
        self.key_priority = raw.get("key_priority", [])

    def resolve(self, tags: dict) -> tuple[str | None, list[tuple[str, float]], dict]:
        """Return (primary_category, [(secondary, weight)], rule) or (None, [], {})."""
        for key in self.key_priority:
            val = tags.get(key)
            if not val:
                continue
            combo = f"{key}={val}"
            if combo in self.drop:
                return None, [], {}
            rule = self.rules.get(combo)
            if not rule:
                continue
            if rule.get("requires_name") and not tags.get("name"):
                return None, [], {}
            secondary = [
                (s["category"], float(s["weight"]))
                for s in rule.get("secondary", [])
            ]
            return rule["primary"], secondary, rule
        return None, [], {}


def prominence(tags: dict, name_norm: str, mapping: Mapping) -> tuple[float, dict]:
    """Deterministic, auditable. NOT a rating - measures documentation and
    notability only. See ADR-013. Full scoring (Wikidata sitelinks, edit
    history) arrives with enrichment."""
    rich_keys = ("website", "contact:website", "phone", "contact:phone",
                 "opening_hours", "cuisine", "wheelchair", "description", "image")
    tag_richness = sum(1 for k in rich_keys if tags.get(k)) / len(rich_keys)
    has_wikidata = 1.0 if tags.get("wikidata") else 0.0
    has_wikipedia = 1.0 if tags.get("wikipedia") else 0.0
    is_landmark = 1.0 if name_norm in mapping.landmarks else 0.0

    parts = {
        "wikidata_presence": round(0.30 * has_wikidata, 3),
        "wikipedia_presence": round(0.15 * has_wikipedia, 3),
        "tag_richness": round(0.25 * tag_richness, 3),
        "landmark_flag": round(0.30 * is_landmark, 3),
        "_note": "pass 1: sitelink breadth and edit signal pending enrichment",
    }
    score = sum(v for k, v in parts.items() if not k.startswith("_"))
    return round(min(score, 1.0), 3), parts


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def main() -> None:
    ap = argparse.ArgumentParser(description="NQ-013 pass 1: load POIs")
    ap.add_argument("--staging", default="data/artifacts/pois_staging.jsonl")
    ap.add_argument("--mapping", default="data/mappings/osm_categories.yaml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mapping = Mapping(Path(args.mapping))
    print(f"mapping: {len(mapping.rules)} rules, {len(mapping.drop)} drops, "
          f"{len(mapping.landmarks)} landmarks")

    stats = Counter()
    candidates: list[dict] = []

    with open(args.staging, encoding="utf-8") as fh:
        for line in fh:
            stats["read"] += 1
            rec = json.loads(line)
            tags = rec["tags"]

            name = tags.get("name") or tags.get("name:en")
            if not name:
                stats["no_name"] += 1
                continue

            primary, secondary, rule = mapping.resolve(tags)
            if primary is None:
                stats["dropped_or_unmapped"] += 1
                continue

            name_norm = normalize_name(name)
            score, parts = prominence(tags, name_norm, mapping)

            candidates.append({
                "source": "osm",
                "source_ref": rec["source_ref"],
                "name": name,
                "name_normalized": name_norm,
                "lat": rec["lat"],
                "lon": rec["lon"],
                "primary": primary,
                "secondary": secondary,
                "indoor": rule.get("indoor"),
                "prominence": score,
                "prominence_parts": parts,
                "tags": tags,
                "wikidata_id": tags.get("wikidata"),
                "content_hash": content_hash({**rec, "name": name}),
            })
            stats["kept"] += 1

    print(f"\nread {stats['read']:,} | no name {stats['no_name']:,} | "
          f"dropped/unmapped {stats['dropped_or_unmapped']:,} | kept {stats['kept']:,}")

    # --- dedup: wikidata equality, then name+proximity ----------------------
    # Never substring matching: "Lalbagh" also matches "Lalbagh Nursing Home".
    by_wikidata: dict[str, dict] = {}
    deduped: list[dict] = []
    for c in candidates:
        wd = c["wikidata_id"]
        if wd and wd in by_wikidata:
            stats["merged_wikidata"] += 1
            continue
        if wd:
            by_wikidata[wd] = c
        deduped.append(c)

    by_name: dict[str, list[dict]] = {}
    final: list[dict] = []
    for c in deduped:
        bucket = by_name.setdefault(c["name_normalized"], [])
        dup = next(
            (o for o in bucket
             if haversine_m((c["lat"], c["lon"]), (o["lat"], o["lon"])) < 120),
            None,
        )
        if dup:
            stats["merged_proximity"] += 1
            continue
        bucket.append(c)
        final.append(c)

    print(f"dedup: {stats['merged_wikidata']:,} by wikidata, "
          f"{stats['merged_proximity']:,} by name+120m -> {len(final):,} unique")

    print("\ntop categories:")
    for cat, n in Counter(c["primary"] for c in final).most_common(12):
        print(f"  {n:>6,}  {cat}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT key, id FROM poi_categories")
        cat_ids = dict(cur.fetchall())

        missing = {c["primary"] for c in final} - set(cat_ids)
        missing |= {s for c in final for s, _ in c["secondary"]} - set(cat_ids)
        if missing:
            raise SystemExit(f"categories not in poi_categories: {sorted(missing)}")

        for c in final:
            cur.execute(
                """
                INSERT INTO pois (source, source_ref, name, name_normalized, geom,
                                  primary_category, prominence, prominence_parts,
                                  indoor, weather_flags, tags, wikidata_id, curated, quality_score,
                                  active, content_hash)
                VALUES (%s,%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                        %s,%s,%s,%s,%s,%s,%s,false,0,true,%s)
                ON CONFLICT (source, source_ref) DO UPDATE SET
                    name = EXCLUDED.name,
                    name_normalized = EXCLUDED.name_normalized,
                    geom = EXCLUDED.geom,
                    primary_category = EXCLUDED.primary_category,
                    prominence = EXCLUDED.prominence,
                    prominence_parts = EXCLUDED.prominence_parts,
                    tags = EXCLUDED.tags,
                    content_hash = EXCLUDED.content_hash
                WHERE pois.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                RETURNING id, (xmax = 0) AS inserted
                """,
                (c["source"], c["source_ref"], c["name"], c["name_normalized"],
                 c["lon"], c["lat"], cat_ids[c["primary"]], c["prominence"],
                 json.dumps(c["prominence_parts"]), c["indoor"], json.dumps({}),
                 json.dumps(c["tags"], ensure_ascii=False), c["wikidata_id"],
                 c["content_hash"]),
            )
            row = cur.fetchone()
            if row is None:
                stats["unchanged"] += 1
                continue
            poi_id, inserted = row
            stats["inserted" if inserted else "updated"] += 1

            cur.execute("DELETE FROM poi_category_links WHERE poi_id = %s", (poi_id,))
            cur.execute(
                "INSERT INTO poi_category_links (poi_id, category_id, weight) "
                "VALUES (%s,%s,1.0)", (poi_id, cat_ids[c["primary"]]))
            for sec, weight in c["secondary"]:
                cur.execute(
                    "INSERT INTO poi_category_links (poi_id, category_id, weight) "
                    "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (poi_id, cat_ids[sec], weight))
        conn.commit()

    print(f"\ninserted {stats['inserted']:,} | updated {stats['updated']:,} | "
          f"unchanged {stats['unchanged']:,}")


if __name__ == "__main__":
    main()
