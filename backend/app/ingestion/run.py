"""CLI: run the POI ingestion pipeline end to end.

    python -m app.ingestion.run                 # full run (uses cached raw data)
    python -m app.ingestion.run --refresh       # re-download from Overpass/Wikimedia
    python -m app.ingestion.run --dry-run       # every stage except load
    python -m app.ingestion.run --report-only   # regenerate the quality report

Artifacts: data/artifacts/raw/ (cached responses), data/artifacts/stages/
(one JSONL per stage + manifest.json), data/artifacts/reports/ and
docs/data_quality_report.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from app.config import settings
from app.core.paths import artifacts_dir
from app.geo.regions import geo_config
from app.ingestion import curated as curated_mod
from app.ingestion import pipeline as P
from app.ingestion.gazetteer import DistrictIndex, PlaceIndex, fetch_districts
from app.ingestion.http import CachedClient
from app.ingestion.load import load_places, load_pois, sync_dsn
from app.ingestion.mapping import OSMMapping
from app.ingestion.overpass import GROUPS, OVERPASS_URLS, fetch_group
from app.ingestion.report import build_report, write_report
from app.ingestion.wiki import (
    fetch_commons_images, fetch_wikidata, fetch_wikipedia_intros,
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(*, refresh: bool = False, dry_run: bool = False, skip_wiki: bool = False) -> dict:
    cfg = geo_config()
    manifest = P.Manifest()
    dsn = sync_dsn(settings.DATABASE_URL)

    # 1. extract ---------------------------------------------------------------
    raw: dict[str, dict] = {}
    osm_base = None
    with CachedClient("overpass", min_interval_s=5.0, timeout_s=900, retries=3,
                      refresh=refresh) as client:
        for group in GROUPS:
            raw[group.name] = fetch_group(client, group, cfg.center_lat, cfg.center_lon,
                                          cfg.radius_km)
            osm_base = osm_base or raw[group.name].get("osm3s", {}).get("timestamp_osm_base")
            log(f"extract {group.name}: {len(raw[group.name].get('elements', []))} elements")
        districts_body = fetch_districts(client, cfg.center_lat, cfg.center_lon, cfg.radius_km)
        manifest.record("extract", network_calls=client.network_calls,
                        cache_hits=client.cache_hits, osm_base=osm_base,
                        **{f"{k}_elements": len(v.get("elements", [])) for k, v in raw.items()})

    # 2. geographic filter -----------------------------------------------------------
    records = P.geo_filter(raw, cfg, manifest)
    places = P.geo_filter_places(raw["places"].get("elements", []), cfg)
    manifest.record("gazetteer", places=len(places))
    place_index = PlaceIndex(places)
    districts = DistrictIndex(districts_body)
    manifest.record("gazetteer", districts=[d[0] for d in districts.districts])
    P.write_stage("02_geo", records)
    log(f"geo filter: {len(records)} records, {len(places)} places, "
        f"{len(districts.districts)} districts")

    # 3+4. normalize and categorize ---------------------------------------------------
    records = P.normalize_and_categorize(records, OSMMapping(), manifest)
    P.write_stage("04_categorized", records)
    log(f"categorize: {len(records)} kept")

    # 5. deduplicate -------------------------------------------------------------------
    records = P.deduplicate(records, manifest)
    P.write_stage("05_deduplicated", records)
    log(f"dedupe: {len(records)} kept")

    # 5a. link OSM features to Wikidata by name + location; add notable
    #     Wikidata-only places (their own recorded coordinates) ----------------
    from app.ingestion.wikidata_geo import fetch_items, items_to_records, link, name_score
    from app.geo.distance import haversine_km
    with CachedClient("wikidata_sparql", min_interval_s=1.0, timeout_s=120, retries=3,
                      refresh=refresh) as client:
        wd_items = fetch_items(client, cfg.center_lat, cfg.center_lon, cfg.radius_km)
    linked = link(records, wd_items)
    additions = []
    for rec in items_to_records(linked["unmatched"], cfg):
        near_same = any(haversine_km(rec["lat"], rec["lon"], r["lat"], r["lon"]) <= 1.5
                        and name_score(rec["name"], r["name"]) >= 80 for r in records)
        if not near_same:
            additions.append(rec)
    records += additions
    records.sort(key=lambda r: r["source_ref"])
    manifest.record("wikidata_link", items=len(wd_items), linked=linked["linked"],
                    added_wikidata_only=len(additions))
    log(f"wikidata: {len(wd_items)} items, {linked['linked']} linked, {len(additions)} added")

    # curated geometry-backed creations join before enrichment
    entries = curated_mod.load_curated()
    created = []
    with CachedClient("overpass", min_interval_s=5.0, timeout_s=300, retries=3,
                      refresh=refresh) as client:
        for e in entries:
            rec = None
            if e.from_wikidata:
                rec = P.created_from_wikidata(e, wd_items, cfg)
            elif e.from_place:
                rec = P.created_from_place(e, places, cfg)
            elif e.from_osm:
                within = e.from_osm_within_km or (cfg.radius_km + 1)
                q = (f"[out:json][timeout:120];{e.from_osm}"
                     f"(around:{int(within * 1000)},{cfg.center_lat},"
                     f"{cfg.center_lon});out tags center bb qt;")
                body = None
                for url in OVERPASS_URLS:
                    try:
                        body = client.fetch_json(url, method="POST", data={"data": q},
                                                 cache_as="overpass")
                        break
                    except Exception:  # noqa: BLE001
                        continue
                if body:
                    rec = P.created_from_features(e, body.get("elements", []), cfg)
            if rec:
                created.append(rec)
    by_ref = {r["source_ref"]: r for r in records}
    by_qid = {r["wikidata_id"]: r for r in records if r.get("wikidata_id")}
    for c in created:
        existing = by_ref.get(c["source_ref"]) or (
            by_qid.get(c["wikidata_id"]) if c.get("wikidata_id") else None)
        if existing is not None:
            # Same feature already present (e.g. auto-added from Wikidata):
            # the curated entry annotates it instead of duplicating it.
            existing["curated_key"] = c["curated_key"]
            existing["category"] = c["category"]
            existing["query_group"] = "curated"
        else:
            records.append(c)
    records.sort(key=lambda r: r["source_ref"])

    # 6. enrich ----------------------------------------------------------------------------
    wikidata, wikipedia, images = {}, {}, {}
    if not skip_wiki:
        with CachedClient("wikimedia", min_interval_s=0.5, timeout_s=60, retries=4,
                          refresh=refresh) as client:
            wikidata = fetch_wikidata(client, [r["wikidata_id"] for r in records
                                               if r["wikidata_id"]])
            titles = set()
            for r in records:
                wd = wikidata.get(r["wikidata_id"]) if r["wikidata_id"] else None
                if wd and wd.enwiki_title:
                    titles.add(wd.enwiki_title)
                else:
                    t = P.wikipedia_title_from_tag(r["tags"].get("wikipedia"))
                    if t:
                        titles.add(t)
            wikipedia = fetch_wikipedia_intros(client, sorted(titles))
            images = fetch_commons_images(client, [w.image_file for w in wikipedia.values()
                                                   if w.image_file])
            manifest.record("enrich", wikidata_entities=len(wikidata),
                            wikipedia_articles=len(wikipedia), free_images=len(images),
                            network_calls=client.network_calls, cache_hits=client.cache_hits)
        log(f"enrich: {len(wikidata)} wikidata, {len(wikipedia)} wikipedia, "
            f"{len(images)} images")

    # 7. tag --------------------------------------------------------------------------------
    records = P.enrich_and_tag(records, wikidata=wikidata, wikipedia=wikipedia, images=images,
                               places=place_index, districts=districts, manifest=manifest)

    # 8. curate -----------------------------------------------------------------------------
    records = P.apply_curated(records, entries, manifest)

    # 9. score, 10. validate ----------------------------------------------------------------
    records = P.score_records(records, manifest)
    records = P.finalize(records, manifest)
    P.write_stage("10_final", records)
    log(f"final: {len(records)} records, "
        f"{sum(r['recommendable'] for r in records)} recommendable")

    (artifacts_dir() / "stages" / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, default=str), encoding="utf-8")
    if dry_run:
        log("dry run: nothing loaded")
        return manifest.to_dict()

    # 11. load -----------------------------------------------------------------------------
    manifest.record("load", **load_pois(dsn, records, source_updated_at=osm_base))
    manifest.record("load_places", **load_places(dsn, places, cfg, districts))
    log(f"load: {manifest.stages['load']} places {manifest.stages['load_places']}")
    (artifacts_dir() / "stages" / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, default=str), encoding="utf-8")

    # 12. report ---------------------------------------------------------------------------
    rep = build_report(dsn, manifest.to_dict())
    j, m = write_report(rep)
    log(f"report: {j} and {m}")
    return manifest.to_dict()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NavigIQ POI ingestion")
    ap.add_argument("--refresh", action="store_true", help="bypass the raw response cache")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-wiki", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)
    if args.report_only:
        manifest_path = artifacts_dir() / "stages" / "manifest.json"
        manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                    if manifest_path.exists() else None)
        j, m = write_report(build_report(sync_dsn(settings.DATABASE_URL), manifest))
        log(f"report: {j} and {m}")
        return 0
    run(refresh=args.refresh, dry_run=args.dry_run, skip_wiki=args.skip_wiki)
    return 0


if __name__ == "__main__":
    sys.exit(main())
