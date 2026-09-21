"""Property-based planner tests (section 94).

For randomly generated planning problems, EVERY schedule returned by CP-SAT
or the greedy fallback must satisfy:
    cost <= budget; all POIs exist; no duplicates; no overlapping visits;
    must-includes present; exclusions absent; inside the requested window;
    transition buffer respected; reliable hours respected
- checked twice: directly, and by the independent validator.
"""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st

from app.geo.regions import destination_point_geodesic, geo_config
from app.geo.distance import haversine_km
from app.services.planning.optimizer.greedy import greedy_schedule
from app.services.planning.optimizer.model import OptimizerArc, OptimizerNode, optimize
from app.services.planning.validator.itinerary import PlannedStop, TripRules, validate
from tests.unit.test_recommendation import poi

CFG = geo_config()
CATS = ["park", "cafe", "museum", "lake", "temple", "gallery"]


@st.composite
def problems(draw):
    n = draw(st.integers(min_value=1, max_value=7))
    start = draw(st.sampled_from([8 * 60, 10 * 60, 14 * 60]))
    window = draw(st.integers(min_value=120, max_value=600))
    buffer = draw(st.sampled_from([0, 10, 15, 30]))
    budget = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=2000)))
    pois = []
    for i in range(n):
        visit = draw(st.integers(min_value=20, max_value=150))
        cost = draw(st.sampled_from([0, 50, 150, 300, 800]))
        reliable = draw(st.booleans())
        o = draw(st.integers(min_value=6 * 60, max_value=14 * 60)) if reliable else 0
        c = min(1440, o + draw(st.integers(min_value=60, max_value=600))) if reliable else 1440
        bearing = draw(st.floats(min_value=0, max_value=359))
        km = draw(st.floats(min_value=0.5, max_value=8.0))
        pois.append(dict(visit=visit, cost=cost, o=o, c=c, reliable=reliable,
                         score=draw(st.floats(min_value=0.05, max_value=1.0)),
                         cat=draw(st.sampled_from(CATS)), bearing=bearing, km=km))
    must = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=n - 1)))
    return dict(n=n, start=start, end=min(start + window, 23 * 60), buffer=buffer,
                budget=budget, pois=pois, must=must)


def build(p):
    nodes = [OptimizerNode(None, "Start", "origin", 0, 0, 0, p["start"], p["end"])]
    facts = {}
    coords = {}
    for i, q in enumerate(p["pois"], start=1):
        lat, lon = destination_point_geodesic(CFG.center_lat, CFG.center_lon, q["bearing"], q["km"])
        coords[i] = (lat, lon)
        nodes.append(OptimizerNode(i, f"P{i}", q["cat"], q["score"], q["visit"], q["cost"],
                                   q["o"], q["c"], 0.9 if q["reliable"] else 0.3,
                                   False, p["must"] == i - 1))
        rec = poi(pid=i, category=q["cat"], cost=(q["cost"], q["cost"], q["cost"]),
                  visit=(q["visit"], q["visit"], q["visit"]), dist=q["km"],
                  hours=[(q["o"], q["c"])] if q["reliable"] else None)
        rec.lat, rec.lon = lat, lon
        if not q["reliable"]:
            rec.hours_confidence = 0.3
        facts[i] = rec
    arcs = {}
    for i in range(len(nodes)):
        for j in range(len(nodes)):
            if i == j:
                continue
            if i == 0 or j == 0:
                arcs[(i, j)] = OptimizerArc(0, 0, 0, "start", 0.0)
            else:
                d = haversine_km(*coords[i], *coords[j])
                arcs[(i, j)] = OptimizerArc(p["buffer"], 0, 0, "transition", round(d, 3))
    rules = TripRules(start_min=p["start"], end_min=p["end"], transition_buffer_min=p["buffer"],
                      party_size=1, budget_total=p["budget"], envelope_radius_km=90.0,
                      center_lat=CFG.center_lat, center_lon=CFG.center_lon,
                      exploration_radius_km=90.0, max_hop_km=20.0,
                      must_include_ids={p["must"] + 1} if p["must"] is not None else set(),
                      exclude_ids={999})
    return nodes, arcs, facts, rules


def check_invariants(result, p, facts, rules):
    stops = result.stops
    ids = [s.poi_id for s in stops]
    assert len(ids) == len(set(ids)), "duplicate stop"
    assert all(i in facts for i in ids), "unknown POI"
    assert 999 not in ids, "excluded POI"
    if p["budget"] is not None:
        assert sum(facts[i].cost[1] for i in ids) <= p["budget"], "budget exceeded"
    prev = None
    for s in stops:
        assert p["start"] <= s.arrive_min <= s.depart_min <= p["end"], "outside window"
        if prev is not None:
            assert s.arrive_min - prev.depart_min >= p["buffer"], "buffer / overlap"
        q = p["pois"][s.poi_id - 1]
        if q["reliable"]:
            assert q["o"] <= s.arrive_min and s.depart_min <= q["c"], "closed venue"
        prev = s
    if p["must"] is not None and stops:
        assert p["must"] + 1 in ids, "must-include missing"
    report = validate([PlannedStop(s.seq, s.poi_id, s.arrive_min, s.depart_min) for s in stops],
                      rules, facts)
    if p["must"] is None or p["must"] + 1 in ids:
        assert report.valid, report.to_dict()


@given(problems())
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_cpsat_solutions_satisfy_all_invariants(p):
    nodes, arcs, facts, rules = build(p)
    r = optimize(nodes, arcs, start_min=p["start"], end_min=p["end"], budget_inr=p["budget"],
                 max_walk_m=10 ** 9, requirements=[], mode="balanced", visit_multiplier=1.0,
                 min_visit_minutes=1, max_stops=5, time_limit_s=3.0)
    if r.is_solution:
        check_invariants(r, p, facts, rules)


@given(problems())
@settings(max_examples=150, deadline=None)
def test_greedy_solutions_satisfy_all_invariants(p):
    nodes, arcs, facts, rules = build(p)
    r = greedy_schedule(nodes, arcs, start_min=p["start"], end_min=p["end"],
                        budget_inr=p["budget"], max_stops=5, min_visit_minutes=1)
    if r.is_solution:
        check_invariants(r, p, facts, rules)
