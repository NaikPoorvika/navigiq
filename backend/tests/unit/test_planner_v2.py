"""Planner v2 (sections 41-47, 92-96): optimizer features with known optima,
greedy fallback, feasibility with relaxations, resolution of partial specs,
closed modification operations, and validator mutation tests."""
from __future__ import annotations

import copy
from datetime import date, datetime

import pytest

from app.geo.regions import destination_point_geodesic, geo_config
from app.nlu.timeparse import IST
from app.schemas.tripspec import TripSpec
from app.services.planning.feasibility.engine import StopBound, Violation, check
from app.services.planning.modify import (
    CurrentStop, Modification, ModificationError, apply_modifications,
)
from app.services.planning.optimizer.greedy import greedy_schedule
from app.services.planning.optimizer.model import OptimizerArc, OptimizerNode, optimize
from app.services.planning.resolve import resolve_for_planning
from app.services.planning.validator.itinerary import (
    PlannedStop, Rule, TripRules, unsupported_numbers, validate,
)
from app.services.plans import compare_itineraries
from tests.unit.test_recommendation import poi

CFG = geo_config()
START, END = 10 * 60, 18 * 60


def node(name, cat="park", score=0.5, visit=60, cost=0, o=0, c=1440, conf=0.3, must=False,
         meal=False, pid=None):
    return OptimizerNode(pid, name, cat, score, visit, cost, o, c, conf, meal, must)


def start():
    return node("Start", "origin", 0, 0, 0)


def arcs_for(n, buffer=15, dist=1.0, far=None):
    out = {}
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if i == 0 or j == 0:
                out[(i, j)] = OptimizerArc(0, 0, 0, "start", 0.0)
            elif far and ((i, j) in far or (j, i) in far):
                continue
            else:
                out[(i, j)] = OptimizerArc(buffer, 0, 0, "transition", dist)
    return out


def solve(nodes, arcs, **kw):
    base = dict(start_min=START, end_min=END, budget_inr=None, max_walk_m=10 ** 9,
                requirements=[], mode="balanced", visit_multiplier=1.0, min_visit_minutes=1,
                time_limit_s=5.0)
    base.update(kw)
    return optimize(nodes, arcs, **base)


# --- optimizer v2 ------------------------------------------------------------------------------

def test_must_visit_is_hard_even_when_low_scoring():
    nodes = [start(), node("A", score=0.9), node("B", score=0.9), node("Must", score=0.01,
                                                                          must=True)]
    r = solve(nodes, arcs_for(4), max_stops=2)
    assert "Must" in [s.name for s in r.stops]


def test_min_and_max_stops():
    nodes = [start()] + [node(f"P{i}", score=0.5, visit=30) for i in range(6)]
    assert len(solve(nodes, arcs_for(7), max_stops=2).stops) == 2
    assert len(solve(nodes, arcs_for(7), max_stops=5, min_stops=4).stops) >= 4


def test_transition_buffer_separates_stops():
    nodes = [start()] + [node(f"P{i}", visit=60) for i in range(3)]
    r = solve(nodes, arcs_for(4, buffer=20), max_stops=3)
    for a, b in zip(r.stops, r.stops[1:]):
        assert b.arrive_min - a.depart_min >= 20


def test_category_caps():
    nodes = [start()] + [node(f"H{i}", cat="hill", score=0.9) for i in range(3)] + [
        node("C", cat="cafe", score=0.2)]
    r = solve(nodes, arcs_for(5), max_stops=4, category_caps={"hill": 1})
    assert sum(1 for s in r.stops if s.category == "hill") == 1


def test_missing_arc_means_never_consecutive():
    nodes = [start(), node("A", score=0.9), node("B", score=0.9)]
    r = solve(nodes, arcs_for(3, far={(1, 2)}), max_stops=2)
    assert len(r.stops) == 1


def test_compactness_prefers_short_hops_when_scores_tie():
    nodes = [start(), node("A"), node("Near"), node("Far")]
    arcs = arcs_for(4)
    for (i, j), a in list(arcs.items()):
        if {i, j} == {1, 3} or {i, j} == {2, 3}:
            arcs[(i, j)] = OptimizerArc(15, 0, 0, "transition", 10.0)
    r = solve(nodes, arcs, max_stops=2, compactness_weight=200)
    assert {s.name for s in r.stops} == {"A", "Near"}


def test_early_start_tie_breaker_removes_idle_start():
    nodes = [start(), node("A", visit=60)]
    r = solve(nodes, arcs_for(2), max_stops=1, early_start_weight=20)
    assert r.stops[0].arrive_min == START


def test_reliable_hours_are_hard():
    nodes = [start(), node("Closed", o=19 * 60, c=22 * 60, conf=0.9, score=0.99)]
    assert solve(nodes, arcs_for(2)).stops == []


