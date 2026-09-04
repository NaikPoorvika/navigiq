import asyncio, sys
sys.path.insert(0, "backend")
from datetime import datetime
from app.services.routing.service import RoutingService, area_class

INDIRANAGAR = (12.9784, 77.6408)
CUBBON = (12.9716, 77.5946)
LALBAGH = (12.9489, 77.5867)


async def main():
    svc = RoutingService()

    print("--- car, no time given ---")
    r = await svc.get_route(INDIRANAGAR, CUBBON)
    print(f"  {r.distance_m:.0f}m  raw={r.raw_duration_s:.0f}s  "
          f"adj={r.duration_s:.0f}s  factor={r.traffic_factor}")

    print("--- car, Saturday 18:00 (pm peak, weekend) ---")
    r = await svc.get_route(INDIRANAGAR, CUBBON,
                            depart_at=datetime(2026, 9, 5, 18, 0), overhead_s=300)
    print(f"  raw={r.raw_duration_s:.0f}s  adj={r.duration_s:.0f}s  "
          f"factor={r.traffic_factor}")

    print("--- car, Tuesday 09:00 (am peak, weekday) ---")
    r = await svc.get_route(INDIRANAGAR, CUBBON,
                            depart_at=datetime(2026, 9, 8, 9, 0))
    print(f"  raw={r.raw_duration_s:.0f}s  adj={r.duration_s:.0f}s  "
          f"factor={r.traffic_factor}")

    print("--- walking (never adjusted) ---")
    r = await svc.get_route(INDIRANAGAR, (12.9760, 77.6350), mode="walking",
                            depart_at=datetime(2026, 9, 8, 9, 0))
    print(f"  {r.distance_m:.0f}m  {r.duration_s:.0f}s  factor={r.traffic_factor}")

    print("--- 3x3 matrix, Saturday 18:00 ---")
    m = await svc.get_matrix([INDIRANAGAR, CUBBON, LALBAGH],
                             depart_at=datetime(2026, 9, 5, 18, 0))
    for row in m.durations:
        print("  " + "  ".join(f"{v:7.1f}" for v in row))

    print("--- area classes ---")
    for name, pt in [("Indiranagar", INDIRANAGAR), ("Cubbon", CUBBON),
                     ("Nandi Hills", (13.3702, 77.6835))]:
        print(f"  {name:<14}{area_class(*pt)}")


asyncio.run(main())
