import asyncio, sys, os
sys.path.insert(0, "backend")
os.environ.setdefault("DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq")

from datetime import datetime
from app.db.session import AsyncSessionLocal
from app.services.poi.search import search_pois, get_poi_detail


async def main():
    async with AsyncSessionLocal() as db:
        print("--- cafes and bars near Indiranagar, Sat 16:00 ---")
        rows = await search_pois(db, lat=12.9784, lon=77.6408, radius_km=2,
                                 categories=["cafe", "bar"],
                                 open_at=datetime(2026, 9, 5, 16, 0), limit=10)
        for r in rows:
            print(f"{r.name[:30]:<32}{r.category:<8}{r.distance_m:>5}m  "
                  f"open={r.open_at_requested}  conf={r.hours_confidence}")

        print("\n--- budget filter: max 100 INR ---")
        rows = await search_pois(db, lat=12.9784, lon=77.6408, radius_km=3,
                                 max_cost_inr=100, limit=5)
        for r in rows:
            cost = r.cost_estimate_inr if r.cost_estimate_inr is not None else r.category_typical_inr
            print(f"{r.name[:30]:<32}{r.category:<12}cost={cost}")

        print("\n--- no filters at all ---")
        rows = await search_pois(db, lat=12.9784, lon=77.6408, radius_km=1, limit=5)
        for r in rows:
            print(f"{r.name[:30]:<32}{r.category:<12}{r.distance_m:>5}m")

        if rows:
            d = await get_poi_detail(db, rows[0].id)
            print(f"\n--- detail: {d['name']} ---")
            print("  category:", d["category"], "| visit:", d["visit_minutes"], "min")
            print("  cost basis:", d["cost_basis"])
            print("  hours rows:", len(d["opening_hours"]))


asyncio.run(main())