def test_deterministic_with_fixed_seed():
    nodes = [start()] + [node(f"P{i}", score=0.4 + 0.05 * i, visit=45) for i in range(8)]
    a = solve(nodes, arcs_for(9), max_stops=5)
    b = solve(nodes, arcs_for(9), max_stops=5)
    assert [s.name for s in a.stops] == [s.name for s in b.stops]


# --- greedy fallback ------------------------------------------------------------------------------

def test_greedy_respects_budget_hours_window_and_caps():
    nodes = [start(), node("Pricey", cost=900, score=0.9), node("Cheap", cost=100, score=0.5),
             node("Morning", o=6 * 60, c=9 * 60, conf=0.9, score=0.8),
             node("Hill1", cat="hill", score=0.7), node("Hill2", cat="hill", score=0.7)]
    r = greedy_schedule(nodes, arcs_for(6), start_min=START, end_min=END, budget_inr=500,
                        max_stops=5, category_caps={"hill": 1}, min_visit_minutes=1)
    names = [s.name for s in r.stops]
    assert "Pricey" not in names and "Morning" not in names
    assert sum(1 for s in r.stops if s.category == "hill") == 1
    assert r.stops[-1].depart_min <= END


def test_greedy_includes_must_or_reports_infeasible():
    nodes = [start(), node("Must", must=True, visit=600)]
    r = greedy_schedule(nodes, arcs_for(2), start_min=START, end_min=END, budget_inr=None,
                        max_stops=3, min_visit_minutes=1)
    assert r.status.value == "infeasible"


# --- feasibility ------------------------------------------------------------------------------------

def spec(**kw):
    base = dict(date=date(2026, 9, 22), start_time="10:00", end_time="18:00")
    base.update(kw)
    return TripSpec(**base)


def test_ten_places_in_two_hours_for_100_is_infeasible_with_relaxations():
    s = spec(start_time="10:00", end_time="12:00", desired_stop_count=8, budget_total=100)
    rep = check(s, must=[], candidate_count=50, min_visit_any=30, min_cost_pp_any=50)
    assert not rep.feasible
    assert {Violation.STOPS, Violation.BUDGET} <= set(rep.violated) or Violation.TIME in rep.violated
    codes = {r.code for r in rep.relaxations}
    assert {"REDUCE_STOPS", "INCREASE_TIME", "INCREASE_BUDGET"} <= codes
    assert rep.message.startswith("That combination isn't feasible")
    for r in rep.relaxations:
        assert "op" in r.operation


def test_closed_must_include_is_reported():
    rep = check(spec(), must=[StopBound("Museum", 60, 50, False)], candidate_count=10)
    assert Violation.MUST_CLOSED in rep.violated


def test_feasible_request_passes():
    assert check(spec(), must=[], candidate_count=30).feasible


def test_no_candidates():
    rep = check(spec(interests=["cafe"]), must=[], candidate_count=0)
    assert Violation.NO_CANDIDATES in rep.violated


# --- resolve partial specs ----------------------------------------------------------------------

@pytest.mark.parametrize("now_h,spec_kw,exp_date_offset,exp_start,exp_end", [
    (9, {}, 0, "10:00", "18:00"),
    (13, {}, 0, "13:30", "19:30"),          # 30-minute lead time, quarter-hour aligned
    (17, {}, 1, "10:00", "18:00"),
    (9, {"start_time": "15:00"}, 0, "15:00", "21:00"),
    (9, {"end_time": "20:00"}, 0, "14:00", "20:00"),
])
def test_resolution_defaults_are_recorded(now_h, spec_kw, exp_date_offset, exp_start, exp_end):
    now = datetime(2026, 9, 21, now_h, 0, tzinfo=IST)
    r = resolve_for_planning(TripSpec(**spec_kw), now)
    assert (r.spec.date - now.date()).days == exp_date_offset
    assert (r.spec.start_time, r.spec.end_time) == (exp_start, exp_end)
    assert r.assumptions


def test_resolution_keeps_explicit_values():
    now = datetime(2026, 9, 21, 9, 0, tzinfo=IST)
    s = TripSpec(date=date(2026, 9, 25), start_time="11:00", end_time="20:00", party_size=2)
    r = resolve_for_planning(s, now)
    assert r.spec.date == date(2026, 9, 25) and r.spec.start_time == "11:00"
    assert r.assumptions == []


# --- modifications ----------------------------------------------------------------------------------

STOPS = [CurrentStop(1, 11, "Garden", "garden"), CurrentStop(2, 12, "Museum", "museum"),
         CurrentStop(3, 13, "Cafe", "cafe")]


def mods(*ops):
    return [Modification(**o) for o in ops]


