"""POI search, name resolution and area resolution (sections 57, 86).

Names are compared after the same normalisation the pipeline applied at
ingestion (Bangalore/Bengaluru, Malleswaram/Malleshwaram, MG Road/M.G. Road
fold together), then by pg_trgm similarity for misspellings and partial
names, over canonical names AND aliases.

Area resolution returns coordinates ONLY from stored OSM data (the places
gazetteer or a POI). An unknown area resolves to nothing - never to a guess.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.regions import geo_config
from app.ingestion.normalize import normalize_name
from app.services.poi.repository import POIRecord, fetch_by_ids

MIN_NAME_SIMILARITY = 0.32
PLACE_RADIUS_KM = {"neighbourhood": 2.5, "quarter": 2.5, "suburb": 3.0, "locality": 2.5,
                   "hamlet": 3.0, "village": 4.0, "town": 5.0, "city": 8.0, "poi": 2.0}
CITY_NAMES = {"bengaluru", "bengaluru city", "bengaluru urban", "namma bengaluru", "blr",
              "the city", "city"}


@dataclass
class NameMatch:
    poi_id: int
    name: str
    matched_text: str
    similarity: float
    exact: bool
    score: float


@dataclass
class ResolvedArea:
    name: str
    lat: float
    lon: float
    radius_km: float
    source_ref: str
    kind: str                 # place type or "poi"
    confidence: float

    def to_dict(self) -> dict:
        return {"name": self.name, "lat": self.lat, "lon": self.lon,
                "radius_km": self.radius_km, "source_ref": self.source_ref,
                "kind": self.kind, "confidence": round(self.confidence, 3)}


_NAME_SQL = text("""
WITH q AS (SELECT CAST(:q AS text) AS q)
SELECT p.id, p.name, m.matched, m.sim, m.exact, p.quality_score, p.prominence
FROM (
    SELECT p.id, p.name_normalized AS matched,
           GREATEST(similarity(p.name_normalized, q.q), word_similarity(q.q, p.name_normalized)) AS sim,
           p.name_normalized = q.q AS exact
    FROM pois p, q
    WHERE p.active AND (p.name_normalized % q.q OR q.q <% p.name_normalized
                        OR p.name_normalized = q.q)
    UNION ALL
    SELECT a.poi_id, a.alias_normalized,
           GREATEST(similarity(a.alias_normalized, q.q), word_similarity(q.q, a.alias_normalized)),
           a.alias_normalized = q.q
    FROM poi_aliases a, q
    WHERE a.alias_normalized % q.q OR q.q <% a.alias_normalized OR a.alias_normalized = q.q
) m JOIN pois p ON p.id = m.id AND p.active
ORDER BY m.exact DESC, m.sim DESC, p.quality_score DESC, p.id
LIMIT 60
""")


async def resolve_poi_name(db: AsyncSession, name: str, *, limit: int = 5) -> list[NameMatch]:
    q = normalize_name(name)
    if len(q) < 2:
        return []
    await db.execute(text("SELECT set_limit(0.25)"))
    rows = (await db.execute(_NAME_SQL, {"q": q})).all()
    best: dict[int, NameMatch] = {}
    for r in rows:
        sim = float(r.sim)
        if sim < MIN_NAME_SIMILARITY and not r.exact:
            continue
        score = (2.0 if r.exact else 0.0) + 0.7 * sim + 0.2 * float(r.quality_score) + \
            0.1 * float(r.prominence)
        m = NameMatch(r.id, r.name, r.matched, sim, bool(r.exact), score)
        if r.id not in best or best[r.id].score < score:
            best[r.id] = m
    return sorted(best.values(), key=lambda m: (-m.score, m.poi_id))[:limit]


def unambiguous(matches: list[NameMatch]) -> NameMatch | None:
    """The single intended POI, or None when the user must choose."""
    if not matches:
        return None
    top = matches[0]
    if top.exact and (len(matches) == 1 or not matches[1].exact):
        return top
    if top.similarity < 0.5:
        return None
    if len(matches) == 1:
        return top
    second = matches[1]
    # A clearly better textual match, or an equally good match that is a far
    # better-documented place (the garden, not the restaurant named after it).
    if top.similarity - second.similarity >= 0.1 or top.score - second.score >= 0.12:
        return top
    return None


_PLACE_SQL = text("""
SELECT id, source_ref, name, place_type, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon,
       importance, GREATEST(similarity(name_normalized, :q), word_similarity(:q, name_normalized)) AS sim,
       name_normalized = :q AS exact
