"""Opening-hours parsing (ported from NQ-014, extended).

Deliberately the COMMON SUBSET of the OSM grammar. Measured in NQ-014: under
9 % of POIs carry opening_hours at all and the top patterns are simple.

Handles:
  24/7
  HH:MM-HH:MM                     (every day)
  Mo-Su HH:MM-HH:MM, Mo,We,Fr ... (day lists and ranges, wrap-around Sa-Mo)
  Sa-Su off / Su off / PH off     (PH rules are ignored - no holiday calendar)
  multiple time ranges per rule   ("Mo-Fr 09:00-13:00,14:00-18:00")
  multiple rules separated by ';'
  cross-midnight ("18:00-02:00", split at the day boundary)
  sunrise-sunset                  (approximated 06:00-18:30, confidence 0.6)

Everything else is UNPARSED and falls back to a category default at
confidence 0.3. CONFIDENCE drives behaviour everywhere: below 0.5 the hours
are a soft preference, never a hard filter, so 90 % of POIs are not deleted
from every plan by guesses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DAYS = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
ALL_DAYS = tuple(range(7))

PARSED_CONFIDENCE = 0.9
SUN_CONFIDENCE = 0.6
DEFAULT_CONFIDENCE = 0.3
RELIABLE_THRESHOLD = 0.5

# Sunrise/sunset in Bengaluru varies by roughly 40 minutes over the year;
# the approximation errs toward a narrower window.
SUNRISE_MIN = 6 * 60 + 15
SUNSET_MIN = 18 * 60 + 15

TIME_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")
DAYSPEC_RE = re.compile(
    r"^((?:mo|tu|we|th|fr|sa|su)(?:\s*[-,]\s*(?:mo|tu|we|th|fr|sa|su))*)(?=\s|$)",
    re.IGNORECASE)

# Category fallbacks (open, close) when nothing parses. Wide windows that do
# not wrongly exclude a POI, paired with low confidence.
CATEGORY_DEFAULTS: dict[str, tuple[int, int]] = {
    "cafe": (8 * 60, 22 * 60), "restaurant": (11 * 60, 23 * 60),
    "street_food": (8 * 60, 22 * 60), "dessert": (10 * 60, 22 * 60),
    "nightlife": (17 * 60, 23 * 60 + 30),
    "museum": (10 * 60, 17 * 60), "gallery": (10 * 60, 18 * 60),
    "science": (10 * 60, 18 * 60), "palace": (10 * 60, 17 * 60 + 30),
    "fort": (9 * 60, 17 * 60 + 30), "history": (9 * 60, 18 * 60),
    "heritage": (9 * 60, 18 * 60), "monument": (6 * 60, 20 * 60),
    "architecture": (6 * 60, 21 * 60),
    "temple": (6 * 60, 20 * 60 + 30), "church": (6 * 60, 19 * 60),
    "mosque": (5 * 60, 21 * 60), "religious_site": (6 * 60, 20 * 60),
    "park": (6 * 60, 19 * 60), "garden": (6 * 60, 19 * 60),
    "lake": (6 * 60, 18 * 60 + 30), "nature": (8 * 60, 17 * 60),
    "hill": (6 * 60, 18 * 60), "viewpoint": (6 * 60, 19 * 60),
    "forest": (7 * 60, 17 * 60 + 30), "waterfall": (8 * 60, 17 * 60 + 30),
    "reservoir": (7 * 60, 18 * 60),
    "shopping": (10 * 60, 21 * 60), "market": (7 * 60, 21 * 60),
    "mall": (10 * 60, 22 * 60),
    "entertainment": (10 * 60, 22 * 60), "gaming": (11 * 60, 22 * 60),
    "activity": (9 * 60, 20 * 60), "adventure": (7 * 60, 17 * 60 + 30),
    "farm": (9 * 60, 17 * 60), "experience": (10 * 60, 19 * 60),
    "workshop": (10 * 60, 19 * 60), "neighborhood": (8 * 60, 21 * 60),
    "walking_area": (8 * 60, 22 * 60), "other": (9 * 60, 18 * 60),
}


@dataclass(frozen=True)
class Interval:
    day: int
    open_min: int
    close_min: int
    is_24h: bool = False

    def __post_init__(self) -> None:
        if not (0 <= self.day <= 6):
            raise ValueError("day out of range")
        if not (0 <= self.open_min < self.close_min <= 1440):
            raise ValueError(f"impossible interval {self.open_min}-{self.close_min}")


@dataclass(frozen=True)
class ParsedHours:
    intervals: tuple[Interval, ...]
    confidence: float
    source: str                 # osm_parsed | osm_sun | category_default | curated


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


def _add(rows: list[Interval], day: int, o: int, c: int) -> None:
    if c > o:
        rows.append(Interval(day, o, c))
    elif c < o:
        rows.append(Interval(day, o, 1440))
        if c > 0:
            rows.append(Interval((day + 1) % 7, 0, c))


def parse_osm(value: str | None) -> ParsedHours | None:
    """Parse an OSM opening_hours value, or None if not in the subset."""
    if not value:
        return None
    v = value.strip()
    if not v or len(v) > 255:
        return None
    if v.lower() in ("24/7", "24x7", "24 hours", "open 24 hours", "mo-su 00:00-24:00"):
        return ParsedHours(tuple(Interval(d, 0, 1440, True) for d in ALL_DAYS),
                           PARSED_CONFIDENCE, "osm_parsed")
    if v.lower().replace(" ", "") in ("sunrise-sunset", "mo-susunrise-sunset"):
        return ParsedHours(tuple(Interval(d, SUNRISE_MIN, SUNSET_MIN) for d in ALL_DAYS),
                           SUN_CONFIDENCE, "osm_sun")

    rows: list[Interval] = []
    closed: set[int] = set()
    matched_any = False
    for rule in v.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        if rule.lower().startswith("ph"):
            matched_any = True       # public-holiday rules: no calendar, ignore
            continue
        m = DAYSPEC_RE.match(rule)
        if m:
            days = expand_days(m.group(1))
            rest = rule[m.end():].strip()
        else:
            days, rest = list(ALL_DAYS), rule
        rest = rest.lstrip(",").strip()
        if rest.lower() in ("off", "closed"):
            closed.update(days)
            matched_any = True
            continue
        times = TIME_RANGE_RE.findall(rest)
        if not times:
            continue
        leftover = TIME_RANGE_RE.sub("", rest).replace(",", "").strip()
        if leftover:
            return None               # something we do not understand: refuse
        matched_any = True
        for h1, m1, h2, m2 in times:
            o, c = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
            if o > 1440 or c > 1440 or int(m1) > 59 or int(m2) > 59:
                return None
            for d in days:
                _add(rows, d, o, c)
    if not matched_any:
        return None
    kept = tuple(sorted({r for r in rows if r.day not in closed},
                        key=lambda r: (r.day, r.open_min)))
    return ParsedHours(kept, PARSED_CONFIDENCE, "osm_parsed")


def category_default(category: str) -> ParsedHours:
    o, c = CATEGORY_DEFAULTS.get(category, (9 * 60, 18 * 60))
    return ParsedHours(tuple(Interval(d, o, c) for d in ALL_DAYS),
                       DEFAULT_CONFIDENCE, "category_default")


def resolve_hours(value: str | None, category: str) -> ParsedHours:
    return parse_osm(value) or category_default(category)


def is_open_at(intervals, day: int, minute: int) -> bool:
    return any(i.day == day and i.open_min <= minute < i.close_min for i in intervals)


def window_for_day(intervals, day: int) -> tuple[int, int] | None:
    """Earliest open and latest close for a day, or None when closed.

    For scheduling, a day with a lunch break (09-13, 14-18) is treated as its
    envelope only when the planner also checks the concrete visit fits one
    interval - see planning.validator.
    """
    day_rows = [i for i in intervals if i.day == day]
    if not day_rows:
        return None
    return min(i.open_min for i in day_rows), max(i.close_min for i in day_rows)