def test_remove_stop_locks_the_rest_and_excludes_target():
    a = apply_modifications(spec(), STOPS, mods({"op": "remove_stop", "target_seq": 2}))
    assert 12 in a.spec.exclude_poi_ids
    assert set(a.directives.locked_ids) == {11, 13}
    assert a.directives.max_stops_override == 2


def test_replace_stop_with_category():
    a = apply_modifications(spec(), STOPS, mods({"op": "replace_stop", "target_seq": 2,
                                                 "category": "gallery"}))
    assert a.directives.replacement_category == "gallery"
    assert a.directives.max_stops_override == 3 and 12 in a.spec.exclude_poi_ids


def test_add_poi_locks_all():
    a = apply_modifications(spec(), STOPS, mods({"op": "add_poi", "poi_id": 99}))
    assert set(a.directives.locked_ids) == {11, 12, 13, 99}


def test_day_level_changes_prefer_current_stops():
    a = apply_modifications(spec(), STOPS, mods({"op": "set_budget", "amount": 700}))
    assert a.spec.budget_total == 700 and a.directives.preferred_ids == [11, 12, 13]
    assert not a.directives.locked_ids


@pytest.mark.parametrize("op,check_fn", [
    ({"op": "set_start_time", "time": "12:00"}, lambda s: s.start_time == "12:00"),
    ({"op": "set_end_time", "time": "20:00"}, lambda s: s.end_time == "20:00"),
    ({"op": "shift_time", "minutes": 180}, lambda s: (s.start_time, s.end_time) == ("13:00", "21:00")),
    ({"op": "set_stop_count", "count": 2}, lambda s: s.desired_stop_count == 2),
    ({"op": "set_pace", "pace": "relaxed"}, lambda s: s.pace.value == "relaxed"),
    ({"op": "avoid_category", "category": "museum"}, lambda s: "museum" in s.avoid_interests
     and 12 in s.exclude_poi_ids),
    ({"op": "prefer_category", "category": "lake"}, lambda s: "lake" in s.interests),
    ({"op": "add_interest", "interest": "romantic"}, lambda s: "romantic" in s.interests),
    ({"op": "set_indoor_preference", "preference": "indoor"}, lambda s: s.indoor_preference == "indoor"),
    ({"op": "set_transition_buffer", "minutes": 30}, lambda s: s.transition_buffer_minutes == 30),
    ({"op": "add_meal", "meal": "dinner"}, lambda s: "dinner" in s.meal_preferences
     and "restaurant" in s.interests),
    ({"op": "avoid_area", "area": "Testnagar"}, lambda s: "Testnagar" in s.avoid_areas),
])
def test_every_operation_applies(op, check_fn):
    a = apply_modifications(spec(interests=["museum"]), STOPS, mods(op))
    assert check_fn(a.spec)


def test_input_spec_is_never_mutated():
    s = spec()
    before = s.model_dump()
    apply_modifications(s, STOPS, mods({"op": "set_budget", "amount": 5}))
    assert s.model_dump() == before


@pytest.mark.parametrize("bad", [
    {"op": "remove_stop"}, {"op": "set_budget"}, {"op": "set_start_time", "time": "25:00"},
    {"op": "avoid_category", "category": "spaceport"}, {"op": "teleport"},
    {"op": "remove_stop", "target_seq": 1, "sql": "DROP TABLE pois"},
])
def test_invalid_operations_are_rejected(bad):
    with pytest.raises(Exception):
        Modification(**bad)


def test_unknown_target_is_an_error():
    with pytest.raises(ModificationError):
        apply_modifications(spec(), STOPS, mods({"op": "remove_stop", "target_seq": 9}))


def test_compare_itineraries():
    def it(stops, cost):
        return {"stops": [{"poi": {"id": i, "name": n}, "arrive": "10:00", "depart": "11:00"}
                          for i, n in stops], "summary": {"estimated_cost": {"typical": cost},
                                                          "span_minutes": 60},
                "start_time": "10:00", "end_time": "18:00"}
    c = compare_itineraries(it([(1, "A"), (2, "B")], 500), it([(1, "A"), (3, "C")], 300))
    assert c["added"] == ["C"] and c["removed"] == ["B"] and c["estimated_cost"]["delta"] == -200


# --- validator mutation tests ---------------------------------------------------------------------

def _facts():
    def near(b, km):
        return destination_point_geodesic(CFG.center_lat, CFG.center_lon, b, km)
    facts = {}
    for pid, (b, km, cat, cost, hours, visit) in {
            1: (0, 2.0, "garden", (0, 30, 60), [(360, 1140)], (45, 60, 120)),
            2: (5, 2.5, "museum", (50, 50, 50), [(600, 1020)], (45, 60, 150)),
            3: (10, 3.0, "cafe", (150, 300, 600), [(480, 1320)], (30, 60, 120))}.items():
        lat, lon = near(b, km)
        p = poi(pid=pid, name=f"P{pid}", category=cat, cost=cost, hours=hours, visit=visit,
                dist=km, io="outdoor" if cat == "garden" else "indoor")
        p.lat, p.lon = lat, lon
        facts[pid] = p
    return facts


