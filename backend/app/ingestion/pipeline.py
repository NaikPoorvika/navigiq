"""The POI ingestion pipeline (ADR-026).

    extract -> geographic filter -> normalize -> categorize -> deduplicate
            -> enrich -> tag -> curate -> score -> validate -> load -> report

Every stage is a pure function over plain dicts (so it is unit-testable) and
writes an inspectable artifact under data/artifacts/stages/. The manifest
records counts in, out and every drop reason per stage.

Idempotent: inputs are cached raw responses, ordering is deterministic
(sorted by source_ref), and the loader upserts on (source, source_ref) with a
content hash. A second identical run writes zero rows.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.core.paths import artifacts_dir
from app.domain.taxonomy import category_catalog, moods_for
from app.geo.distance import haversine_km
from app.geo.regions import GeoConfig, distance_from_center_km, in_envelope, region_bucket
from app.ingestion import curated as curated_mod
from app.ingestion.gazetteer import DistrictIndex, PlaceIndex, PlaceRec, assign_locality
from app.ingestion.hours import RELIABLE_THRESHOLD, resolve_hours
from app.ingestion.mapping import OSMMapping, is_notable
from app.ingestion.normalize import (
    alias_candidates, chain_key, clean_display_name, is_generic_name, normalize_name, slugify,
)
from app.ingestion.overpass import element_to_record
from app.ingestion.scoring import (
    data_confidence, name_quality, prominence, quality, recommendable,
)
from app.ingestion.tagging import derive_tags
from app.ingestion.validate import validate_record
from app.ingestion.wiki import (
    WIKIPEDIA_LICENSE, ImageInfo, WikidataInfo, WikipediaInfo, first_sentences, valid_qid,
)

OSM_LICENSE = "ODbL-1.0"
DUPLICATE_RADIUS_M = 150.0
CHAIN_MIN_BRANCHES = 4
BRAND_QID_SPREAD_KM = 1.0
MAX_DESCRIPTION_CHARS = 1200


@dataclass
class Manifest:
    stages: dict[str, dict] = field(default_factory=dict)

    def record(self, stage: str, **counts) -> None:
        self.stages.setdefault(stage, {}).update(counts)

    def to_dict(self) -> dict:
        return {"stages": self.stages}


def write_stage(name: str, records: list[dict]) -> Path:
    d = artifacts_dir() / "stages"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return path


# --- 2. geographic filter ---------------------------------------------------------

def geo_filter(raw_groups: dict[str, dict], cfg: GeoConfig, manifest: Manifest) -> list[dict]:
    """Flatten Overpass groups, merge repeats of one element, apply the
    inclusive envelope, attach distance and region bucket."""
    by_ref: dict[str, dict] = {}
    stats = Counter()
    for group in sorted(raw_groups):
        if group == "places":
            continue
        for el in raw_groups[group].get("elements", []):
            stats["elements"] += 1
            rec = element_to_record(el, group)
            if rec is None:
                stats["no_coordinates"] += 1
                continue
            if rec["source_ref"] in by_ref:
                stats["repeat_across_groups"] += 1
                continue
            d = distance_from_center_km(rec["lat"], rec["lon"], cfg)
            if not in_envelope(d, cfg):
                stats["outside_envelope"] += 1
                continue
            rec["distance_from_center_km"] = round(d, 3)
            rec["region_bucket"] = region_bucket(d, cfg).value
            by_ref[rec["source_ref"]] = rec
    out = [by_ref[k] for k in sorted(by_ref)]
    manifest.record("geo_filter", **stats, kept=len(out))
    return out


def geo_filter_places(elements: list[dict], cfg: GeoConfig) -> list[PlaceRec]:
    from app.ingestion.gazetteer import places_from_overpass
    kept = []
    for p in places_from_overpass(elements):
        if in_envelope(distance_from_center_km(p.lat, p.lon, cfg), cfg):
            kept.append(p)
    return kept


# --- 3+4. normalize and categorize ----------------------------------------------------

def normalize_and_categorize(records: list[dict], mapping: OSMMapping,
                             manifest: Manifest) -> list[dict]:
    out = []
    drops = Counter()
    for rec in records:
        tags = rec["tags"]
        raw_name = tags.get("name:en") or tags.get("name")
        name = clean_display_name(raw_name) if raw_name else None
        res = mapping.resolve(tags, name, rec.get("extent_m"), rec["osm_type"])
        if res.category is None:
            drops[res.drop_reason or "unmapped"] += 1
            continue
        qid = valid_qid(tags.get("wikidata"))
        out.append({
            **rec,
            "name": name,
            "name_normalized": normalize_name(name),
            "category": res.category,
            "secondary": res.secondary,
            "rule_tags": res.tags,
            "rule_index": res.rule_index,
            "wikidata_id": qid,
            "aliases": alias_candidates(tags, name),
            "generic_name": is_generic_name(name),
        })
    manifest.record("categorize", input=len(records), kept=len(out), **{
        f"dropped_{k}": v for k, v in sorted(drops.items())})
    return out


# --- 5. deduplicate -------------------------------------------------------------------

def _richness(r: dict) -> tuple:
    return (bool(r.get("wikidata_id")), len(r["tags"]), r["osm_type"] != "node",
            -int(r["source_ref"].split("/")[1]))


def deduplicate(records: list[dict], manifest: Manifest) -> list[dict]:
    stats = Counter()
    # Brand ids mis-tagged as wikidata: one QID on several places > 1 km apart
    # is a franchise, not a place. Clear it so branches are neither merged nor
    # handed the brand's Wikipedia article.
    by_qid: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r["wikidata_id"]:
            by_qid[r["wikidata_id"]].append(r)
    for qid, group in by_qid.items():
        if len(group) < 2:
            continue
        spread = max(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
                     for a in group for b in group)
        if spread > BRAND_QID_SPREAD_KM:
            for r in group:
                r["tags"] = {**r["tags"], "brand:wikidata": r["tags"].get("brand:wikidata", qid)}
                r["wikidata_id"] = None
            stats["brand_qids_cleared"] += 1

    kept: list[dict] = []
    seen_qid: dict[str, dict] = {}
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(records, key=_richness, reverse=True):
        qid = r["wikidata_id"]
        if qid and qid in seen_qid:
            _merge_into(seen_qid[qid], r)
            stats["merged_wikidata"] += 1
            continue
        dup = next((o for o in by_name[r["name_normalized"]]
                    if haversine_km(r["lat"], r["lon"], o["lat"], o["lon"]) * 1000
                    < DUPLICATE_RADIUS_M), None)
        if dup is not None:
            _merge_into(dup, r)
            stats["merged_name_proximity"] += 1
            continue
        if qid:
            seen_qid[qid] = r
        by_name[r["name_normalized"]].append(r)
        kept.append(r)

    # Chains: brand tags, or a normalised name repeated across the region.
    name_counts = Counter(r["name_normalized"] for r in kept
                          if r["category"] in ("cafe", "restaurant", "street_food", "dessert",
                                               "nightlife", "shopping", "mall", "gaming",
                                               "entertainment"))
    for r in kept:
        key = chain_key(r["tags"], r["name"])
        if key is None and name_counts.get(r["name_normalized"], 0) >= CHAIN_MIN_BRANCHES:
            key = f"name:{r['name_normalized']}"[:80]
        r["chain_key"] = key
        r["is_chain"] = key is not None
        stats["chain_branches"] += int(r["is_chain"])
    kept.sort(key=lambda r: r["source_ref"])
    manifest.record("deduplicate", input=len(records), kept=len(kept), **stats)
    return kept


def _merge_into(keep: dict, dup: dict) -> None:
    aliases = set(keep["aliases"]) | set(dup["aliases"])
    if dup["name"] and normalize_name(dup["name"]) != keep["name_normalized"]:
        aliases.add(dup["name"])
    keep["aliases"] = sorted(aliases)
    for k, v in dup["tags"].items():
        keep["tags"].setdefault(k, v)
    keep.setdefault("merged_refs", []).append(dup["source_ref"])


# --- 6+7. enrich, locality and tags -----------------------------------------------------

def wikipedia_title_from_tag(value: str | None) -> str | None:
    if not value or not value.startswith("en:"):
        return None
    return value[3:].strip() or None


def enrich_and_tag(records: list[dict], *, wikidata: dict[str, WikidataInfo],
                   wikipedia: dict[str, WikipediaInfo], images: dict[str, ImageInfo],
                   places: PlaceIndex, districts: DistrictIndex | None,
                   manifest: Manifest) -> list[dict]:
    stats = Counter()
    for r in records:
        tags = r["tags"]
        wd = wikidata.get(r["wikidata_id"]) if r["wikidata_id"] else None
        title = (wd.enwiki_title if wd and wd.enwiki_title
                 else wikipedia_title_from_tag(tags.get("wikipedia")))
        wp = wikipedia.get(title) if title else None
        r["wikipedia_title"] = wp.title if wp else None
        r["sitelinks"] = wd.sitelinks if wd else 0
        aliases = set(r["aliases"])
        label = _display_label(wd.label if wd else None)
        if label and normalize_name(label) != r["name_normalized"] and r["category"] not in (
                "cafe", "restaurant", "street_food", "dessert", "nightlife"):
            # The English Wikidata label is usually the name people search for
            # ("Skandagiri", not the OSM "Kalawara Betta"); keep the OSM name too.
            aliases.add(r["name"])
            r["name"] = label
            r["name_normalized"] = normalize_name(label)
        if wd:
            if wd.label and normalize_name(wd.label) != r["name_normalized"]:
                aliases.add(wd.label)
            aliases.update(a for a in wd.aliases if normalize_name(a) != r["name_normalized"])
        r["aliases"] = sorted(a for a in aliases if 2 <= len(a) <= 120)[:15]

        if r["source"] == "wikidata":
            source_urls, source_names, licenses = [], [], ["CC0-1.0 (Wikidata)"]
        else:
            source_urls = [f"https://www.openstreetmap.org/{r['source_ref']}"]
            source_names = ["OpenStreetMap"]
            licenses = [OSM_LICENSE]
        r["description"] = None
        r["short_description"] = None
        r["description_source"] = None
        if wp:
            desc = wp.extract
            if len(desc) > MAX_DESCRIPTION_CHARS:
                desc = first_sentences(desc, MAX_DESCRIPTION_CHARS)
            r["description"] = desc
            r["short_description"] = first_sentences(wp.extract, 240)
            r["description_source"] = "wikipedia"
            source_urls.append(wp.url)
            source_names.append("Wikipedia")
            licenses.append(WIKIPEDIA_LICENSE)
            stats["wikipedia_description"] += 1
        elif wd and wd.description:
            r["short_description"] = wd.description[0].upper() + wd.description[1:]
            r["description_source"] = "wikidata"
            stats["wikidata_description"] += 1
        if wd:
            source_urls.append(f"https://www.wikidata.org/wiki/{wd.qid}")
            source_names.append("Wikidata")
        img = images.get(wp.image_file) if wp and wp.image_file else None
        r["image_url"] = img.thumb_url if img else None
        r["image_attribution"] = ({"artist": img.artist, "license": img.license,
                                   "source_url": img.description_url, "file": img.file}
                                  if img else None)
        stats["free_images"] += int(img is not None)
        r["source_urls"] = source_urls
        r["source_names"] = source_names
        r["source_license"] = "; ".join(dict.fromkeys(licenses))

        locality, hood = assign_locality(places, r["lat"], r["lon"])
        r["locality"] = tags.get("addr:suburb") or locality
        r["neighborhood"] = hood
        r["district"] = districts.lookup(r["lat"], r["lon"]) if districts else None
        r["address"] = _address(tags)

        notable = bool(wd or wp or is_notable(tags))
        t = derive_tags(category=r["category"], secondary=r["secondary"],
                        rule_tags=r["rule_tags"], osm=tags,
                        region_bucket=r["region_bucket"],
                        distance_km=r["distance_from_center_km"],
                        extent_m=r.get("extent_m"), notable=notable, is_chain=r["is_chain"])
        r.update({
            "experience_tags": t.experience_tags, "mood_tags": t.mood_tags,
            "food_tags": t.food_tags, "dietary_tags": t.dietary_tags,
            "activity_tags": t.activity_tags, "accessibility_tags": t.accessibility_tags,
            "indoor_outdoor": t.indoor_outdoor, "weather_suitability": t.weather_suitability,
            "suitability": t.suitability, "visit_duration": list(t.visit_duration),
            "cost": list(t.cost), "cost_confidence": t.cost_confidence, **t.regional,
            "notable": notable,
        })
        hours = resolve_hours(tags.get("opening_hours"), r["category"])
        r["opening_hours_raw"] = tags.get("opening_hours")
        r["hours"] = [{"day": i.day, "open_min": i.open_min, "close_min": i.close_min,
                       "is_24h": i.is_24h} for i in hours.intervals]
        r["hours_source"] = hours.source
        r["opening_hours_confidence"] = hours.confidence
        stats[f"hours_{hours.source}"] += 1
    manifest.record("enrich_tag", records=len(records), **stats)
    return records


_CITY_SUFFIX = re.compile(r",\s*(bangalore|bengaluru|karnataka|india|bangalore urban|"
                          r"bangalore rural)(,.*)?$", re.IGNORECASE)


def _display_label(label: str | None) -> str | None:
    if not label or re.fullmatch(r"Q\d+", label) or len(label) > 60:
        return None
    if not re.search(r"[A-Za-z]", label):
        return None
    return _CITY_SUFFIX.sub("", label).strip() or None


def _address(tags: dict) -> str | None:
    parts = [tags.get(k) for k in ("addr:housenumber", "addr:street", "addr:suburb",
                                   "addr:city", "addr:postcode") if tags.get(k)]
    return ", ".join(parts)[:300] if parts else None


# --- 8. curated overlay ------------------------------------------------------------------

def apply_curated(records: list[dict], entries: list[curated_mod.CuratedEntry],
                  manifest: Manifest) -> list[dict]:
    """Overlay curated entries. Records created from curated geometry are
    already in `records` (marked with curated_key) and were enriched with
    everything else, so they are matched by key here."""
    created = [r for r in records if r.get("query_group") == "curated"]
    by_qid = {r["wikidata_id"]: r for r in records if r["wikidata_id"]}
    by_ref = {r["source_ref"]: r for r in records}
    for r in records:
        for m in r.get("merged_refs", []):
            by_ref.setdefault(m, r)
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_name[r["name_normalized"]].append(r)
        for a in r["aliases"]:
            by_name[normalize_name(a)].append(r)
    stats = Counter()
    unmatched = []
    for e in entries:
        if e.from_place or e.from_osm or e.from_wikidata:
            target = next((c for c in created if c.get("curated_key") == e.key), None)
        else:
            target = curated_mod.match_entry(e, records, by_qid, by_ref, by_name)
        if target is None:
            unmatched.append(e.key)
            continue
        _overlay(target, e)
        stats["applied"] += 1
    manifest.record("curate", entries=len(entries), created=len(created),
                    unmatched=len(unmatched), unmatched_keys=unmatched, **stats)
    return records


ABSORB_RADIUS_M = 300.0


def absorb_curated_duplicates(records: list[dict], manifest: Manifest) -> list[dict]:
    """Fold raw features that duplicate a curated place into it.

    Curation often anchors a landmark on its Wikidata item while OSM carries
    the same place as separate, differently-named nodes (the Wikidata item
    "Dodda Basavana Gudi" and two OSM nodes "Bull Temple"). Once curation has
    given the landmark its aliases, any non-curated record within 300 m whose
    name equals the landmark's name or an alias, in the same category group,
    and without a conflicting Wikidata id, is the same place: it is merged
    (its reference kept in merged_refs) instead of competing with it in
    search and recommendations."""
    catalog = category_catalog()

    def group(r: dict) -> str:
        info = catalog.get(r["category"])
        return info.group if info else "other"

    names: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("curated"):
            for n in {r["name_normalized"], normalize_name(r["name"]),
                      *(normalize_name(a) for a in r["aliases"])}:
                if n:
                    names[n].append(r)
    absorbed: set[int] = set()
    for r in records:
        if r.get("curated") or r["name_normalized"] not in names:
            continue
        for c in names[r["name_normalized"]]:
            if c is r or group(c) != group(r):
                continue
            if r["wikidata_id"] and c["wikidata_id"] and r["wikidata_id"] != c["wikidata_id"]:
                continue
            if haversine_km(r["lat"], r["lon"], c["lat"], c["lon"]) * 1000 > ABSORB_RADIUS_M:
                continue
            _merge_into(c, r)
            absorbed.add(id(r))
            break
    manifest.record("absorb_curated_duplicates", absorbed=len(absorbed))
    return [r for r in records if id(r) not in absorbed]


def _overlay(r: dict, e: curated_mod.CuratedEntry) -> None:
    r["curated"] = True
    r["curated_key"] = e.key
    if e.category and e.category != r["category"]:
        # A new category brings its own defaults (indoor/outdoor, durations,
        # cost band, tags): re-derive them from the same source tags before
        # the curated values are layered on top.
        r["category"] = e.category
        r["secondary"] = [s for s in r["secondary"] if s[0] != e.category]
        t = derive_tags(category=e.category, secondary=r["secondary"], rule_tags=[],
                        osm=r["tags"], region_bucket=r["region_bucket"],
                        distance_km=r["distance_from_center_km"], extent_m=r.get("extent_m"),
                        notable=r.get("notable", False), is_chain=r["is_chain"])
        r.update({
            "experience_tags": t.experience_tags, "mood_tags": t.mood_tags,
            "indoor_outdoor": t.indoor_outdoor, "weather_suitability": t.weather_suitability,
            "suitability": t.suitability, "visit_duration": list(t.visit_duration),
            "cost": list(t.cost), "cost_confidence": t.cost_confidence, **t.regional,
        })
        hours = resolve_hours(r["tags"].get("opening_hours"), e.category)
        r["hours"] = [{"day": i.day, "open_min": i.open_min, "close_min": i.close_min,
                       "is_24h": i.is_24h} for i in hours.intervals]
        r["hours_source"] = hours.source
        r["opening_hours_confidence"] = hours.confidence
    if e.display_name:
        if normalize_name(r["name"]) != normalize_name(e.display_name):
            r["aliases"] = sorted(set(r["aliases"]) | {r["name"]})
        r["name"] = e.display_name
        r["name_normalized"] = normalize_name(e.display_name)
    if e.aliases:
        r["aliases"] = sorted(set(r["aliases"]) | {a for a in e.aliases
                                                   if normalize_name(a) != r["name_normalized"]})
    if e.short_description:
        r["short_description"] = e.short_description
        if not r.get("description"):
            r["description"] = e.short_description
            r["description_source"] = "curated"
        r["source_names"] = list(dict.fromkeys(r["source_names"] + ["NavigIQ editorial"]))
    tags = (set(r["experience_tags"]) | set(e.experience_tags)) - set(e.remove_tags)
    r["experience_tags"] = sorted(tags)
    if {"indoor", "rain_friendly"} & set(e.remove_tags) and r["indoor_outdoor"] != "outdoor":
        r["indoor_outdoor"] = "outdoor"
        r["weather_suitability"] = "dry_weather"
    secondary = {s for s, _ in r["secondary"]}
    r["mood_tags"] = sorted(set(moods_for(tags, r["category"], secondary)) | set(e.moods))
    if e.editorial_score is not None:
        r["editorial_score"] = e.editorial_score
    if e.visit_duration:
        r["visit_duration"] = list(e.visit_duration)
    if e.cost:
        r["cost"] = list(e.cost)
        r["cost_confidence"] = "curated_estimate"
    r["suitability"] = {**r["suitability"], **e.suitability}
    for k, v in e.flags.items():
        r[k] = v


def created_from_place(entry: curated_mod.CuratedEntry, places: list[PlaceRec],
                       cfg: GeoConfig) -> dict | None:
    target = normalize_name(entry.from_place)
    matches = [p for p in places if p.name_normalized == target
               or target in {normalize_name(a) for a in p.aliases}]
    if not matches:
        return None
    p = sorted(matches, key=lambda p: (-p.importance, p.source_ref))[0]
    return _created_record(entry, p.source_ref, p.name, p.lat, p.lon, {"place": p.place_type},
                           cfg)


def created_from_features(entry: curated_mod.CuratedEntry, elements: list[dict],
                          cfg: GeoConfig) -> dict | None:
    pts = []
    refs = []
    for el in elements:
        rec = element_to_record(el, "curated")
        if rec:
            pts.append((rec["lat"], rec["lon"]))
            refs.append(rec["source_ref"])
    if not pts:
        return None
    lat = sum(p[0] for p in pts) / len(pts)
    lon = sum(p[1] for p in pts) / len(pts)
    name = entry.display_name or entry.from_osm
    ref = sorted(refs)[0]
    return _created_record(entry, ref, name, lat, lon, {"segments": str(len(pts))}, cfg)


def created_from_wikidata(entry: curated_mod.CuratedEntry, items: list, cfg: GeoConfig) -> dict | None:
    """A curated POI placed at the Wikidata item's own recorded coordinate."""
    it = next((i for i in items if i.qid == entry.from_wikidata), None)
    if it is None:
        return None
    rec = _created_record(entry, it.qid, entry.display_name or it.label, it.lat, it.lon,
                          {"wikidata": it.qid, "wikipedia": f"en:{it.enwiki}"}, cfg,
                          source="wikidata")
    if rec:
        rec["wikidata_id"] = it.qid
    return rec