FROM places
WHERE name_normalized % :q OR name_normalized = :q OR :q <% name_normalized
   OR :q = ANY(SELECT lower(a) FROM unnest(aliases) a)
ORDER BY (name_normalized = :q) DESC, sim DESC, importance DESC, id
LIMIT 10
""")


async def resolve_location(db: AsyncSession, name: str) -> ResolvedArea | None:
    q = normalize_name(name)
    if len(q) < 3 or q in CITY_NAMES:
        return None
    await db.execute(text("SELECT set_limit(0.3)"))
    places = (await db.execute(_PLACE_SQL, {"q": q})).all()
    cands: list[ResolvedArea] = []
    for p in places:
        sim = 1.0 if p.exact else float(p.sim)
        if sim < 0.5:
            continue
        # Among equal names prefer the more important place (a suburb over a
        # hamlet that happens to share its name).
        conf = sim * (0.7 + 0.3 * float(p.importance))
        cands.append(ResolvedArea(p.name, float(p.lat), float(p.lon),
                                  PLACE_RADIUS_KM.get(p.place_type, 3.0), p.source_ref,
                                  p.place_type, conf))
    # A named street or landmark ("MG Road", "Church Street", "Lalbagh").
    matches = await resolve_poi_name(db, name, limit=3)
    top = unambiguous(matches)
    if top is not None:
        rec = (await fetch_by_ids(db, [top.poi_id])).get(top.poi_id)
        if rec is not None:
            conf = (1.0 if top.exact else top.similarity) * 0.95
            cands.append(ResolvedArea(rec.name, rec.lat, rec.lon, PLACE_RADIUS_KM["poi"],
                                      f"poi/{rec.id}", "poi", conf))
    if not cands:
        return None
    return sorted(cands, key=lambda c: (-c.confidence, c.source_ref))[0]


_FILTER_SQL = text("""
SELECT p.id FROM pois p JOIN poi_categories c ON c.id = p.primary_category
WHERE p.active
  AND (CAST(:cats AS text[]) IS NULL OR c.key = ANY(CAST(:cats AS text[]))
       OR EXISTS (SELECT 1 FROM poi_category_links l JOIN poi_categories lc ON lc.id = l.category_id
                  WHERE l.poi_id = p.id AND lc.key = ANY(CAST(:cats AS text[]))))
  AND (CAST(:tags AS text[]) IS NULL OR p.experience_tags && CAST(:tags AS text[]))
  AND (CAST(:buckets AS text[]) IS NULL OR p.region_bucket = ANY(CAST(:buckets AS text[])))
  AND (CAST(:max_cost AS int) IS NULL OR p.estimated_cost_typical <= :max_cost)
  AND (CAST(:lat AS float8) IS NULL OR ST_DWithin(p.geom,
       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius_m))
  AND (CAST(:q AS text) IS NULL OR p.search_tsv @@ plainto_tsquery('simple', :q)
       OR p.name_normalized % :q)
ORDER BY
  CASE WHEN CAST(:lat AS float8) IS NULL THEN 0
       ELSE ST_Distance(p.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) / 5000.0
  END - p.quality_score,
  p.id
