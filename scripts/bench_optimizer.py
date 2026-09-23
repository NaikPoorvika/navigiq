"""NQ-023 - optimizer scaling check.

The candidate cap is 50. If a 50-node instance blows the 10-second budget,
the single-worker determinism choice needs revisiting.
"""
import random
import sys
import time

sys.path.insert(0, "backend")

from app.services.planning.optimizer.model import (
    InterestRequirement, OptimizerArc, OptimizerNode, optimize,
)

CATS = ["cafe", "restaurant", "park", "temple", "museum", "bar", "historical"]


def build(n, seed=42):
    rng = random.Random(seed)
    nodes = [OptimizerNode(None, "Origin", "origin", 0.0, 0, 0, 0, 1440)]
    for i in range(n):
        nodes.append(OptimizerNode(
            poi_id=i, name=f"POI-{i}", category=rng.choice(CATS),
            score=round(rng.uniform(0.2, 1.0), 3),
            visit_minutes=rng.choice([30, 45, 60, 90]),
            cost_inr=rng.choice([0, 100, 250, 500]),
            open_min=9 * 60, close_min=22 * 60,
        ))
    arcs = {
        (i, j): OptimizerArc(rng.randint(8, 35), rng.choice([0, 30, 60]),
                             rng.choice([0, 200, 500]), "auto")
        for i in range(n + 1) for j in range(n + 1) if i != j
    }
    return nodes, arcs


for n in (10, 20, 35, 50):
    nodes, arcs = build(n)
    t0 = time.perf_counter()
    r = optimize(
        nodes, arcs, start_min=15 * 60, end_min=20 * 60, budget_inr=2000,
        max_walk_m=3000,
        requirements=[InterestRequirement("cafe", 1, True),
                      InterestRequirement("historical", 1, True),
                      InterestRequirement("park", 1, False)],
        mode="balanced", time_limit_s=10.0,
    )
    wall = (time.perf_counter() - t0) * 1000
    print(f"N={n:>3}  {r.status.value:<10} stops={len(r.stops):<2} "
          f"solve={r.solve_ms:>6} ms  wall={wall:>7.0f} ms  "
          f"cost=Rs {r.total_cost_inr}")