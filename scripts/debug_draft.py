import asyncio, os, sys, traceback
sys.path.insert(0, "backend")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq")

from app.db.base import Base  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.schemas.trip_draft import TripDraft
from app.services.planning.draft_builder import build_tripspec
from app.services.planning.orchestrator import plan_trip

DRAFT = TripDraft(
    origin={"name": "Koramangala", "lat": 99.9, "lon": 99.9},
    date_phrase="saturday",
    start_time_local="10:00",
    end_time_local="18:00",
    days=2,
    interests=[
        {"category": "restaurant", "priority": "must"},
        {"category": "historical", "priority": "must"},
    ],
)


async def main():
    async with AsyncSessionLocal() as db:
        try:
            print("--- building ---")
            built = await build_tripspec(db, DRAFT)
            print("clarify:", built.needs_clarification)
            print("assumptions:", built.assumptions)
            if built.tripspec:
                print("origin:", built.tripspec.origin)
                print("dates:", built.tripspec.day_dates)

            if built.tripspec:
                print("\n--- planning ---")
                r = await plan_trip(db, built.tripspec, persist=False)
                print("ok:", r["ok"], "| planned:", r["days_planned"])
                for d in r["days"]:
                    stops = (d.get("itinerary") or {}).get("stops", [])
                    print(f"  day {d['day']} {d['date']}: "
                          f"{[s['name'] for s in stops]}")
        except Exception:
            traceback.print_exc()


asyncio.run(main())