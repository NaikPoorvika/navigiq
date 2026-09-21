"""Deterministic greedy fallback scheduler (section 45).

Used when CP-SAT times out or returns no solution. Same inputs as the CP-SAT
model, same hard constraints (hours, budget, window, buffer, must-visit,
stop caps, category caps, hop filter via the arc set), no randomness:
candidates are taken in descending score order with ties on node index, and
each is inserted at the end of the tour only if the whole tour stays valid.

It is weaker than CP-SAT (no reordering search), which is the point: it is
simple enough to trust as a fallback. The independent validator checks its
output exactly like the optimizer's.
"""
from __future__ import annotations

import time

from app.services.planning.optimizer.model import (
    OptimizerArc, OptimizerNode, OptimizerResult, OptimizerStatus, Stop,
)


def greedy_schedule(
    nodes: list[OptimizerNode],
    arcs: dict[tuple[int, int], OptimizerArc],
    *,
    start_min: int,
    end_min: int,
    budget_inr: int | None,
    max_stops: int,
    min_stops: int | None = None,
    visit_multiplier: float = 1.0,
    category_caps: dict[str, int] | None = None,
    min_visit_minutes: int = 15,
) -> OptimizerResult:
    t0 = time.perf_counter()
    n = len(nodes)
    order = sorted(range(1, n), key=lambda i: (not nodes[i].must_visit, -nodes[i].score, i))
    tour: list[int] = []
    for idx in order:
        if len(tour) >= max_stops:
            break
        trial = tour + [idx]
        if _schedule(trial, nodes, arcs, start_min, end_min, budget_inr, visit_multiplier,
                     category_caps, min_visit_minutes) is not None:
            tour = trial
    # Must-visit nodes that did not fit at the end may fit earlier: try each
    # insertion position deterministically.
    for idx in order:
        if not nodes[idx].must_visit or idx in tour:
            continue
        for pos in range(len(tour) + 1):
            trial = tour[:pos] + [idx] + tour[pos:]
            if _schedule(trial, nodes, arcs, start_min, end_min, budget_inr, visit_multiplier,
                         category_caps, min_visit_minutes) is not None:
                tour = trial
                break
    schedule = _schedule(tour, nodes, arcs, start_min, end_min, budget_inr, visit_multiplier,
                         category_caps, min_visit_minutes)
    must_ok = all(i in tour for i in range(1, n) if nodes[i].must_visit)
    if schedule is None or not must_ok or (min_stops and len(tour) < min_stops):
        return OptimizerResult(status=OptimizerStatus.INFEASIBLE, optimizer="greedy",
                               solve_ms=int((time.perf_counter() - t0) * 1000))
    result = OptimizerResult(status=OptimizerStatus.FEASIBLE, optimizer="greedy")
    prev = 0
    for seq, (idx, arrive, depart) in enumerate(schedule, start=1):
        node = nodes[idx]
        arc = arcs.get((prev, idx))
        result.stops.append(Stop(seq=seq, node_index=idx, poi_id=node.poi_id, name=node.name,
                                 category=node.category, arrive_min=arrive, depart_min=depart,
                                 visit_minutes=depart - arrive, cost_inr=node.cost_inr,
                                 mode_from_prev=arc.mode if arc else None,
                                 travel_minutes_from_prev=arc.duration_min if arc else 0))
        result.total_cost_inr += node.cost_inr
        prev = idx
    if result.stops:
        result.total_duration_min = result.stops[-1].depart_min - start_min
    result.solve_ms = int((time.perf_counter() - t0) * 1000)
    return result


def _schedule(tour, nodes, arcs, start_min, end_min, budget, mult, caps, min_visit):
    """Earliest-start schedule for a fixed order, or None if any constraint fails."""
    if budget is not None and sum(nodes[i].cost_inr for i in tour) > budget:
        return None
    if caps:
        counts: dict[str, int] = {}
        for i in tour:
            counts[nodes[i].category] = counts.get(nodes[i].category, 0) + 1
            if counts[nodes[i].category] > caps.get(nodes[i].category, 10 ** 6):
                return None
    out = []
    t = start_min
    prev = 0
    for i in tour:
        arc = arcs.get((prev, i))
        if arc is None:
            return None
        t += arc.duration_min
        node = nodes[i]
        if node.hours_confidence >= 0.5:
            t = max(t, node.open_min)
        visit = max(min_visit, int(node.visit_minutes * mult))
        depart = t + visit
        if node.hours_confidence >= 0.5 and depart > node.close_min:
            return None
        if depart > end_min:
            return None
        out.append((i, t, depart))
        t = depart
        prev = i
    return out
