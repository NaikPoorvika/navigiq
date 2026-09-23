"""Tests for NQ-023 CP-SAT optimizer.

Deliberately tiny instances where the correct answer can be worked out by
hand. A 50-node test you cannot verify proves nothing; a 3-node test with a
known optimum proves the model is actually right.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.planning.optimizer.model import (  # noqa: E402
    InterestRequirement,
    OptimizerArc,
    OptimizerNode,
    OptimizerStatus,
    optimize,
)

DAY_START = 15 * 60      # 15:00
DAY_END = 20 * 60        # 20:00


def node(name, category, score=0.5, visit=60, cost=100,
         open_min=0, close_min=1440, conf=1.0, meal=False, poi_id=None):
    return OptimizerNode(
        poi_id=poi_id, name=name, category=category, score=score,
        visit_minutes=visit, cost_inr=cost, open_min=open_min,
        close_min=close_min, hours_confidence=conf, is_meal=meal,
    )


def origin():
    return node("Origin", "origin", score=0, visit=0, cost=0)


def full_arcs(n, duration=15, cost=30, walk=0, mode="auto"):
    """Complete graph with uniform arcs."""
    return {(i, j): OptimizerArc(duration, cost, walk, mode)
            for i in range(n) for j in range(n) if i != j}


def solve(nodes, arcs, **over):
    kwargs = dict(
        start_min=DAY_START, end_min=DAY_END, budget_inr=None,
        max_walk_m=5000, requirements=[], mode="balanced", time_limit_s=5.0,
    )
    kwargs.update(over)
    return optimize(nodes, arcs, **kwargs)


# --- the model works at all ----------------------------------------------

def test_single_candidate_is_visited():
    """The smallest instance. Origin plus one 60-minute cafe in a 5-hour
    window must produce exactly one stop."""
    nodes = [origin(), node("Cafe A", "cafe", score=0.9)]
    r = solve(nodes, full_arcs(2))
    assert r.is_solution
    assert len(r.stops) == 1
    assert r.stops[0].name == "Cafe A"


def test_higher_score_wins_between_two_equal_options():
    """Identical except score. The better one must be chosen."""
    nodes = [origin(),
             node("Poor", "cafe", score=0.1),
             node("Great", "cafe", score=0.9)]
    r = solve(nodes, full_arcs(3),
              requirements=[InterestRequirement("cafe", 1, False)])
    assert r.is_solution
    assert [s.name for s in r.stops] == ["Great"]


def test_optional_nodes_are_actually_optional():
    """PITFALL 2. Without self-loop literals in AddCircuit, the solver is
    forced to visit every node and this returns 4 stops or INFEASIBLE."""
    nodes = [origin()] + [node(f"P{i}", "cafe", score=0.5) for i in range(4)]
    r = solve(nodes, full_arcs(5),
              requirements=[InterestRequirement("cafe", 1, False)])
    assert r.is_solution
    assert len(r.stops) == 1, f"expected 1 stop, got {len(r.stops)}"


def test_time_window_is_respected():
    """PITFALL 1. Without OnlyEnforceIf on time propagation, unused arcs
    constrain time and nothing is ever feasible."""
    nodes = [origin()] + [node(f"P{i}", "museum", score=0.8, visit=90)
                          for i in range(5)]
    r = solve(nodes, full_arcs(6),
              requirements=[InterestRequirement("museum", 5, False)])
    assert r.is_solution
    # 5 hours available; 90 min visits plus 15 min travel = 105 min each
    assert len(r.stops) <= 3
    assert r.stops[-1].depart_min <= DAY_END


def test_scores_are_not_truncated_to_zero():
    """PITFALL 3. CP-SAT is integer-only. An unscaled float score silently
    becomes 0 and the optimizer picks arbitrarily."""
    nodes = [origin(),
             node("Tiny", "cafe", score=0.001),
             node("Small", "cafe", score=0.004)]
    r = solve(nodes, full_arcs(3),
              requirements=[InterestRequirement("cafe", 1, False)])
    assert r.is_solution
    assert r.stops[0].name == "Small", "small score differences must still rank"


# --- hard constraints -----------------------------------------------------

def test_budget_excludes_the_expensive_option():
    nodes = [origin(),
             node("Cheap", "cafe", score=0.5, cost=100),
             node("Expensive", "cafe", score=0.9, cost=5000)]
    r = solve(nodes, full_arcs(3), budget_inr=500,
              requirements=[InterestRequirement("cafe", 1, False)])
    assert r.is_solution
    assert r.stops[0].name == "Cheap"
    assert r.total_cost_inr <= 500


def test_total_cost_never_exceeds_budget():
    nodes = [origin()] + [node(f"P{i}", "cafe", score=0.8, cost=300)
                          for i in range(6)]
    r = solve(nodes, full_arcs(7), budget_inr=700,
              requirements=[InterestRequirement("cafe", 6, False)])
    assert r.is_solution
    assert r.total_cost_inr <= 700


def test_opening_hours_force_a_specific_order():
    """A place open only in the morning must come before one open only in
    the evening, whatever the scores say."""
    nodes = [
        origin(),
        node("Evening", "bar", score=0.9,
             visit=60, open_min=18 * 60, close_min=23 * 60),
        node("Afternoon", "museum", score=0.5,
             visit=60, open_min=10 * 60, close_min=17 * 60),
    ]
    r = solve(nodes, full_arcs(3), requirements=[
        InterestRequirement("bar", 1, True),
        InterestRequirement("museum", 1, True),
    ])
    assert r.is_solution
    names = [s.name for s in r.stops]
    if len(names) == 2:
        assert names == ["Afternoon", "Evening"]


def test_closed_venue_is_not_scheduled():
    nodes = [origin(),
             node("Closed", "museum", score=0.9,
                  open_min=6 * 60, close_min=12 * 60)]
    r = solve(nodes, full_arcs(2))
    assert r.is_solution
    assert len(r.stops) == 0, "a venue closed all afternoon must not be picked"


def test_low_confidence_hours_are_not_hard_filtered():
    """NQ-014: 91% of POIs have category-default hours at confidence 0.3.
    Enforcing those as hard windows would empty every itinerary."""
    nodes = [origin(),
             node("Guessed hours", "cafe", score=0.9,
                  open_min=6 * 60, close_min=12 * 60, conf=0.3)]
    r = solve(nodes, full_arcs(2))
    assert r.is_solution
    assert len(r.stops) == 1, "low-confidence hours must be soft"


def test_walking_cap_is_enforced():
    nodes = [origin()] + [node(f"P{i}", "cafe", score=0.8) for i in range(4)]
    arcs = full_arcs(5, walk=800, mode="walking")
    r = solve(nodes, arcs, max_walk_m=1000,
              requirements=[InterestRequirement("cafe", 4, False)])
    assert r.is_solution
    assert r.total_walk_m <= 1000
    assert len(r.stops) <= 1, "800m arcs against a 1000m cap allow at most one"


# --- interests ------------------------------------------------------------

def test_interest_count_is_a_ceiling():
    nodes = [origin()] + [node(f"C{i}", "cafe", score=0.9) for i in range(5)]
    r = solve(nodes, full_arcs(6),
              requirements=[InterestRequirement("cafe", 2, False)])
    assert r.is_solution
    assert sum(1 for s in r.stops if s.category == "cafe") <= 2


def test_must_outranks_a_higher_scoring_alternative():
    """MUST satisfaction is weighted an order of magnitude above score, so
    no combination of preferences can outbid it."""
    nodes = [origin(),
             node("Great cafe", "cafe", score=1.0),
             node("Dull temple", "temple", score=0.1)]
    r = solve(nodes, full_arcs(3), requirements=[
        InterestRequirement("temple", 1, True),
        InterestRequirement("cafe", 1, False),
    ])
    assert r.is_solution
    assert "Dull temple" in [s.name for s in r.stops]


def test_unsatisfiable_must_is_reported_not_hidden():
    """An over-constrained instance returns the best partial itinerary with
    the shortfall named, rather than a bare INFEASIBLE."""
    nodes = [origin(), node("Only one", "museum", score=0.8, visit=90)]
    r = solve(nodes, full_arcs(2),
              requirements=[InterestRequirement("museum", 3, True)])
    assert r.is_solution
    assert r.unsatisfied_must
    assert "museum" in r.unsatisfied_must[0]


# --- modes ----------------------------------------------------------------

def test_quick_mode_shortens_visits():
    nodes = [origin(), node("Museum", "museum", score=0.8, visit=90)]
    q = solve(nodes, full_arcs(2), mode="quick")
    rx = solve(nodes, full_arcs(2), mode="relaxed")
    assert q.stops[0].visit_minutes < rx.stops[0].visit_minutes


def test_modes_produce_different_itineraries():
    """Three modes are three objective weight sets, not three prompts."""
    nodes = [origin()] + [node(f"P{i}", "cafe", score=0.5 + i * 0.05, visit=50)
                          for i in range(8)]
    arcs = full_arcs(9, duration=20)
    results = {m: solve(nodes, arcs, mode=m,
                        requirements=[InterestRequirement("cafe", 8, False)])
               for m in ("balanced", "quick", "relaxed")}
    counts = {m: len(r.stops) for m, r in results.items()}
    assert len(set(counts.values())) > 1, f"all modes identical: {counts}"


# --- determinism and shape -------------------------------------------------

def test_same_input_gives_the_same_itinerary():
    """Fixed seed. Reproducibility is required for plan_snapshots to mean
    anything."""
    nodes = [origin()] + [node(f"P{i}", "cafe", score=0.4 + i * 0.07)
                          for i in range(6)]
    arcs = full_arcs(7)
    reqs = [InterestRequirement("cafe", 3, False)]
    a = solve(nodes, arcs, requirements=reqs)
    b = solve(nodes, arcs, requirements=reqs)
    assert [s.name for s in a.stops] == [s.name for s in b.stops]


def test_timeline_is_monotonic_and_inside_the_window():
    nodes = [origin()] + [node(f"P{i}", "cafe", score=0.7, visit=40)
                          for i in range(4)]
    r = solve(nodes, full_arcs(5),
              requirements=[InterestRequirement("cafe", 4, False)])
    assert r.is_solution
    prev_depart = DAY_START
    for s in r.stops:
        assert s.arrive_min >= prev_depart
        assert s.depart_min >= s.arrive_min
        assert DAY_START <= s.arrive_min <= DAY_END
        prev_depart = s.depart_min


def test_stops_are_sequentially_numbered_without_duplicates():
    nodes = [origin()] + [node(f"P{i}", "cafe", score=0.7) for i in range(4)]
    r = solve(nodes, full_arcs(5),
              requirements=[InterestRequirement("cafe", 3, False)])
    assert [s.seq for s in r.stops] == list(range(1, len(r.stops) + 1))
    assert len({s.node_index for s in r.stops}) == len(r.stops)


def test_empty_candidate_set_returns_infeasible_not_a_crash():
    r = solve([origin()], {})
    assert r.status == OptimizerStatus.INFEASIBLE


def test_result_serializes_for_persistence():
    nodes = [origin(), node("Cafe", "cafe", score=0.8, poi_id=42)]
    d = solve(nodes, full_arcs(2)).to_dict()
    assert d["status"] in ("optimal", "feasible")
    assert d["optimizer"] == "cpsat"
    assert "solve_ms" in d
    if d["stops"]:
        assert d["stops"][0]["poi_id"] == 42