def _rules(**kw):
    base = dict(start_min=START, end_min=END, transition_buffer_min=15, party_size=1,
                budget_total=1000, envelope_radius_km=90.0, center_lat=CFG.center_lat,
                center_lon=CFG.center_lon, exploration_radius_km=90.0, max_hop_km=12.0,
                must_include_ids={2}, exclude_ids={99}, avoid_categories={"mall"})
    base.update(kw)
    return TripRules(**base)


def _good():
    return [PlannedStop(1, 1, 600, 660), PlannedStop(2, 2, 675, 735), PlannedStop(3, 3, 750, 810)]


def test_valid_itinerary_passes():
    rep = validate(_good(), _rules(), _facts())
    assert rep.valid, rep.to_dict()
    assert rep.recomputed_cost_inr == 380


def _far_facts():
    f = _facts()
    lat, lon = destination_point_geodesic(CFG.center_lat, CFG.center_lon, 180, 95.0)
    f[3].lat, f[3].lon, f[3].distance_from_center_km = lat, lon, 95.0
    return f


def _hop_facts():
    f = _facts()
    lat, lon = destination_point_geodesic(CFG.center_lat, CFG.center_lon, 180, 30.0)
    f[3].lat, f[3].lon, f[3].distance_from_center_km = lat, lon, 30.0
    return f


MUTATIONS = [
    ("duplicate stop", lambda s, r, f: (s + [PlannedStop(4, 1, 825, 885)], r, f), Rule.DUPLICATE),
    ("closed stop", lambda s, r, f: ([PlannedStop(1, 1, 600, 660), PlannedStop(2, 2, 1030, 1075)],
                                     r, f), Rule.HOURS),
    ("budget overflow", lambda s, r, f: (s, _rules(budget_total=200), f), Rule.BUDGET),
    ("schedule overlap", lambda s, r, f: ([PlannedStop(1, 1, 600, 680), PlannedStop(2, 2, 670, 730)],
                                          r, f), Rule.OVERLAP),
    ("missing must-include", lambda s, r, f: ([s[0], s[2]], r, f), Rule.MUST),
    ("forbidden stop", lambda s, r, f: (s, _rules(exclude_ids={3}), f), Rule.EXCLUDED),
    ("forbidden category", lambda s, r, f: (s, _rules(avoid_categories={"cafe"}), f),
     Rule.EXCLUDED),
    ("out-of-region stop", lambda s, r, f: (s, r, _far_facts()), Rule.SCOPE),
    ("transition violation", lambda s, r, f: ([PlannedStop(1, 1, 600, 660),
                                               PlannedStop(2, 2, 665, 725),
                                               PlannedStop(3, 3, 740, 800)], r, f), Rule.BUFFER),
    ("invalid duration", lambda s, r, f: ([PlannedStop(1, 1, 600, 610), s[1], s[2]], r, f),
     Rule.DURATION),
    ("outside window", lambda s, r, f: ([s[0], s[1], PlannedStop(3, 3, 1060, 1120)], r, f),
     Rule.WINDOW),
    ("unknown poi", lambda s, r, f: (s + [PlannedStop(4, 404, 825, 885)], r, f), Rule.EXISTS),
    ("incoherent hop", lambda s, r, f: (s, r, _hop_facts()), Rule.COHERENCE),
    ("dietary violation", lambda s, r, f: (s, _rules(dietary=["vegetarian"]), f), Rule.REQUIREMENT),
]


@pytest.mark.parametrize("name,mutate,rule", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_single_fault_is_detected_by_the_expected_rule(name, mutate, rule):
    stops, rules, facts = mutate(copy.deepcopy(_good()), _rules(), _facts())
    rep = validate(stops, rules, facts)
    assert not rep.valid
    assert rule.value in rep.rules_failed(), rep.to_dict()


def test_unsupported_numbers_in_explanation():
    assert unsupported_numbers("Arrive at 10:00, costs ₹300", {"10:00", "10", "00", "300"}) == []
    assert unsupported_numbers("It takes 25 minutes by cab", {"10"}) == ["25 minutes"]
    rep = validate(_good(), _rules(), _facts(), explanation="Only 45 km away",
                   fact_numbers={"10"})
    assert Rule.CLAIM.value in rep.rules_failed()


def test_low_confidence_hours_are_not_enforced():
    f = _facts()
    f[2].hours_confidence = 0.3
    rep = validate([PlannedStop(1, 1, 600, 660), PlannedStop(2, 2, 1030, 1075)], _rules(), f)
    assert Rule.HOURS.value not in rep.rules_failed()
