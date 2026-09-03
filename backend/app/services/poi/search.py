"""NQ-016 - POI search with hard constraint filtering.

Hard filters (a POI failing any of these is excluded, never down-ranked):
  spatial radius, category, opening hours, budget ceiling, user exclusions.

The opening-hours filter respects the NQ-014 confidence rule: rows below
0.5 confidence are category defaults, not real data. Filtering hard on them
would remove 13,563 of 14,851 POIs. Low-confidence POIs are therefore
INCLUDED when open_at is given, and flagged so the caller can penalise
rather than delete them.

ST_DWithin is used rather than ST_Distance in WHERE - only the former can
use the GIST index.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

HOURS_CONFIDENCE_THRESHOLD = 0.5
MAX_RADIUS_KM = 25.0
MAX_LIMIT = 50


@dataclass(frozen=True)
class POISummary:
    id: int
    name: str
    category: str
    lat: float
    lon: float
    distance_m: int
    prominence: float
    cost_estimate_inr: int | None
    category_typical_inr: int
    visit_minutes: int
    indoor: bool | None
    open_at_requested: bool | None
    hours_confidence: float | None
    curated: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "lat": self.lat,
            "lon": self.lon,
            "distance_m": self.distance_m,
            "prominence": float(self.prominence),
            "cost_estimate_inr": self.cost_estimate_inr,
            "category_typical_inr": self.category_typical_inr,
            "visit_minutes": self.visit_minutes,
            "indoor": self.indoor,
            "open_at_requested": self.open_at_requested,
            "hours_confidence": (
                float(self.hours_confidence)
                if self.hours_confidence is not None else None
            ),
            "hours_verified": (
                self.hours_confidence is not None
                and float(self.hours_confidence) >= HOURS_CONFIDENCE_THRESHOLD
            ),
            "curated": self.curated,
        }


_SEARCH_SQL = text("""
WITH origin AS (
    SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g
),
hours AS (
    SELECT DISTINCT ON (poi_id)
           poi_id, open_min, close_min, is_24h, confidence
    FROM poi_opening_hours
    WHERE (:dow)::int IS NULL OR day_of_week = (:dow)::int
    ORDER BY poi_id, confidence DESC
)
SELECT
    p.id,
    p.name,
    c.key                       AS category,
    ST_Y(p.geom::geometry)      AS lat,
    ST_X(p.geom::geometry)      AS lon,
    ST_Distance(p.geom, origin.g) AS distance_m,
    p.prominence,
    p.cost_estimate_inr,
    c.typical_cost_inr,
    COALESCE(p.visit_minutes, c.default_visit_minutes) AS visit_minutes,
    COALESCE(p.indoor, c.is_indoor) AS indoor,
    h.confidence                AS hours_confidence,
    CASE
        WHEN (:minute)::int IS NULL OR h.poi_id IS NULL THEN NULL
        WHEN h.is_24h THEN true
        ELSE (:minute)::int >= h.open_min AND (:minute)::int < h.close_min
    END AS open_at_requested,
    p.curated
FROM pois p
CROSS JOIN origin
JOIN poi_categories c ON c.id = p.primary_category
LEFT JOIN hours h ON h.poi_id = p.id
WHERE p.active
  AND ST_DWithin(p.geom, origin.g, :radius_m)
  AND (CAST(:categories AS text[]) IS NULL OR c.key = ANY(CAST(:categories AS text[])))
  AND (CAST(:exclude_ids AS bigint[]) IS NULL OR NOT (p.id = ANY(CAST(:exclude_ids AS bigint[]))))
  AND (
        CAST(:max_cost AS int) IS NULL
        OR COALESCE(p.cost_estimate_inr, c.typical_cost_inr) <= :max_cost
      )
  AND (
        (:minute)::int IS NULL
        OR h.poi_id IS NULL
        OR h.confidence < :hours_threshold
        OR h.is_24h
        OR ((:minute)::int >= h.open_min AND (:minute)::int < h.close_min)
      )
