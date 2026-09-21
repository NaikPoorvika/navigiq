"""POI data access: one typed record shape for recommendation, planning and
validation, and the parameterised candidate query every consumer shares.

SQL here is fixed text with bound parameters. No caller (and no tool, and no
model) can pass SQL fragments - filters are typed arguments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class HoursInterval:
    open_min: int
    close_min: int
    is_24h: bool
    confidence: float


@dataclass
class POIRecord:
    id: int
    slug: str
    name: str
    category: str
    secondary: list[str]
    lat: float
    lon: float
    distance_from_center_km: float
    region_bucket: str
    district: str | None
    locality: str | None
    neighborhood: str | None
    experience_tags: list[str]
    mood_tags: list[str]
    food_tags: list[str]
    dietary_tags: list[str]
    accessibility_tags: list[str]
    indoor_outdoor: str
    weather_suitability: str
    visit: tuple[int, int, int]
    cost: tuple[int, int, int]
    cost_confidence: str
    hours_confidence: float
    prominence: float
    quality: float
    editorial: float | None
    curated: bool
    recommendable: bool
    suitability: dict[str, bool | None]
    primary_destination: bool
    large_time_block: bool
    short_escape: bool
    day_trip: bool
    is_chain: bool
    chain_key: str | None
    short_description: str | None
    image_url: str | None
    image_attribution: dict | None
    source_names: list[str]
    source_urls: list[str]
    source_license: str
    anchor_km: float | None = None
    hours: list[HoursInterval] = field(default_factory=list)   # for the requested day
    hours_loaded_for_day: int | None = None

    @property
    def all_categories(self) -> set[str]:
        return {self.category, *self.secondary}

    @property
    def tags(self) -> set[str]:
        return set(self.experience_tags)

    @property
    def hours_reliable(self) -> bool:
        return self.hours_confidence >= 0.5

    def open_interval_containing(self, start: int, end: int) -> HoursInterval | None:
        for h in self.hours:
            if h.is_24h or (h.open_min <= start and end <= h.close_min):
                return h
        return None

    def closed_all_day(self) -> bool:
        """True only when reliable hours were loaded for the day and none exist."""
        return self.hours_reliable and self.hours_loaded_for_day is not None and not self.hours

    def card(self) -> dict:
        """The public, verified subset used by POI cards and tool results."""
        return {
            "id": self.id, "slug": self.slug, "name": self.name, "category": self.category,
            "secondary_categories": self.secondary, "lat": self.lat, "lon": self.lon,
            "locality": self.locality, "neighborhood": self.neighborhood,
            "district": self.district, "region_bucket": self.region_bucket,
            "distance_from_center_km": round(self.distance_from_center_km, 1),
            "short_description": self.short_description,
            "experience_tags": self.experience_tags, "mood_tags": self.mood_tags,
            "indoor_outdoor": self.indoor_outdoor,
            "visit_duration": {"min": self.visit[0], "typical": self.visit[1],
                               "max": self.visit[2]},
            "estimated_cost": {"min": self.cost[0], "typical": self.cost[1],
                               "max": self.cost[2], "confidence": self.cost_confidence,
                               "currency": "INR", "per": "person", "basis": "estimate"},
            "hours_confidence": self.hours_confidence,
            "image_url": self.image_url, "image_attribution": self.image_attribution,
            "is_chain": self.is_chain, "curated": self.curated,
            "short_escape": self.short_escape, "day_trip_suitable": self.day_trip,
            "recommended_as_primary_destination": self.primary_destination,
            "source_names": self.source_names,
        }


_COLUMNS = """
    p.id, p.slug, p.name, c.key AS category,
    ST_Y(p.geom::geometry) AS lat, ST_X(p.geom::geometry) AS lon,
    p.distance_from_center_km, p.region_bucket, p.district, p.locality, p.neighborhood,
    p.experience_tags, p.mood_tags, p.food_tags, p.dietary_tags, p.accessibility_tags,
    p.indoor_outdoor, p.weather_suitability,
    p.visit_duration_min, p.visit_duration_typical, p.visit_duration_max,
    p.estimated_cost_min, p.estimated_cost_typical, p.estimated_cost_max, p.cost_confidence,
    p.opening_hours_confidence, p.prominence, p.quality_score, p.editorial_score, p.curated,
    p.recommendable, p.family_friendly, p.kids_friendly, p.senior_friendly, p.couple_friendly,
    p.solo_friendly, p.group_friendly, p.recommended_as_primary_destination,
    p.requires_large_time_block, p.short_escape, p.day_trip_suitable, p.is_chain, p.chain_key,
    p.short_description, p.image_url, p.image_attribution, p.source_names, p.source_urls,
    p.source_license,
    COALESCE((SELECT array_agg(lc.key ORDER BY l.weight DESC, lc.key)
              FROM poi_category_links l JOIN poi_categories lc ON lc.id = l.category_id
              WHERE l.poi_id = p.id AND l.category_id <> p.primary_category), '{}') AS secondary
