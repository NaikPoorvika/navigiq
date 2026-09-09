"""Isolate why the optimizer returns INFEASIBLE on real data."""
import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, "backend")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq")

from app.db.session import AsyncSessionLocal
from app.schemas.tripspec import TripSpec
from app.services.planning.orchestrator import plan


def next_saturday():
    d = date.today()
    return d + timedelta(days=(5 - d.weekday()) % 7 or 7)


def make_spec(meal=True, interests=None):
    return TripSpec(
        origin={"lat": 12.9784, "lon": 77.6408, "name": "Indiranagar"},
        date=next_saturday(),
        start_time_local="15:00", end_time_local="20:00",
        budget_inr=1500, party_size=1,
        interests=interests or [
            {"category": "restaurant", "count": 1, "priority": "must"},
            {"category": "historical", "count": 1, "priority": "must"},
            {"category": "sunset", "count": 1, "priority": "must"},
        ],
        transport=["walking", "auto"],
        constraints={"max_walking_km": 2.0, "meal_required": meal},
        mode="balanced",
    )


async def run(label, spec):
    async with AsyncSessionLocal() as db:
        r = await plan(db, spec, persist=False)
    it = r.itinerary or {}
    print(f"\n--- {label} ---")
    print(f"  status: {it.get('status')}  stops: {len(it.get('stops', []))}")
    for s in it.get("stops", []):
        print(f"    {s['seq']}. {s['name'][:34]:<36} {s['category']:<12} "
              f"Rs {s['cost_inr']}")
    if it.get("unsatisfied_must"):
        print(f"    unsatisfied: {it['unsatisfied_must']}")


async def main():
    await run("A: as specified (meal required)", make_spec(meal=True))
    await run("B: meal_required = False", make_spec(meal=False))
    await run("C: no sunset requirement", make_spec(meal=False, interests=[
        {"category": "restaurant", "count": 1, "priority": "must"},
        {"category": "historical", "count": 1, "priority": "must"},
    ]))
    await run("D: sunset only", make_spec(meal=False, interests=[
        {"category": "sunset", "count": 1, "priority": "must"},
    ]))


asyncio.run(main())