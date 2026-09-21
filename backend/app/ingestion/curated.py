"""Stage 7 - CURATED OVERLAY (data/curated/navigiq_curated.yaml).

Editorial knowledge NavigIQ authors itself: experience tags, a one-line
description, sensible visit durations, estimated cost bands, suitability and
regional behaviour for places that matter most for discovery.

THE RULE: curated data never supplies a coordinate. An entry either
  * annotates an existing OSM-derived POI (matched by wikidata id, OSM ref,
    or exact normalised name + category), or
  * creates a POI from OSM geometry: `from_place` (a gazetteer place node,
    e.g. a neighbourhood) or `from_osm` (an Overpass selector whose returned
    features' centres are averaged, e.g. the segments of Church Street).
An entry that matches nothing is reported in the manifest, never invented.

Cost bands here are ESTIMATES (cost_confidence = curated_estimate) and are
shown to users as such. Durations are on-site time only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.core.paths import data_dir
from app.domain.taxonomy import (
    category_catalog, is_valid_category, is_valid_mood, is_valid_tag,
)
from app.ingestion.normalize import normalize_name

SUITABILITY_KEYS = {"family_friendly", "kids_friendly", "senior_friendly", "couple_friendly",
                    "solo_friendly", "group_friendly"}
FLAG_KEYS = {"recommended_as_primary_destination", "requires_large_time_block",
             "short_escape", "day_trip_suitable"}


@dataclass
class CuratedEntry:
    key: str
    wikidata: str | None = None
    source_ref: str | None = None
    name: str | None = None
    match_category: str | None = None
    from_place: str | None = None
    from_osm: str | None = None
    # Limit a from_osm query to this distance from the centre: several towns
    # in the region have their own "MG Road" or "Brigade Road".
    from_osm_within_km: float | None = None
    from_wikidata: str | None = None
    category: str | None = None
    display_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    short_description: str | None = None
    experience_tags: list[str] = field(default_factory=list)
    remove_tags: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    editorial_score: float | None = None
    visit_duration: tuple[int, int, int] | None = None
    cost: tuple[int, int, int] | None = None
    suitability: dict[str, bool] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)


def _triple(value, what: str, key: str, allow_zero: bool) -> tuple[int, int, int] | None:
    if value is None:
        return None
    if len(value) != 3:
        raise ValueError(f"{key}: {what} must be [min, typical, max]")
    a, b, c = (int(v) for v in value)
    lo = 0 if allow_zero else 1
    if not (lo <= a <= b <= c):
        raise ValueError(f"{key}: {what} must satisfy {lo}<=min<=typical<=max")
    return a, b, c


def load_curated(path: Path | None = None) -> list[CuratedEntry]:
    path = path or (data_dir() / "curated" / "navigiq_curated.yaml")
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: list[CuratedEntry] = []
    seen: set[str] = set()
    catalog = category_catalog()
    for item in raw.get("entries", []):
        key = item["key"]
        if key in seen:
            raise ValueError(f"duplicate curated key {key!r}")
        seen.add(key)
        match = item.get("match", {})
        e = CuratedEntry(
            key=key,
            wikidata=match.get("wikidata"), source_ref=match.get("source_ref"),
            name=match.get("name"), match_category=match.get("category"),
            from_place=item.get("from_place"), from_osm=item.get("from_osm"),
            from_wikidata=item.get("from_wikidata"),
            from_osm_within_km=item.get("from_osm_within_km"),
            category=item.get("category"), display_name=item.get("display_name"),
            aliases=list(item.get("aliases", [])),
            short_description=item.get("short_description"),
            experience_tags=list(item.get("experience_tags", [])),
            remove_tags=list(item.get("remove_tags", [])),
            moods=list(item.get("moods", [])),
            editorial_score=item.get("editorial_score"),
            visit_duration=_triple(item.get("visit_duration"), "visit_duration", key, False),
            cost=_triple(item.get("cost"), "cost", key, True),
            suitability=dict(item.get("suitability", {})),
            flags=dict(item.get("flags", {})),
        )
        created = e.from_place or e.from_osm or e.from_wikidata
        if not (e.wikidata or e.source_ref or e.name or created):
            raise ValueError(f"{key}: needs a match or a from_place/from_osm/from_wikidata source")
        if created and not e.category:
            raise ValueError(f"{key}: created entries must set a category")
        for c in filter(None, (e.category, e.match_category)):
            if not is_valid_category(c) or catalog[c].theme:
                raise ValueError(f"{key}: invalid primary category {c!r}")
        for t in e.experience_tags + e.remove_tags:
            if not is_valid_tag(t):
                raise ValueError(f"{key}: unknown experience tag {t!r}")
        for m in e.moods:
            if not is_valid_mood(m):
                raise ValueError(f"{key}: unknown mood {m!r}")
        if e.editorial_score is not None and not 0 <= e.editorial_score <= 1:
            raise ValueError(f"{key}: editorial_score must be within 0-1")
        if set(e.suitability) - SUITABILITY_KEYS or set(e.flags) - FLAG_KEYS:
            raise ValueError(f"{key}: unknown suitability/flag keys")
        if e.short_description and len(e.short_description) > 300:
            raise ValueError(f"{key}: short_description over 300 characters")
        entries.append(e)
    return entries


def match_entry(entry: CuratedEntry, records: list[dict],
                by_wikidata: dict[str, dict], by_ref: dict[str, dict],
                by_name: dict[str, list[dict]]) -> dict | None:
    """The record an annotating entry applies to, or None.

    Name matches must be unambiguous after the category filter: when two
    records share a name, the one with a wikidata id wins; if that still
    leaves more than one, the entry is reported as ambiguous instead of
    guessing.
    """
    if entry.wikidata:
        return by_wikidata.get(entry.wikidata)
    if entry.source_ref:
        return by_ref.get(entry.source_ref)
    if entry.name:
        cands = by_name.get(normalize_name(entry.name), [])
        if entry.match_category:
            cands = [r for r in cands if r["category"] == entry.match_category]
        if len(cands) > 1:
            with_wd = [r for r in cands if r.get("wikidata_id")]
            if len(with_wd) == 1:
                return with_wd[0]
            return None
        return cands[0] if cands else None
    return None