ORDER BY p.prominence DESC, distance_m ASC
LIMIT :limit
""")


async def search_pois(
    db: AsyncSession,
    *,
    lat: float,
    lon: float,
    radius_km: float = 3.0,
    categories: list[str] | None = None,
    open_at: datetime | None = None,
    max_cost_inr: int | None = None,
    exclude_ids: list[int] | None = None,
    limit: int = 20,
) -> list[POISummary]:
    """Search POIs under hard constraints, ordered by prominence then distance."""
    radius_km = min(max(radius_km, 0.1), MAX_RADIUS_KM)
    limit = min(max(limit, 1), MAX_LIMIT)

    dow = minute = None
    if open_at is not None:
        dow = open_at.weekday()
        minute = open_at.hour * 60 + open_at.minute

    result = await db.execute(
        _SEARCH_SQL,
        {
            "lat": lat,
            "lon": lon,
            "radius_m": radius_km * 1000,
            "categories": categories or None,
            "exclude_ids": exclude_ids or None,
            "max_cost": max_cost_inr,
            "dow": dow,
            "minute": minute,
            "hours_threshold": HOURS_CONFIDENCE_THRESHOLD,
            "limit": limit,
        },
    )

    return [
        POISummary(
            id=r.id, name=r.name, category=r.category,
            lat=float(r.lat), lon=float(r.lon),
            distance_m=int(round(r.distance_m)),
            prominence=float(r.prominence),
            cost_estimate_inr=r.cost_estimate_inr,
            category_typical_inr=r.typical_cost_inr,
            visit_minutes=r.visit_minutes, indoor=r.indoor,
            open_at_requested=r.open_at_requested,
            hours_confidence=r.hours_confidence, curated=r.curated,
        )
        for r in result
    ]


async def get_poi_detail(db: AsyncSession, poi_id: int) -> dict | None:
    """Full POI record including the week's opening hours."""
    row = (await db.execute(text("""
        SELECT p.id, p.name, p.description, c.key AS category,
               ST_Y(p.geom::geometry) AS lat, ST_X(p.geom::geometry) AS lon,
               p.area, p.prominence, p.prominence_parts,
               p.cost_estimate_inr, c.typical_cost_inr,
               COALESCE(p.visit_minutes, c.default_visit_minutes) AS visit_minutes,
               COALESCE(p.indoor, c.is_indoor) AS indoor,
               p.tags, p.wikidata_id, p.curated, p.source_ref
        FROM pois p JOIN poi_categories c ON c.id = p.primary_category
        WHERE p.id = :id AND p.active
    """), {"id": poi_id})).first()

    if row is None:
        return None

    hours = (await db.execute(text("""
        SELECT day_of_week, open_min, close_min, is_24h, source, confidence
        FROM poi_opening_hours WHERE poi_id = :id
        ORDER BY day_of_week, open_min
    """), {"id": poi_id})).all()

    secondary = (await db.execute(text("""
        SELECT c.key, l.weight
        FROM poi_category_links l JOIN poi_categories c ON c.id = l.category_id
        WHERE l.poi_id = :id ORDER BY l.weight DESC
    """), {"id": poi_id})).all()

    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "secondary_categories": [
            {"category": s.key, "weight": float(s.weight)} for s in secondary
        ],
        "lat": float(row.lat), "lon": float(row.lon), "area": row.area,
        "prominence": float(row.prominence),
        "prominence_parts": row.prominence_parts,
        "cost_estimate_inr": row.cost_estimate_inr,
        "category_typical_inr": row.typical_cost_inr,
        "cost_basis": "poi_specific" if row.cost_estimate_inr is not None
                      else "category_median",
        "visit_minutes": row.visit_minutes,
        "indoor": row.indoor,
        "curated": row.curated,
        "source": "openstreetmap",
        "source_ref": row.source_ref,
        "wikidata_id": row.wikidata_id,
        "opening_hours": [
            {
                "day_of_week": h.day_of_week, "open_min": h.open_min,
                "close_min": h.close_min, "is_24h": h.is_24h,
                "source": h.source, "confidence": float(h.confidence),
                "verified": float(h.confidence) >= HOURS_CONFIDENCE_THRESHOLD,
            }
            for h in hours
        ],
    }





