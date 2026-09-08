import asyncio, sys
sys.path.insert(0, "backend")
from datetime import datetime
from app.services.routing.multimodal import MultiModalRouter
from app.services.routing.service import RoutingUnavailable

INDIRANAGAR = (12.9784, 77.6408)
MG_ROAD = (12.9756, 77.6068)
LALBAGH = (12.9489, 77.5867)
NEARBY = (12.9760, 77.6350)

SAT_1800 = datetime(2026, 9, 5, 18, 0)


async def main():
    r = MultiModalRouter()
    modes = ["walking", "auto", "cab"]

    cases = [
        ("short hop (walkable)", INDIRANAGAR, NEARBY),
        ("medium (competitive?)", INDIRANAGAR, MG_ROAD),
        ("long cross-city", INDIRANAGAR, LALBAGH),
    ]

    for label, o, d in cases:
        print(f"\n--- {label} ---")
        try:
            arc = await r.build_arc(0, 1, o, d, modes, SAT_1800,
                                    party_size=1, max_walking_m=3000)
            print(f"  WINNER: {arc.mode}  {arc.duration_s/60:.1f} min  "
                  f"Rs {arc.cost_inr}  walk {arc.walk_m:.0f}m")
            for why in arc.rejected:
                print(f"    rejected {why}")
        except RoutingUnavailable as exc:
            print(f"  {exc}")

    print("\n--- walking cap forces a vehicle ---")
    arc = await r.build_arc(0, 1, INDIRANAGAR, NEARBY, modes, SAT_1800,
                            max_walking_m=100)
    print(f"  WINNER: {arc.mode}  walk {arc.walk_m:.0f}m")
    for why in arc.rejected:
        print(f"    rejected {why}")

    print("\n--- 3x3 matrix ---")
    m = await r.build_matrix([INDIRANAGAR, MG_ROAD, LALBAGH], modes, SAT_1800)
    for row in m:
        print("  " + "  ".join(
            f"{a.mode[:4]:>5}/{a.duration_s/60:>4.0f}m" if a else "    -    "
            for a in row))


asyncio.run(main())
