"""Primary-source facts for the validator, re-queried from the database.

Deliberately a separate query path from the planner's candidate retrieval:
the validator must not see the optimizer's copy of a POI (its costs, its
hours window, its duration), only what the database says now.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.geo.regions import geo_config
from app.schemas.tripspec import TripSpec
from app.services.planning.validator.itinerary import TripRules
from app.services.poi.repository import POIRecord, attach_hours, fetch_by_ids


async def load_facts(db: AsyncSession, poi_ids: list[int], on: date) -> dict[int, POIRecord]:
    facts = await fetch_by_ids(db, poi_ids)
    await attach_hours(db, facts.values(), on.weekday())
    return facts


def rules_for(spec: TripSpec, *, max_hop_km: float) -> TripRules:
    cfg = geo_config()
    avoid_cats = {i for i in spec.avoid_interests if _is_category(i)}
    return TripRules(
        start_min=spec.start_minute, end_min=spec.end_minute,
        transition_buffer_min=spec.transition_buffer_minutes,
        party_size=spec.effective_party_size, budget_total=spec.effective_budget_total,
        envelope_radius_km=settings.BENGALURU_DISCOVERY_RADIUS_KM,
        center_lat=cfg.center_lat, center_lon=cfg.center_lon,
        exploration_radius_km=spec.exploration_radius_km, max_hop_km=max_hop_km,
        must_include_ids=set(spec.must_include_poi_ids),
        exclude_ids=set(spec.exclude_poi_ids),
        avoid_categories=avoid_cats,
        avoid_tags={i for i in spec.avoid_interests if i not in avoid_cats},
        dietary=list(spec.dietary_preferences),
        accessibility=list(spec.accessibility_requirements),
        indoor_preference=spec.indoor_preference,
        kids="kids_friendly" in spec.family_requirements
        or (spec.party_type is not None and spec.party_type.value == "family_with_kids"),
    )


def _is_category(value: str) -> bool:
    from app.domain.taxonomy import is_valid_category
    return is_valid_category(value)
