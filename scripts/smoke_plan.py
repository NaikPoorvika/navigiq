"""NQ-025 - the demo scenario, end to end, no AI involved.

'I have Rs 1500 and 5 hours starting from Indiranagar this Saturday
 afternoon. I want good food, one historical place and a sunset spot.
 I don't want to walk much.'
"""
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


SPEC = TripSpec(
    origin={"lat": 12.9784, "lon": 77.6408, "name": "Indiranagar"},
    date=next_saturday(),
    start_time_local="15:00",
    end_time_local="20:00",
    budget_inr=1500,
    party_size=1,
    interests=[
        {"category": "restaurant", "count": 1, "priority": "must"},
        {"category": "historical", "count": 1, "priority": "must"},
        {"category": "sunset", "count": 1, "priority": "must"},
    ],
    transport=["walking", "auto"],
    constraints={"max_walking_km": 2.0, "meal_required": True},
    mode="balanced",
)


def hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


async def main():
    async with AsyncSessionLocal() as db:
        r = await plan(db, SPEC, persist=False)

    print("=" * 68)
    print(f"  {SPEC.date}  {SPEC.start_time_local}-{SPEC.end_time_local}  "
          f"Rs {SPEC.budget_inr}  from {SPEC.origin.name}")
    print("=" * 68)

    w = r.weather or {}
    print(f"weather   {w.get('condition')}  {w.get('mean_temp_c')}C  "
          f"rain {w.get('max_precip_mm')}mm  available={w.get('available')}")

    f = r.feasibility or {}
    b = f.get("bounds", {})
    print(f"feasible  {f.get('feasible')}  "
          f"need {b.get('total_required_minutes')}min of "
          f"{b.get('available_minutes')}  "
          f"min cost Rs {b.get('min_cost_inr')}")
    if f.get("violated"):
        print(f"          violated: {f['violated']}")

    if r.relaxations_applied:
        print("relaxed  ", "; ".join(r.relaxations_applied))

    if not r.itinerary:
        print("\nNO ITINERARY")
        for s in f.get("suggested_relaxations", []):
            print(f"  suggest: {s['description']} ({s['impact']})")
        print("\ntimings", r.timings_ms)
        return

    it = r.itinerary
    print(f"\noptimizer {it['status']}  solve {it['solve_ms']}ms  "
          f"objective {it['objective_value']:.0f}")
    print(f"total     Rs {it['total_cost_inr']}  "
          f"{it['total_duration_min']}min  walk {it['total_walk_m']}m\n")

    for s in it["stops"]:
        travel = (f"  <- {s['travel_minutes_from_prev']}min "
                  f"by {s['mode_from_prev']}" if s["mode_from_prev"] else "")
        print(f"  {s['seq']}. {hhmm(s['arrive_min'])}-{hhmm(s['depart_min'])}  "
              f"{s['name'][:38]:<40} {s['category']:<12} Rs {s['cost_inr']}{travel}")

    if it.get("unsatisfied_must"):
        print(f"\n  UNSATISFIED: {it['unsatisfied_must']}")

    v = r.validator_report or {}
    print(f"\nvalidator {'PASS' if v.get('valid') else 'FAIL'}  "
          f"({len(v.get('rules_run', []))} rules)")
    for finding in v.get("findings", []):
        print(f"  {finding['rule']}: {finding['message']}")

    print(f"\ntimings   {r.timings_ms}")
    print(f"ok        {r.ok}")


asyncio.run(main())