def _created_record(entry, source_ref: str, name: str, lat: float, lon: float, tags: dict,
                    cfg: GeoConfig, source: str = "osm") -> dict | None:
    d = distance_from_center_km(lat, lon, cfg)
    if not in_envelope(d, cfg):
        return None
    osm_type, _, osm_id = source_ref.partition("/")
    return {
        "source": source, "source_ref": f"{source_ref}", "osm_type": osm_type if osm_id else source,
        "osm_id": int(osm_id) if osm_id.isdigit() else 0, "lat": round(lat, 7), "lon": round(lon, 7),
        "extent_m": None, "tags": tags, "query_group": "curated",
        "distance_from_center_km": round(d, 3), "region_bucket": region_bucket(d, cfg).value,
        "name": entry.display_name or name, "name_normalized": normalize_name(
            entry.display_name or name),
        "category": entry.category, "secondary": [], "rule_tags": [], "rule_index": None,
        "wikidata_id": None, "aliases": [], "generic_name": False, "is_chain": False,
        "chain_key": None, "curated_key": entry.key,
    }


# --- 9. score -------------------------------------------------------------------------------

def score_records(records: list[dict], manifest: Manifest) -> list[dict]:
    for r in records:
        curated = bool(r.get("curated"))
        prom, parts = prominence(
            r["tags"], has_wikidata=bool(r.get("wikidata_id")),
            has_enwiki=bool(r.get("wikipedia_title")), sitelinks=r.get("sitelinks", 0),
            curated_landmark=curated and (r.get("editorial_score") or 0) >= 0.8)
        conf = data_confidence(
            has_description=bool(r.get("description") or r.get("short_description")),
            hours_reliable=r["opening_hours_confidence"] >= RELIABLE_THRESHOLD,
            cost_confidence=r["cost_confidence"],
            has_locality=bool(r.get("locality")), has_wikidata=bool(r.get("wikidata_id")),
            tags=r["tags"], curated=curated)
        q, qparts = quality(
            prominence_score=prom, confidence=conf, category=r["category"],
            name_q=name_quality(r["name"], r["generic_name"]), is_chain=r["is_chain"],
            curated=curated, editorial=r.get("editorial_score"))
        r["prominence"] = prom
        r["prominence_parts"] = {**parts, "quality_parts": qparts}
        r["data_confidence"] = conf
        r["quality_score"] = q
        r["curated"] = curated
        r["recommendable"] = recommendable(
            quality_score=q, curated=curated, generic=r["generic_name"], active=True,
            category=r["category"], name=r["name"],
            notable=bool(r.get("wikidata_id") or r.get("wikipedia_title")
                         or r["tags"].get("tourism")))
    manifest.record("score", records=len(records),
                    recommendable=sum(r["recommendable"] for r in records))
    return records