"""


def _row_to_record(r) -> POIRecord:
    return POIRecord(
        id=r.id, slug=r.slug, name=r.name, category=r.category, secondary=list(r.secondary or []),
        lat=float(r.lat), lon=float(r.lon),
        distance_from_center_km=float(r.distance_from_center_km),
        region_bucket=r.region_bucket, district=r.district, locality=r.locality,
        neighborhood=r.neighborhood, experience_tags=list(r.experience_tags or []),
        mood_tags=list(r.mood_tags or []), food_tags=list(r.food_tags or []),
        dietary_tags=list(r.dietary_tags or []),
        accessibility_tags=list(r.accessibility_tags or []),
        indoor_outdoor=r.indoor_outdoor, weather_suitability=r.weather_suitability,
        visit=(r.visit_duration_min, r.visit_duration_typical, r.visit_duration_max),
        cost=(r.estimated_cost_min, r.estimated_cost_typical, r.estimated_cost_max),
        cost_confidence=r.cost_confidence, hours_confidence=float(r.opening_hours_confidence),
        prominence=float(r.prominence), quality=float(r.quality_score),
        editorial=float(r.editorial_score) if r.editorial_score is not None else None,
        curated=r.curated, recommendable=r.recommendable,
        suitability={k: getattr(r, k) for k in (
            "family_friendly", "kids_friendly", "senior_friendly", "couple_friendly",
            "solo_friendly", "group_friendly")},
        primary_destination=r.recommended_as_primary_destination,
        large_time_block=r.requires_large_time_block, short_escape=r.short_escape,
        day_trip=r.day_trip_suitable, is_chain=r.is_chain, chain_key=r.chain_key,
        short_description=r.short_description, image_url=r.image_url,
        image_attribution=r.image_attribution, source_names=list(r.source_names or []),
        source_urls=list(r.source_urls or []), source_license=r.source_license,
        anchor_km=float(r.anchor_km) if getattr(r, "anchor_km", None) is not None else None,
    )


@dataclass
class CandidateQuery:
    """Typed filters for the shared candidate query. Every field optional."""
    recommendable_only: bool = True
    buckets: list[str] | None = None
    anchor_lat: float | None = None
    anchor_lon: float | None = None
    radius_km: float | None = None
    max_center_km: float | None = None
    any_categories: list[str] | None = None      # relevance prefilter (OR-ed)
    any_tags: list[str] | None = None
    any_moods: list[str] | None = None
    avoid_categories: list[str] | None = None
    avoid_tags: list[str] | None = None
    exclude_ids: list[int] | None = None
    max_cost_typical: int | None = None
    min_quality: float | None = None
    limit: int = 600


_CANDIDATE_SQL = text(f"""
SELECT {_COLUMNS},
    CASE WHEN CAST(:alat AS float8) IS NULL THEN NULL
         ELSE ST_Distance(p.geom, ST_SetSRID(ST_MakePoint(:alon, :alat), 4326)::geography) / 1000.0
    END AS anchor_km
