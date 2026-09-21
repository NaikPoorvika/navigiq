"""Stage 11 - LOAD into Postgres, idempotently.

  * POIs upsert on (source, source_ref). A row is written only when its
    content hash changed; unchanged rows are skipped, so an identical second
    run reports inserted=0, updated=0.
  * Child rows (aliases, category links, opening hours) are rewritten only for
    inserted/updated POIs.
  * POIs from a previous run that no longer appear are DEACTIVATED, never
    deleted - saved places, interactions and old itineraries keep their FK.
  * Places (gazetteer) upsert on source_ref the same way.
"""
from __future__ import annotations

import json
from collections import Counter

import psycopg

from app.domain.taxonomy import category_catalog


def sync_dsn(database_url: str) -> str:
    return (database_url.replace("postgresql+asyncpg://", "postgresql://")
            .replace("postgresql+psycopg://", "postgresql://"))


UPSERT_SQL = """
INSERT INTO pois (
    source, source_ref, slug, name, name_normalized, short_description, description,
    description_source, geom, address, distance_from_center_km, region_bucket, district,
    locality, neighborhood, primary_category, tags, experience_tags, mood_tags, food_tags,
    dietary_tags, activity_tags, accessibility_tags, indoor_outdoor, weather_suitability,
    opening_hours_raw, opening_hours_confidence, visit_duration_min, visit_duration_typical,
    visit_duration_max, estimated_cost_min, estimated_cost_typical, estimated_cost_max,
    cost_confidence, prominence, prominence_parts, quality_score, editorial_score,
    data_confidence, curated, recommendable, family_friendly, kids_friendly, senior_friendly,
    couple_friendly, solo_friendly, group_friendly, recommended_as_primary_destination,
    requires_large_time_block, short_escape, day_trip_suitable, is_chain, chain_key,
    wikidata_id, wikipedia_title, image_url, image_attribution, source_urls, source_names,
    source_license, source_updated_at, search_text, active, content_hash, updated_at
) VALUES (
    %(source)s, %(source_ref)s, %(slug)s, %(name)s, %(name_normalized)s,
    %(short_description)s, %(description)s, %(description_source)s,
    ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(address)s,
    %(distance_from_center_km)s, %(region_bucket)s, %(district)s, %(locality)s,
    %(neighborhood)s, %(category_id)s, %(tags)s, %(experience_tags)s, %(mood_tags)s,
    %(food_tags)s, %(dietary_tags)s, %(activity_tags)s, %(accessibility_tags)s,
    %(indoor_outdoor)s, %(weather_suitability)s, %(opening_hours_raw)s,
    %(opening_hours_confidence)s, %(dmin)s, %(dtyp)s, %(dmax)s, %(cmin)s, %(ctyp)s, %(cmax)s,
    %(cost_confidence)s, %(prominence)s, %(prominence_parts)s, %(quality_score)s,
    %(editorial_score)s, %(data_confidence)s, %(curated)s, %(recommendable)s,
    %(family_friendly)s, %(kids_friendly)s, %(senior_friendly)s, %(couple_friendly)s,
    %(solo_friendly)s, %(group_friendly)s, %(recommended_as_primary_destination)s,
    %(requires_large_time_block)s, %(short_escape)s, %(day_trip_suitable)s, %(is_chain)s,
    %(chain_key)s, %(wikidata_id)s, %(wikipedia_title)s, %(image_url)s,
    %(image_attribution)s, %(source_urls)s, %(source_names)s, %(source_license)s,
    %(source_updated_at)s, %(search_text)s, true, %(content_hash)s, now()
)
ON CONFLICT (source, source_ref) DO UPDATE SET
    slug = EXCLUDED.slug, name = EXCLUDED.name, name_normalized = EXCLUDED.name_normalized,
    short_description = EXCLUDED.short_description, description = EXCLUDED.description,
    description_source = EXCLUDED.description_source, geom = EXCLUDED.geom,
    address = EXCLUDED.address, distance_from_center_km = EXCLUDED.distance_from_center_km,
    region_bucket = EXCLUDED.region_bucket, district = EXCLUDED.district,
    locality = EXCLUDED.locality, neighborhood = EXCLUDED.neighborhood,
    primary_category = EXCLUDED.primary_category, tags = EXCLUDED.tags,
    experience_tags = EXCLUDED.experience_tags, mood_tags = EXCLUDED.mood_tags,
    food_tags = EXCLUDED.food_tags, dietary_tags = EXCLUDED.dietary_tags,
    activity_tags = EXCLUDED.activity_tags, accessibility_tags = EXCLUDED.accessibility_tags,
    indoor_outdoor = EXCLUDED.indoor_outdoor, weather_suitability = EXCLUDED.weather_suitability,
    opening_hours_raw = EXCLUDED.opening_hours_raw,
    opening_hours_confidence = EXCLUDED.opening_hours_confidence,
    visit_duration_min = EXCLUDED.visit_duration_min,
    visit_duration_typical = EXCLUDED.visit_duration_typical,
    visit_duration_max = EXCLUDED.visit_duration_max,
    estimated_cost_min = EXCLUDED.estimated_cost_min,
    estimated_cost_typical = EXCLUDED.estimated_cost_typical,
    estimated_cost_max = EXCLUDED.estimated_cost_max, cost_confidence = EXCLUDED.cost_confidence,
    prominence = EXCLUDED.prominence, prominence_parts = EXCLUDED.prominence_parts,
    quality_score = EXCLUDED.quality_score, editorial_score = EXCLUDED.editorial_score,
    data_confidence = EXCLUDED.data_confidence, curated = EXCLUDED.curated,
    recommendable = EXCLUDED.recommendable, family_friendly = EXCLUDED.family_friendly,
    kids_friendly = EXCLUDED.kids_friendly, senior_friendly = EXCLUDED.senior_friendly,
    couple_friendly = EXCLUDED.couple_friendly, solo_friendly = EXCLUDED.solo_friendly,
    group_friendly = EXCLUDED.group_friendly,
    recommended_as_primary_destination = EXCLUDED.recommended_as_primary_destination,
    requires_large_time_block = EXCLUDED.requires_large_time_block,
    short_escape = EXCLUDED.short_escape, day_trip_suitable = EXCLUDED.day_trip_suitable,
    is_chain = EXCLUDED.is_chain, chain_key = EXCLUDED.chain_key,
    wikidata_id = EXCLUDED.wikidata_id, wikipedia_title = EXCLUDED.wikipedia_title,
    image_url = EXCLUDED.image_url, image_attribution = EXCLUDED.image_attribution,
    source_urls = EXCLUDED.source_urls, source_names = EXCLUDED.source_names,
    source_license = EXCLUDED.source_license, source_updated_at = EXCLUDED.source_updated_at,
    search_text = EXCLUDED.search_text, active = true, content_hash = EXCLUDED.content_hash,
    updated_at = now()
WHERE pois.content_hash IS DISTINCT FROM EXCLUDED.content_hash OR NOT pois.active
RETURNING id, (xmax = 0) AS inserted
"""