# --- 10. validate + finalize ------------------------------------------------------------------

def finalize(records: list[dict], manifest: Manifest) -> list[dict]:
    catalog = category_catalog()
    out = []
    rejects = Counter()
    used_slugs: set[str] = set()
    for r in sorted(records, key=lambda r: r["source_ref"]):
        suffix = r["source_ref"].replace("/", "")
        r["slug"] = slugify(r["name"], suffix)
        if r["slug"] in used_slugs:
            rejects["duplicate_slug"] += 1
            continue
        r["search_text"] = _search_text(r, catalog)
        errors = validate_record(r)
        if errors:
            for e in errors:
                rejects[e] += 1
            continue
        used_slugs.add(r["slug"])
        r["content_hash"] = content_hash(r)
        out.append(r)
    manifest.record("validate", input=len(records), kept=len(out),
                    **{f"rejected_{k}": v for k, v in sorted(rejects.items())})
    return out


def _search_text(r: dict, catalog) -> str:
    parts = [r["name"], *r["aliases"], catalog[r["category"]].name,
             r.get("locality") or "", r.get("neighborhood") or "",
             " ".join(t.replace("_", " ") for t in r["experience_tags"]),
             " ".join(r.get("food_tags", [])), r.get("short_description") or ""]
    text = " ".join(p for p in parts if p)
    return re.sub(r"\s+", " ", normalize_name(text))[:2000]


HASHED_FIELDS = (
    "name", "name_normalized", "aliases", "lat", "lon", "category", "secondary",
    "description", "short_description", "description_source", "distance_from_center_km",
    "region_bucket", "district", "locality", "neighborhood", "address", "experience_tags",
    "mood_tags", "food_tags", "dietary_tags", "activity_tags", "accessibility_tags",
    "indoor_outdoor", "weather_suitability", "opening_hours_raw", "opening_hours_confidence",
    "hours", "visit_duration", "cost", "cost_confidence", "prominence", "quality_score",
    "editorial_score", "data_confidence", "curated", "recommendable", "suitability",
    "recommended_as_primary_destination", "requires_large_time_block", "short_escape",
    "day_trip_suitable", "is_chain", "chain_key", "wikidata_id", "wikipedia_title",
    "image_url", "image_attribution", "source_urls", "source_names", "source_license",
    "slug", "search_text", "tags", "prominence_parts",
)


def content_hash(r: dict) -> str:
    payload = {k: r.get(k) for k in HASHED_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