LIMIT :limit
""")


async def filtered_search(db: AsyncSession, *, query: str | None = None,
                          categories: list[str] | None = None, tags: list[str] | None = None,
                          buckets: list[str] | None = None, max_cost_pp: int | None = None,
                          near: tuple[float, float] | None = None, radius_km: float = 3.0,
                          limit: int = 20) -> list[POIRecord]:
    """Structured search used by the Explore filters and the search tool.
    Works with no LLM and no embeddings."""
    q = normalize_name(query) if query else None
    await db.execute(text("SELECT set_limit(0.3)"))
    ids = (await db.execute(_FILTER_SQL, {
        "cats": categories or None, "tags": tags or None, "buckets": buckets or None,
        "max_cost": max_cost_pp, "lat": near[0] if near else None,
        "lon": near[1] if near else None, "radius_m": min(radius_km, 90.0) * 1000.0,
        "q": q or None, "limit": max(1, min(limit, 100)),
    })).scalars().all()
    recs = await fetch_by_ids(db, ids)
    return [recs[i] for i in ids if i in recs]


async def get_poi_detail(db: AsyncSession, poi_id: int) -> dict | None:
    recs = await fetch_by_ids(db, [poi_id])
    rec = recs.get(poi_id)
    if rec is None:
        return None
    row = (await db.execute(text("""
        SELECT description, description_source, address, wikidata_id, wikipedia_title,
               opening_hours_raw, activity_tags, prominence_parts, source_updated_at, data_confidence
        FROM pois WHERE id = :id
    """), {"id": poi_id})).first()
    hours = (await db.execute(text("""
        SELECT day_of_week, open_min, close_min, is_24h, source, confidence
        FROM poi_opening_hours WHERE poi_id = :id ORDER BY day_of_week, open_min
    """), {"id": poi_id})).all()
    aliases = (await db.execute(text(
        "SELECT alias FROM poi_aliases WHERE poi_id = :id ORDER BY alias"), {"id": poi_id})
    ).scalars().all()
    detail = rec.card()
    detail.update({
        "description": row.description, "description_source": row.description_source,
        "address": row.address, "aliases": list(aliases), "wikidata_id": row.wikidata_id,
        "wikipedia_title": row.wikipedia_title, "opening_hours_raw": row.opening_hours_raw,
        "activity_tags": list(row.activity_tags or []),
        "food_tags": rec.food_tags, "dietary_tags": rec.dietary_tags,
        "accessibility_tags": rec.accessibility_tags,
        "weather_suitability": rec.weather_suitability,
        "suitability": rec.suitability, "data_confidence": float(row.data_confidence),
        "prominence": rec.prominence, "quality_score": rec.quality,
        "source_urls": rec.source_urls, "source_license": rec.source_license,
        "source_updated_at": row.source_updated_at.isoformat() if row.source_updated_at else None,
        "requires_large_time_block": rec.large_time_block,
        "opening_hours": [{
            "day_of_week": h.day_of_week, "open": f"{h.open_min // 60:02d}:{h.open_min % 60:02d}",
            "close": f"{h.close_min // 60:02d}:{h.close_min % 60:02d}"
            if h.close_min < 1440 else "24:00",
            "is_24h": h.is_24h, "source": h.source, "confidence": float(h.confidence),
            "verified": float(h.confidence) >= 0.5,
        } for h in hours],
        "hours_verified": rec.hours_reliable,
        "attribution": _attribution(rec, row.description_source),
    })
    return detail


def _attribution(rec: POIRecord, description_source: str | None) -> list[dict]:
    out = [{"name": "OpenStreetMap contributors", "license": "ODbL",
            "url": next((u for u in rec.source_urls if "openstreetmap" in u),
                        "https://www.openstreetmap.org/copyright")}]
    if description_source == "wikipedia":
        out.append({"name": "Wikipedia", "license": "CC BY-SA 4.0",
                    "url": next((u for u in rec.source_urls if "wikipedia" in u), None)})
    if rec.image_attribution:
        out.append({"name": f"Image: {rec.image_attribution.get('artist')}",
                    "license": rec.image_attribution.get("license"),
                    "url": rec.image_attribution.get("source_url")})
    return out


def city_center_area() -> ResolvedArea:
    cfg = geo_config()
    return ResolvedArea("Bengaluru", cfg.center_lat, cfg.center_lon, 8.0, "config/center",
                        "city", 1.0)