def _params(r: dict, category_ids: dict[str, int], source_updated_at: str | None) -> dict:
    s = r["suitability"]
    dmin, dtyp, dmax = r["visit_duration"]
    cmin, ctyp, cmax = r["cost"]
    return {
        "source": r["source"], "source_ref": r["source_ref"], "slug": r["slug"],
        "name": r["name"], "name_normalized": r["name_normalized"],
        "short_description": r.get("short_description"), "description": r.get("description"),
        "description_source": r.get("description_source"), "lat": r["lat"], "lon": r["lon"],
        "address": r.get("address"), "distance_from_center_km": r["distance_from_center_km"],
        "region_bucket": r["region_bucket"], "district": r.get("district"),
        "locality": (r.get("locality") or None) and r["locality"][:120],
        "neighborhood": (r.get("neighborhood") or None) and r["neighborhood"][:120],
        "category_id": category_ids[r["category"]],
        "tags": json.dumps(r["tags"], ensure_ascii=False, sort_keys=True),
        "experience_tags": r["experience_tags"], "mood_tags": r["mood_tags"],
        "food_tags": r["food_tags"], "dietary_tags": r["dietary_tags"],
        "activity_tags": r["activity_tags"], "accessibility_tags": r["accessibility_tags"],
        "indoor_outdoor": r["indoor_outdoor"], "weather_suitability": r["weather_suitability"],
        "opening_hours_raw": r.get("opening_hours_raw"),
        "opening_hours_confidence": r["opening_hours_confidence"],
        "dmin": dmin, "dtyp": dtyp, "dmax": dmax, "cmin": cmin, "ctyp": ctyp, "cmax": cmax,
        "cost_confidence": r["cost_confidence"], "prominence": r["prominence"],
        "prominence_parts": json.dumps(r["prominence_parts"], sort_keys=True),
        "quality_score": r["quality_score"], "editorial_score": r.get("editorial_score"),
        "data_confidence": r["data_confidence"], "curated": r["curated"],
        "recommendable": r["recommendable"], **{k: s.get(k) for k in (
            "family_friendly", "kids_friendly", "senior_friendly", "couple_friendly",
            "solo_friendly", "group_friendly")},
        "recommended_as_primary_destination": bool(r.get("recommended_as_primary_destination")),
        "requires_large_time_block": bool(r.get("requires_large_time_block")),
        "short_escape": bool(r.get("short_escape")),
        "day_trip_suitable": bool(r.get("day_trip_suitable")),
        "is_chain": r["is_chain"], "chain_key": r.get("chain_key"),
        "wikidata_id": r.get("wikidata_id"), "wikipedia_title": r.get("wikipedia_title"),
        "image_url": r.get("image_url"),
        "image_attribution": json.dumps(r["image_attribution"]) if r.get("image_attribution")
        else None,
        "source_urls": r["source_urls"], "source_names": r["source_names"],
        "source_license": r["source_license"], "source_updated_at": source_updated_at,
        "search_text": r["search_text"], "content_hash": r["content_hash"],
    }


