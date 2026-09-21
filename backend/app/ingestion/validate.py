"""Stage 9 - VALIDATE: data-quality assertions on every record before load.

A record that fails any assertion is rejected (never loaded) and counted by
reason in the manifest. The same rules are enforced again by database CHECK
constraints, so bad data cannot enter through any other path either.
"""
from __future__ import annotations

import math

from app.domain.taxonomy import category_catalog, is_valid_mood, is_valid_tag
from app.geo.regions import RegionBucket

VALID_COST_CONFIDENCE = {"verified", "source_tag", "curated_estimate", "category_default", "free"}


def validate_record(r: dict) -> list[str]:
    errors: list[str] = []
    lat, lon = r.get("lat"), r.get("lon")
    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180):
        errors.append("invalid_coordinates")
    if not r.get("source_ref") or not r.get("slug"):
        errors.append("missing_canonical_id")
    if not r.get("name") or not str(r["name"]).strip():
        errors.append("missing_name")
    d = r.get("distance_from_center_km")
    if d is None or d < 0:
        errors.append("invalid_distance")
    if r.get("region_bucket") not in RegionBucket._value2member_map_:
        errors.append("invalid_region")
    catalog = category_catalog()
    cat = r.get("category")
    if cat not in catalog or catalog[cat].theme:
        errors.append("invalid_category")
    for s, w in r.get("secondary", []):
        if s not in catalog or not 0 < w <= 1:
            errors.append("invalid_secondary")
            break
    dmin, dtyp, dmax = r.get("visit_duration") or (0, 0, 0)
    if not (0 < dmin <= dtyp <= dmax):
        errors.append("invalid_duration")
    cmin, ctyp, cmax = r.get("cost") or (-1, -1, -1)
    if not (0 <= cmin <= ctyp <= cmax):
        errors.append("invalid_cost")
    if r.get("cost_confidence") not in VALID_COST_CONFIDENCE:
        errors.append("invalid_cost_confidence")
    for iv in r.get("hours", []):
        day, o, c = iv["day"], iv["open_min"], iv["close_min"]
        if not (0 <= day <= 6 and 0 <= o < c <= 1440):
            errors.append("impossible_opening_interval")
            break
    if any(not is_valid_tag(t) for t in r.get("experience_tags", [])):
        errors.append("unknown_experience_tag")
    if any(not is_valid_mood(m) for m in r.get("mood_tags", [])):
        errors.append("unknown_mood")
    for key in ("prominence", "quality_score", "data_confidence"):
        v = r.get(key, 0)
        if not (0 <= v <= 1):
            errors.append(f"invalid_{key}")
    if not r.get("source_license"):
        errors.append("missing_license")
    if not r.get("source_urls"):
        errors.append("missing_source_url")
    return errors
