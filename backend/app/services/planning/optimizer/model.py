"""NQ-023 - CP-SAT itinerary optimizer.

An orienteering problem with time windows: choose a SUBSET of candidate POIs
and an order, maximizing collected preference score subject to a time horizon,
per-POI opening windows, a money budget, a walking cap, meal placement and
category diversity.

THREE THINGS THAT SILENTLY BREAK THIS MODEL, all avoided below:

  1. Time propagation without OnlyEnforceIf. Without it every arc constrains
     time whether or not it is used, turning the selective tour into a
     mandatory TSP over all candidates - INFEASIBLE for everything.

  2. Missing self-loop literals in AddCircuit. arc[i][i] must be the literal
     "node i is NOT visited". Without it, optional nodes are not optional.

  3. Unscaled float objectives. CP-SAT is integer-only; scores must be scaled
     to ints explicitly or they silently truncate to zero.

Node 0 is the origin and is always visited. Nodes 1..n are candidates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ortools.sat.python import cp_model

SCORE_SCALE = 100_000          # floats -> ints for the objective
SOLVE_TIME_LIMIT_S = 10.0
SOLVER_SEED = 42            # fixed: same input must give the same itinerary
MAX_CONSECUTIVE_SAME_CATEGORY = 2


class OptimizerStatus(str, Enum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


@dataclass
class OptimizerNode:
    """One candidate. Node 0 is the origin."""
    poi_id: int | None
    name: str
    category: str
    score: float                  # 0..1 from the NQ-017 ranker
    visit_minutes: int
    cost_inr: int
    open_min: int                 # earliest arrival, minutes since midnight
    close_min: int                # latest departure
    hours_confidence: float = 1.0
    is_meal: bool = False


@dataclass
class OptimizerArc:
    """Travel between two nodes, mode already chosen by NQ-020."""
    duration_min: int
    cost_inr: int
    walk_m: int
    mode: str


@dataclass
class Stop:
    seq: int
    node_index: int
    poi_id: int | None
    name: str
    category: str
    arrive_min: int
    depart_min: int
    visit_minutes: int
    cost_inr: int
    mode_from_prev: str | None
    travel_minutes_from_prev: int


@dataclass
class OptimizerResult:
    status: OptimizerStatus
    stops: list[Stop] = field(default_factory=list)
    total_cost_inr: int = 0
    total_duration_min: int = 0
    total_walk_m: int = 0
    objective_value: float = 0.0
    solve_ms: int = 0
    optimizer: str = "cpsat"
    unsatisfied_must: list[str] = field(default_factory=list)

    @property
    def is_solution(self) -> bool:
        return self.status in (OptimizerStatus.OPTIMAL, OptimizerStatus.FEASIBLE)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "optimizer": self.optimizer,
            "total_cost_inr": self.total_cost_inr,
            "total_duration_min": self.total_duration_min,
            "total_walk_m": self.total_walk_m,
            "objective_value": self.objective_value,
            "solve_ms": self.solve_ms,
            "unsatisfied_must": self.unsatisfied_must,
            "stops": [
                {
                    "seq": s.seq, "poi_id": s.poi_id, "name": s.name,
                    "category": s.category,
                    "arrive_min": s.arrive_min, "depart_min": s.depart_min,
                    "visit_minutes": s.visit_minutes, "cost_inr": s.cost_inr,
                    "mode_from_prev": s.mode_from_prev,
                    "travel_minutes_from_prev": s.travel_minutes_from_prev,
                }
                for s in self.stops
            ],
        }


@dataclass
class ModeWeights:
    """The three planning modes are objective weights, not different prompts."""
    score: float
    travel_penalty: float
    time_efficiency: float
    visit_multiplier: float
    max_stops: int


MODES = {
    "balanced": ModeWeights(1.0, 0.5, 0.3, 1.0, 6),
    "quick":    ModeWeights(0.8, 1.2, 1.0, 0.7, 8),
    "relaxed":  ModeWeights(1.2, 0.3, 0.1, 1.4, 4),
}

# MUST satisfaction outranks everything. An order of magnitude above the
# score term so no combination of preferences can outbid a MUST.
MUST_WEIGHT = 100_000


@dataclass
class InterestRequirement:
    category: str
    count: int
    is_must: bool


def optimize(
    nodes: list[OptimizerNode],
    arcs: dict[tuple[int, int], OptimizerArc],
    *,
    start_min: int,
    end_min: int,
    budget_inr: int | None,
    max_walk_m: int,
    requirements: list[InterestRequirement],
    mode: str = "balanced",
    meal_required: bool = False,
    meal_windows: list[tuple[int, int]] | None = None,
    time_limit_s: float = SOLVE_TIME_LIMIT_S,
) -> OptimizerResult:
    """Solve. nodes[0] is the origin; arcs maps (i, j) -> OptimizerArc."""
    n = len(nodes)
    if n < 2:
        return OptimizerResult(status=OptimizerStatus.INFEASIBLE)

    w = MODES.get(mode, MODES["balanced"])
    m = cp_model.CpModel()

    # --- variables --------------------------------------------------------
    visit = [m.NewBoolVar(f"visit_{i}") for i in range(n)]
    m.Add(visit[0] == 1)                       # origin is always visited

    arc_lit: dict[tuple[int, int], cp_model.IntVar] = {}
    circuit_arcs: list[tuple[int, int, cp_model.IntVar]] = []

    for i in range(n):
        for j in range(n):
            if i == j:
                # PITFALL 2: the self-loop literal IS "node i is not visited".
                # Without this, optional nodes are not optional.
                if i != 0:
                    circuit_arcs.append((i, i, visit[i].Not()))
                else:
                    # The origin needs a self-loop too, or an empty tour is
                    # not a valid circuit and the model returns INFEASIBLE
                    # whenever nothing can be visited - a closed venue, or a
                    # walking cap that no real stop can satisfy.
                    no_stops = m.NewBoolVar("no_stops")
                    m.Add(sum(visit[1:]) == 0).OnlyEnforceIf(no_stops)
                    m.Add(sum(visit[1:]) >= 1).OnlyEnforceIf(no_stops.Not())
                    circuit_arcs.append((0, 0, no_stops))
                continue
            if (i, j) not in arcs:
                continue
            lit = m.NewBoolVar(f"arc_{i}_{j}")
            arc_lit[(i, j)] = lit
            circuit_arcs.append((i, j, lit))

    m.AddCircuit(circuit_arcs)

    arrive = [m.NewIntVar(start_min, end_min, f"arrive_{i}") for i in range(n)]
    depart = [m.NewIntVar(start_min, end_min, f"depart_{i}") for i in range(n)]

    m.Add(arrive[0] == start_min)
    m.Add(depart[0] == start_min)

    # --- visit duration ---------------------------------------------------
    for i in range(1, n):
        vm = max(15, int(nodes[i].visit_minutes * w.visit_multiplier))
        m.Add(depart[i] == arrive[i] + vm).OnlyEnforceIf(visit[i])
        m.Add(depart[i] == arrive[i]).OnlyEnforceIf(visit[i].Not())

    # --- time propagation -------------------------------------------------
    # PITFALL 1: OnlyEnforceIf is mandatory. Without it, every arc constrains
    # time whether used or not, and nothing is ever feasible.
    for (i, j), a in arcs.items():
        if (i, j) not in arc_lit:
            continue
        if j == 0:
            continue                            # return leg does not bound time
        m.Add(arrive[j] >= depart[i] + a.duration_min).OnlyEnforceIf(
            arc_lit[(i, j)])

    # --- opening windows ---------------------------------------------------
    for i in range(1, n):
        node = nodes[i]
        # Low-confidence hours are category defaults, not real data. Treating
        # them as hard would delete 91% of POIs from every itinerary (NQ-014).
        if node.hours_confidence >= 0.5:
            m.Add(arrive[i] >= node.open_min).OnlyEnforceIf(visit[i])
            m.Add(depart[i] <= node.close_min).OnlyEnforceIf(visit[i])

    # --- budget ------------------------------------------------------------
    cost_terms = [visit[i] * nodes[i].cost_inr for i in range(1, n)]
    cost_terms += [lit * arcs[(i, j)].cost_inr for (i, j), lit in arc_lit.items()]
    total_cost = sum(cost_terms)
    if budget_inr is not None:
        m.Add(total_cost <= budget_inr)

    # --- walking cap -------------------------------------------------------
    total_walk = sum(lit * arcs[(i, j)].walk_m for (i, j), lit in arc_lit.items())
    m.Add(total_walk <= max_walk_m)

    # --- stop cap ----------------------------------------------------------
    m.Add(sum(visit[1:]) <= w.max_stops)

    # --- interests ---------------------------------------------------------
    must_satisfied: list[cp_model.IntVar] = []
    for req in requirements:
        members = [i for i in range(1, n) if nodes[i].category == req.category]
        if not members:
            continue
        chosen = sum(visit[i] for i in members)
        m.Add(chosen <= req.count)
        if req.is_must:
            # Soft, so an over-constrained instance still returns the best
            # partial itinerary rather than plain INFEASIBLE. The weight makes
            # violating it unattractive.
            sat = m.NewBoolVar(f"must_{req.category}")
            m.Add(chosen >= req.count).OnlyEnforceIf(sat)
            m.Add(chosen < req.count).OnlyEnforceIf(sat.Not())
            must_satisfied.append(sat)

    # --- meal --------------------------------------------------------------
    if meal_required and meal_windows:
        meal_nodes = [i for i in range(1, n) if nodes[i].is_meal]
        if meal_nodes:
            in_window = []
            for i in meal_nodes:
                for lo, hi in meal_windows:
                    if lo > end_min or hi < start_min:
                        continue
                    b = m.NewBoolVar(f"meal_{i}_{lo}")
                    m.Add(arrive[i] >= lo).OnlyEnforceIf(b)
                    m.Add(arrive[i] <= hi).OnlyEnforceIf(b)
                    m.Add(b <= visit[i])
                    in_window.append(b)
            if in_window:
                m.Add(sum(in_window) >= 1)

    # --- diversity ---------------------------------------------------------
    # No three consecutive stops of the same category.
    for (i, j), lit_ij in arc_lit.items():
        if i == 0 or j == 0 or nodes[i].category != nodes[j].category:
            continue
        for (j2, k), lit_jk in arc_lit.items():
            if j2 != j or k == 0:
                continue
            if nodes[k].category == nodes[i].category:
                m.Add(lit_ij + lit_jk <= MAX_CONSECUTIVE_SAME_CATEGORY - 1 + 1)

    # --- objective ---------------------------------------------------------
    # PITFALL 3: scale to ints explicitly or scores truncate to zero.
    obj = []
    obj += [MUST_WEIGHT * s for s in must_satisfied]
    obj += [int(w.score * SCORE_SCALE * nodes[i].score) * visit[i]
            for i in range(1, n)]
    travel_total = sum(lit * arcs[(i, j)].duration_min
                       for (i, j), lit in arc_lit.items())
    obj.append(-int(w.travel_penalty * 10) * travel_total)
    # Cost is discouraged mildly. Coefficient scaled here rather than dividing
    # the expression - CP-SAT linear expressions do not support //.
    obj.append(-int(w.time_efficiency * 1) * total_cost)
    m.Maximize(sum(obj))

    # --- solve -------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    # Single worker: parallel search is non-deterministic even with a fixed
    # seed, because workers race and ties are broken by whichever finishes
    # first. Reproducibility matters more here than raw speed - plan_snapshots
    # is meaningless if the same input can yield a different itinerary.
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = SOLVER_SEED
    status = solver.Solve(m)

    status_map = {
        cp_model.OPTIMAL: OptimizerStatus.OPTIMAL,
        cp_model.FEASIBLE: OptimizerStatus.FEASIBLE,
        cp_model.INFEASIBLE: OptimizerStatus.INFEASIBLE,
    }
    result = OptimizerResult(
        status=status_map.get(status, OptimizerStatus.UNKNOWN),
        solve_ms=int(solver.WallTime() * 1000),
    )
    if not result.is_solution:
        return result

    result.objective_value = solver.ObjectiveValue()

    # --- extract the tour ---------------------------------------------------
    successor = {i: j for (i, j), lit in arc_lit.items()
                 if solver.Value(lit) == 1}
    order, cur, guard = [], 0, 0
    while guard <= len(nodes):
        nxt = successor.get(cur)
        if nxt is None or nxt == 0:
            break
        order.append(nxt)
        cur = nxt
        guard += 1

    prev = 0
    for seq, idx in enumerate(order, start=1):
        node = nodes[idx]
        arc = arcs.get((prev, idx))
        result.stops.append(Stop(
            seq=seq, node_index=idx, poi_id=node.poi_id, name=node.name,
            category=node.category,
            arrive_min=solver.Value(arrive[idx]),
            depart_min=solver.Value(depart[idx]),
            visit_minutes=solver.Value(depart[idx]) - solver.Value(arrive[idx]),
            cost_inr=node.cost_inr,
            mode_from_prev=arc.mode if arc else None,
            travel_minutes_from_prev=arc.duration_min if arc else 0,
        ))
        result.total_cost_inr += node.cost_inr + (arc.cost_inr if arc else 0)
        result.total_walk_m += arc.walk_m if arc else 0
        prev = idx

    if result.stops:
        result.total_duration_min = result.stops[-1].depart_min - start_min

    for req in requirements:
        if not req.is_must:
            continue
        got = sum(1 for s in result.stops if s.category == req.category)
        if got < req.count:
            result.unsatisfied_must.append(
                f"{req.category}: got {got} of {req.count}")

    return result