def load_pois(dsn: str, records: list[dict], *, source_updated_at: str | None,
              deactivate_missing: bool = True) -> dict:
    stats = Counter()
    catalog = category_catalog()
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT key, id FROM poi_categories")
        category_ids = dict(cur.fetchall())
        missing = set(catalog) - set(category_ids)
        if missing:
            raise RuntimeError(f"poi_categories missing keys {sorted(missing)}: run migrations")
        for r in records:
            cur.execute(UPSERT_SQL, _params(r, category_ids, source_updated_at))
            row = cur.fetchone()
            if row is None:
                stats["unchanged"] += 1
                continue
            poi_id, inserted = row
            stats["inserted" if inserted else "updated"] += 1
            cur.execute("DELETE FROM poi_aliases WHERE poi_id = %s", (poi_id,))
            cur.execute("DELETE FROM poi_category_links WHERE poi_id = %s", (poi_id,))
            cur.execute("DELETE FROM poi_opening_hours WHERE poi_id = %s", (poi_id,))
            from app.ingestion.normalize import normalize_name
            seen_alias: set[str] = set()
            for alias in r["aliases"]:
                norm = normalize_name(alias)
                if not norm or norm == r["name_normalized"] or norm in seen_alias:
                    continue
                seen_alias.add(norm)
                cur.execute("INSERT INTO poi_aliases (poi_id, alias, alias_normalized, source) "
                            "VALUES (%s, %s, %s, %s)", (poi_id, alias, norm,
                                                         "curated" if r["curated"] else "source"))
            cur.execute("INSERT INTO poi_category_links (poi_id, category_id, weight) "
                        "VALUES (%s, %s, 1.0)", (poi_id, category_ids[r["category"]]))
            for sec, weight in r["secondary"]:
                if sec == r["category"]:
                    continue
                cur.execute("INSERT INTO poi_category_links (poi_id, category_id, weight) "
                            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            (poi_id, category_ids[sec], weight))
            source = r["hours_source"]
            for iv in r["hours"]:
                cur.execute(
                    "INSERT INTO poi_opening_hours (poi_id, day_of_week, open_min, close_min, "
                    "is_24h, closed_all_day, source, confidence) "
                    "VALUES (%s, %s, %s, %s, %s, false, %s, %s) ON CONFLICT DO NOTHING",
                    (poi_id, iv["day"], iv["open_min"], iv["close_min"], iv["is_24h"], source,
                     r["opening_hours_confidence"]))
        if deactivate_missing:
            keys = [f"{r['source']}:{r['source_ref']}" for r in records]
            cur.execute("""
                UPDATE pois SET active = false, recommendable = false, updated_at = now()
                WHERE source IN ('osm', 'wikidata') AND active
                  AND NOT ((source || ':' || source_ref) = ANY(%s))
            """, (keys,))
            stats["deactivated"] = cur.rowcount
        conn.commit()
    return dict(stats)


def load_places(dsn: str, places: list, cfg, districts) -> dict:
    from app.geo.regions import distance_from_center_km, region_bucket
    stats = Counter()
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for p in places:
            d = distance_from_center_km(p.lat, p.lon, cfg)
            cur.execute("""
                INSERT INTO places (source_ref, name, name_normalized, aliases, place_type, geom,
                                    distance_from_center_km, region_bucket, district, importance)
                VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        %s, %s, %s, %s)
                ON CONFLICT (source_ref) DO UPDATE SET
                    name = EXCLUDED.name, name_normalized = EXCLUDED.name_normalized,
                    aliases = EXCLUDED.aliases, place_type = EXCLUDED.place_type,
                    geom = EXCLUDED.geom,
                    distance_from_center_km = EXCLUDED.distance_from_center_km,
                    region_bucket = EXCLUDED.region_bucket, district = EXCLUDED.district,
                    importance = EXCLUDED.importance
                WHERE (places.name, places.aliases, places.place_type, places.district,
                       places.importance)
                      IS DISTINCT FROM
                      (EXCLUDED.name, EXCLUDED.aliases, EXCLUDED.place_type, EXCLUDED.district,
                       EXCLUDED.importance)
                RETURNING (xmax = 0)
            """, (p.source_ref, p.name, p.name_normalized, p.aliases, p.place_type, p.lon, p.lat,
                  round(d, 3), region_bucket(d, cfg).value,
                  districts.lookup(p.lat, p.lon) if districts else None, p.importance))
            row = cur.fetchone()
            stats["unchanged" if row is None else ("inserted" if row[0] else "updated")] += 1
        conn.commit()
    return dict(stats)