FROM pois p JOIN poi_categories c ON c.id = p.primary_category
WHERE p.active
  AND (NOT CAST(:rec_only AS boolean) OR p.recommendable)
  AND (CAST(:buckets AS text[]) IS NULL OR p.region_bucket = ANY(CAST(:buckets AS text[])))
  AND (CAST(:alat AS float8) IS NULL OR ST_DWithin(
        p.geom, ST_SetSRID(ST_MakePoint(:alon, :alat), 4326)::geography, :radius_m))
  AND (CAST(:max_center AS float8) IS NULL OR p.distance_from_center_km <= :max_center)
  AND (CAST(:exclude_ids AS int[]) IS NULL OR NOT (p.id = ANY(CAST(:exclude_ids AS int[]))))
  AND (CAST(:avoid_cats AS text[]) IS NULL OR NOT (c.key = ANY(CAST(:avoid_cats AS text[]))))
  AND (CAST(:avoid_tags AS text[]) IS NULL OR NOT (p.experience_tags && CAST(:avoid_tags AS text[])))
  AND (CAST(:max_cost AS int) IS NULL OR p.estimated_cost_typical <= :max_cost)
  AND (CAST(:min_quality AS float8) IS NULL OR p.quality_score >= :min_quality)
  AND (
        (CAST(:any_cats AS text[]) IS NULL AND CAST(:any_tags AS text[]) IS NULL
         AND CAST(:any_moods AS text[]) IS NULL)
     OR c.key = ANY(COALESCE(CAST(:any_cats AS text[]), '{{}}'))
     OR EXISTS (SELECT 1 FROM poi_category_links l JOIN poi_categories lc
                ON lc.id = l.category_id WHERE l.poi_id = p.id
                AND lc.key = ANY(COALESCE(CAST(:any_cats AS text[]), '{{}}')))
     OR p.experience_tags && COALESCE(CAST(:any_tags AS text[]), '{{}}')
     OR p.mood_tags && COALESCE(CAST(:any_moods AS text[]), '{{}}')
  )
ORDER BY p.quality_score DESC, p.id
LIMIT :limit
""")


async def fetch_candidates(db: AsyncSession, q: CandidateQuery) -> list[POIRecord]:
    params = {
        "rec_only": q.recommendable_only,
        "buckets": q.buckets or None,
        "alat": q.anchor_lat, "alon": q.anchor_lon,
        "radius_m": (q.radius_km or 5.0) * 1000.0,
        "max_center": q.max_center_km,
        "exclude_ids": q.exclude_ids or None,
        "avoid_cats": q.avoid_categories or None,
        "avoid_tags": q.avoid_tags or None,
        "max_cost": q.max_cost_typical,
        "min_quality": q.min_quality,
        "any_cats": q.any_categories or None,
        "any_tags": q.any_tags or None,
        "any_moods": q.any_moods or None,
        "limit": max(1, min(q.limit, 2000)),
    }
    rows = (await db.execute(_CANDIDATE_SQL, params)).all()
    return [_row_to_record(r) for r in rows]


_BY_IDS_SQL = text(f"""
SELECT {_COLUMNS}, NULL::float8 AS anchor_km
FROM pois p JOIN poi_categories c ON c.id = p.primary_category
WHERE p.id = ANY(CAST(:ids AS int[]))
""")


async def fetch_by_ids(db: AsyncSession, ids: Iterable[int], *,
                       include_inactive: bool = False) -> dict[int, POIRecord]:
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}
    rows = (await db.execute(_BY_IDS_SQL, {"ids": ids})).all()
    out = {}
    for r in rows:
        rec = _row_to_record(r)
        out[rec.id] = rec
    if not include_inactive:
        active = set((await db.execute(
            text("SELECT id FROM pois WHERE active AND id = ANY(CAST(:ids AS int[]))"),
            {"ids": ids})).scalars().all())
        out = {k: v for k, v in out.items() if k in active}
    return out


async def attach_hours(db: AsyncSession, records: Iterable[POIRecord], day_of_week: int) -> None:
    recs = {r.id: r for r in records}
    if not recs:
        return
    rows = (await db.execute(text("""
        SELECT poi_id, open_min, close_min, is_24h, confidence FROM poi_opening_hours
        WHERE poi_id = ANY(CAST(:ids AS int[])) AND day_of_week = :dow AND NOT closed_all_day
        ORDER BY poi_id, open_min
    """), {"ids": list(recs), "dow": day_of_week})).all()
    for r in recs.values():
        r.hours = []
        r.hours_loaded_for_day = day_of_week
    for row in rows:
        recs[row.poi_id].hours.append(HoursInterval(row.open_min, row.close_min, row.is_24h,
                                                    float(row.confidence)))
