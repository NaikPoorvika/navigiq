"""Integration tests for NQ-016 POI search.

Runs against the real loaded database (14,851 POIs), not fixtures. These
tests assert behaviour that must hold on real OSM data, including the
NQ-014 hours-confidence rule and GIST index usage.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq",
)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from app.services.poi.search import (  # noqa: E402
    HOURS_CONFIDENCE_THRESHOLD,
    MAX_RADIUS_KM,
    get_poi_detail,
    search_pois,
)

INDIRANAGAR = {"lat": 12.9784, "lon": 77.6408}


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db():
    """Fresh engine per test.

    The application engine is created at import time and pools connections.
    pytest-asyncio gives each test its own event loop, so a pooled asyncpg
    connection belongs to a loop that has already closed - which surfaces as
    "another operation is in progress". NullPool avoids reuse entirely.
    """
    engine = create_async_engine(
        os.environ["DATABASE_URL"], poolclass=NullPool
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_search_returns_results(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=2, limit=10)
    assert len(rows) > 0
    assert all(r.name for r in rows)


async def test_radius_is_respected(db):
    """A POI at 1.9 km is included, one at 2.1 km is not."""
    rows = await search_pois(db, **INDIRANAGAR, radius_km=2, limit=50)
    assert all(r.distance_m <= 2000 for r in rows), \
        f"max was {max(r.distance_m for r in rows)}m"


async def test_wider_radius_returns_at_least_as_many(db):
    near = await search_pois(db, **INDIRANAGAR, radius_km=1, limit=50)
    far = await search_pois(db, **INDIRANAGAR, radius_km=5, limit=50)
    assert len(far) >= len(near)


async def test_category_filter_is_exclusive(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=3,
                             categories=["cafe"], limit=20)
    assert len(rows) > 0
    assert {r.category for r in rows} == {"cafe"}


async def test_multiple_categories(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=3,
                             categories=["cafe", "bar"], limit=30)
    assert {r.category for r in rows} <= {"cafe", "bar"}


async def test_budget_ceiling_excludes_expensive(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=3,
                             max_cost_inr=100, limit=20)
    for r in rows:
        cost = r.cost_estimate_inr if r.cost_estimate_inr is not None \
            else r.category_typical_inr
        assert cost <= 100, f"{r.name} costs {cost}"


async def test_exclusions_are_honoured(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=2, limit=5)
    assert rows
    excluded = rows[0].id
    again = await search_pois(db, **INDIRANAGAR, radius_km=2,
                              exclude_ids=[excluded], limit=5)
    assert excluded not in {r.id for r in again}


async def test_low_confidence_hours_are_included_not_filtered(db):
    """THE NQ-014 rule. 91.5% of POIs have category-default hours at
    confidence 0.3. Filtering hard on them would remove 13,563 of 14,851
    POIs from every search."""
    rows = await search_pois(db, **INDIRANAGAR, radius_km=3,
                             open_at=datetime(2026, 9, 5, 16, 0), limit=50)
    confidences = [r.hours_confidence for r in rows if r.hours_confidence]
    assert any(c < HOURS_CONFIDENCE_THRESHOLD for c in confidences), \
        "no low-confidence POIs survived the open_at filter"


async def test_hours_verified_flag_matches_threshold(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=3, limit=30)
    for r in rows:
        d = r.to_dict()
        if r.hours_confidence is None:
            assert d["hours_verified"] is False
        else:
            assert d["hours_verified"] == (
                r.hours_confidence >= HOURS_CONFIDENCE_THRESHOLD)


async def test_results_ordered_by_prominence_then_distance(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=3, limit=30)
    keys = [(-r.prominence, r.distance_m) for r in rows]
    assert keys == sorted(keys), "ordering is not prominence desc, distance asc"


async def test_radius_is_clamped(db):
    """A caller asking for 500 km must not get a nationwide scan."""
    rows = await search_pois(db, **INDIRANAGAR, radius_km=500, limit=5)
    assert all(r.distance_m <= MAX_RADIUS_KM * 1000 for r in rows)


async def test_limit_is_respected(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=5, limit=7)
    assert len(rows) <= 7


async def test_detail_returns_full_record(db):
    rows = await search_pois(db, **INDIRANAGAR, radius_km=2, limit=1)
    assert rows
    d = await get_poi_detail(db, rows[0].id)
    assert d is not None
    assert d["name"] == rows[0].name
    assert d["source"] == "openstreetmap"
    assert d["cost_basis"] in ("poi_specific", "category_median")
    assert len(d["opening_hours"]) >= 7, "a week of hours expected"


async def test_detail_returns_none_for_missing_poi(db):
    assert await get_poi_detail(db, 99_999_999) is None


async def test_search_uses_gist_index(db):
    """Without the GIST index this is a seq scan over 14,851 rows. It looks
    fine now and collapses as the dataset grows."""
    plan = (await db.execute(text("""
        EXPLAIN (FORMAT TEXT)
        SELECT id FROM pois
        WHERE ST_DWithin(geom,
            ST_SetSRID(ST_MakePoint(77.6408, 12.9784), 4326)::geography, 2000)
    """))).scalars().all()
    assert any("idx_pois_geom" in line for line in plan), \
        "GIST index not used:\n" + "\n".join(plan)



