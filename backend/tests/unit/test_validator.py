"""Tests for NQ-024 itinerary validator.

MUTATION TESTS are the point. Take a valid itinerary, inject exactly one
fault, and assert that the corresponding rule fires AND the other eight stay
quiet. A validator that never fails is not a validator; one that fires on
everything is just noise.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.planning.validator.itinerary import (  # noqa: E402
    Rule,
    StopFacts,
    TripFacts,
    validate,
)

START = 15 * 60      # 15:00
END = 20 * 60        # 20:00


def stop(seq, name, category, arrive, depart, *, poi_id=None,
         lat=12.97, lon=77.60, cost=200, open_min=9 * 60, close_min=22 * 60,
         conf=1.0, indoor=True, travel=600.0, opt_travel=600.0,
         walk=100.0, leg_cost=50):
    return StopFacts(
        seq=seq, poi_id=poi_id if poi_id is not None else seq * 10,
        name=name, category=category, lat=lat, lon=lon,
        arrive_min=arrive, depart_min=depart, cost_inr=cost,
        open_min=open_min, close_min=close_min, hours_confidence=conf,
        indoor=indoor, travel_s_from_prev=travel,
        optimizer_travel_s_from_prev=opt_travel,
        walk_m_from_prev=walk, leg_cost_inr=leg_cost,
    )


@pytest.fixture
def good_stops():
    """A valid three-stop afternoon: cafe, historical site, sunset spot."""
    return [
        stop(1, "Third Wave", "cafe", 15 * 60 + 10, 15 * 60 + 55),
        stop(2, "Bangalore Palace", "historical", 16 * 60 + 20, 17 * 60 + 20,
             cost=250),
        stop(3, "Sankey Tank", "sunset", 17 * 60 + 50, 18 * 60 + 35,
             cost=0, indoor=False),
    ]


@pytest.fixture
def good_trip():
    return TripFacts(
        start_min=START, end_min=END, date=date(2026, 9, 5),
        budget_inr=1500, max_walk_m=3000,
        must_interests={"cafe": 1, "historical": 1},
        excluded_categories=set(), excluded_poi_ids=set(),
        heavy_rain_expected=False,
    )


def only_rule_fired(report, rule: Rule) -> bool:
    """The injected fault fires its rule and nothing else."""
    fired = {f.rule for f in report.findings}
    return fired == {rule}


# --- baseline -------------------------------------------------------------

def test_a_valid_itinerary_passes(good_stops, good_trip):
    r = validate(good_stops, good_trip)
    assert r.valid, [f.message for f in r.findings]
    assert r.findings == []


def test_all_nine_rules_are_always_run(good_stops, good_trip):
    """Silent rule-skipping would make a green report meaningless."""
    r = validate(good_stops, good_trip)
    assert len(r.rules_run) == 9
    assert set(r.rules_run) == {rule.value for rule in Rule}


# --- the nine mutations ---------------------------------------------------

def test_mutation_travel_time_drift(good_stops, good_trip):
    """Re-fetched travel time disagrees with the optimizer's. This is the
    rule that catches the optimizer working from stale matrix data."""
    bad = list(good_stops)
    bad[1] = replace(bad[1], travel_s_from_prev=1800.0,
                     optimizer_travel_s_from_prev=600.0)
    r = validate(bad, good_trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.TRAVEL_TIME)


def test_mutation_venue_closed(good_stops, good_trip):
    bad = list(good_stops)
    bad[1] = replace(bad[1], close_min=16 * 60)      # closes before departure
    r = validate(bad, good_trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.OPENING_HOURS)


def test_mutation_budget_exceeded(good_stops, good_trip):
    bad = list(good_stops)
    bad[0] = replace(bad[0], cost_inr=5000)
    r = validate(bad, good_trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.BUDGET)


def test_mutation_timeline_goes_backwards(good_stops, good_trip):
    bad = list(good_stops)
    bad[2] = replace(bad[2], arrive_min=15 * 60)     # before stop 2 ends
    r = validate(bad, good_trip)
    assert not r.valid
    assert Rule.TIMELINE in {f.rule for f in r.findings}


def test_mutation_walking_exceeded(good_stops, good_trip):
    bad = list(good_stops)
    bad[1] = replace(bad[1], walk_m_from_prev=4000.0)
    r = validate(bad, good_trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.WALKING)


def test_mutation_must_interest_missing(good_stops, good_trip):
    bad = [s for s in good_stops if s.category != "historical"]
    r = validate(bad, good_trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.MUST_INTERESTS)


def test_mutation_excluded_category_present(good_stops, good_trip):
    trip = replace(good_trip, excluded_categories={"sunset"})
    r = validate(good_stops, trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.EXCLUSIONS)


def test_mutation_out_of_bounds(good_stops, good_trip):
    bad = list(good_stops)
    bad[0] = replace(bad[0], lat=28.6139, lon=77.2090)    # Delhi
    r = validate(bad, good_trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.BOUNDS)


def test_mutation_outdoor_stop_in_heavy_rain(good_stops, good_trip):
    trip = replace(good_trip, heavy_rain_expected=True)
    r = validate(good_stops, trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.WEATHER)


# --- rules that must NOT fire ---------------------------------------------

def test_low_confidence_hours_do_not_fail_validation(good_stops, good_trip):
    """NQ-014: 91% of POIs carry category-default hours at confidence 0.3.
    Validating hard against those would fail almost every itinerary."""
    bad = list(good_stops)
    bad[1] = replace(bad[1], close_min=16 * 60, hours_confidence=0.3)
    r = validate(bad, good_trip)
    assert r.valid, "low-confidence hours must not block validation"


def test_small_travel_drift_is_tolerated(good_stops, good_trip):
    """OSRM caching and rounding mean an exact match is not expected."""
    bad = list(good_stops)
    bad[1] = replace(bad[1], travel_s_from_prev=630.0,
                     optimizer_travel_s_from_prev=600.0)
    assert validate(bad, good_trip).valid


def test_declared_relaxation_excuses_a_missing_must(good_stops, good_trip):
    """If the user agreed to drop a category, its absence is not a fault."""
    bad = [s for s in good_stops if s.category != "historical"]
    r = validate(bad, good_trip,
                 declared_relaxations=["dropped historical on user request"])
    assert r.valid


def test_duplicate_poi_is_caught(good_stops, good_trip):
    bad = list(good_stops) + [
        stop(4, "Third Wave", "cafe", 18 * 60 + 50, 19 * 60 + 30, poi_id=10)]
    r = validate(bad, good_trip)
    assert not r.valid
    assert Rule.EXCLUSIONS in {f.rule for f in r.findings}


def test_single_long_walk_is_caught_even_within_total(good_stops, good_trip):
    """2 km in one leg is unreasonable even if the trip total allows it."""
    bad = list(good_stops)
    bad[1] = replace(bad[1], walk_m_from_prev=2000.0)
    trip = replace(good_trip, max_walk_m=10000)
    r = validate(bad, trip)
    assert not r.valid
    assert Rule.WALKING in {f.rule for f in r.findings}


def test_stop_outside_trip_window_is_caught(good_stops, good_trip):
    bad = list(good_stops)
    bad[2] = replace(bad[2], arrive_min=21 * 60, depart_min=21 * 60 + 45)
    r = validate(bad, good_trip)
    assert not r.valid
    assert Rule.TIMELINE in {f.rule for f in r.findings}


def test_empty_itinerary_fails_on_unsatisfied_must(good_trip):
    r = validate([], good_trip)
    assert not r.valid
    assert only_rule_fired(r, Rule.MUST_INTERESTS)


def test_report_serializes_for_persistence(good_stops, good_trip):
    """validator_report is stored on every itinerary_version."""
    bad = list(good_stops)
    bad[0] = replace(bad[0], cost_inr=9999)
    d = validate(bad, good_trip).to_dict()
    assert d["valid"] is False
    assert len(d["rules_run"]) == 9
    assert d["findings"][0]["rule"] == Rule.BUDGET.value