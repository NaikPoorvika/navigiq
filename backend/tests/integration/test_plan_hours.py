"""Regression guard: real opening hours must be respected end to end.

Before this test existed, the orchestrator passed (0, 1440) to the optimizer
and None to the validator, so opening hours were never enforced and
VENUE_CLOSED never ran - while every report said 'PASS'.

Needs Postgres and OSRM running.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq",
)

from app.db.base import Base  # noqa: E402,F401  registers all models
from app.schemas.tripspec import TripSpec  # noqa: E402
from app.services.planning.orchestrator import plan  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def _real_hours(db, poi_id: int, dow: int):
    return (await db.execute(text("""
        SELECT open_min, close_min, is_24h, confidence
        FROM poi_opening_hours
        WHERE poi_id = :id AND day_of_week = :dow
        ORDER BY confidence DESC, (close_min - open_min) DESC
        LIMIT 1
    """), {"id": poi_id, "dow": dow})).first()


@pytest.mark.parametrize("start,end", [("07:00", "11:00"), ("15:00", "20:00")])
async def test_stops_with_real_hours_are_inside_them(db, start, end):
    spec = TripSpec(
        origin={"lat": 12.9784, "lon": 77.6408, "name": "Indiranagar"},
        date="2026-09-26", start_time_local=start, end_time_local=end,
        interests=[{"category": "restaurant", "priority": "must"},
                   {"category": "cafe", "priority": "should"}],
        transport=["walking", "auto"],
        constraints={"max_walking_km": 2.0, "meal_required": False},
    )
    r = await plan(db, spec, persist=False)
    assert r.ok, r.feasibility

    checked = 0
    for s in r.itinerary["stops"]:
        h = await _real_hours(db, s["poi_id"], spec.date.weekday())
        if h is None or h.is_24h or float(h.confidence) < 0.5:
            continue   # a category default - soft by design (NQ-014)
        checked += 1
        assert s["arrive_min"] >= h.open_min, f"{s['name']} arrives before opening"
        assert s["depart_min"] <= h.close_min, f"{s['name']} leaves after closing"

    assert "VENUE_CLOSED" in r.validator_report["rules_run"]