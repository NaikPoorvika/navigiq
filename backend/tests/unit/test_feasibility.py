"""Tests for NQ-022 feasibility pre-check and relaxation ladder."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.schemas.tripspec import Priority, TripSpec  # noqa: E402
from app.services.planning.feasibility.engine import (  # noqa: E402
    CandidateSummary,
    FeasibilityEngine,
    Violation,
    apply_relaxation,
)

ORIGIN = {"lat": 12.9784, "lon": 77.6408, "name": "Indiranagar"}

DEFAULTS = {
    "restaurant": 75, "cafe": 45, "historical": 60, "sunset": 45,
    "park": 60, "museum": 90, "bar": 90, "street_food": 30,
}


def spec(**over) -> TripSpec:
    base = dict(
        origin=ORIGIN, date="2026-09-05",
        start_time_local="15:00", end_time_local="20:00",
        budget_inr=1500,
        interests=[{"category": "restaurant", "priority": "must"}],
    )
    base.update(over)
    return TripSpec(**base)


def cand(category, count=50, min_cost=200, visit=None, nearest=1.0,
         open_in_window=True, all_outdoor=False) -> CandidateSummary:
    return CandidateSummary(
        category=category, count=count, min_cost_inr=min_cost,
        min_visit_minutes=visit or DEFAULTS.get(category, 45),
        nearest_km=nearest, any_open_in_window=open_in_window,
        all_outdoor=all_outdoor,
    )


@pytest.fixture
def engine():
    return FeasibilityEngine(category_defaults=DEFAULTS)


# --- feasible cases ------------------------------------------------------

def test_reasonable_trip_is_feasible(engine):
    r = engine.check(spec(), {"restaurant": cand("restaurant")})
    assert r.feasible
    assert r.violated == []
    assert r.suggested_relaxations == []


def test_bounds_are_always_reported(engine):
    """The agent needs these numbers to explain itself, feasible or not."""
    r = engine.check(spec(), {"restaurant": cand("restaurant")})
    for key in ("available_minutes", "required_visit_minutes",
                "min_travel_minutes", "total_required_minutes"):
        assert key in r.bounds


# --- the case this engine exists for -------------------------------------

def test_ten_places_three_hours_three_hundred_rupees(engine):
    """'10 places in 3 hours for Rs 300' must fail instantly, before the
    optimizer spends 10 seconds discovering the same thing."""
    s = spec(
        start_time_local="15:00", end_time_local="18:00",
        budget_inr=300,
        interests=[
            {"category": "restaurant", "count": 3, "priority": "must"},
            {"category": "museum", "count": 3, "priority": "must"},
            {"category": "historical", "count": 4, "priority": "must"},
        ],
    )
    r = engine.check(s, {
        "restaurant": cand("restaurant", min_cost=400),
        "museum": cand("museum", min_cost=100),
        "historical": cand("historical", min_cost=50),
    })
    assert not r.feasible
    assert Violation.TIME in r.violated
    assert Violation.BUDGET in r.violated
    assert r.bounds["total_required_minutes"] > r.bounds["available_minutes"]
    assert r.suggested_relaxations


# --- individual violations ------------------------------------------------

def test_time_infeasible_when_visits_exceed_window(engine):
    s = spec(start_time_local="15:00", end_time_local="16:30",
             interests=[{"category": "museum", "count": 2, "priority": "must"}])
    r = engine.check(s, {"museum": cand("museum")})
    assert Violation.TIME in r.violated


def test_budget_infeasible(engine):
    s = spec(budget_inr=100,
             interests=[{"category": "restaurant", "priority": "must"}])
    r = engine.check(s, {"restaurant": cand("restaurant", min_cost=800)})
    assert Violation.BUDGET in r.violated
    assert r.bounds["min_cost_inr"] > r.bounds["budget_inr"]


def test_budget_scales_with_party_size(engine):
    s = spec(budget_inr=500, party_size=4,
             interests=[{"category": "restaurant", "priority": "must"}])
    r = engine.check(s, {"restaurant": cand("restaurant", min_cost=200)})
    assert Violation.BUDGET in r.violated, "4 x 200 = 800 exceeds 500"


def test_reach_infeasible_when_no_candidates(engine):
    s = spec(interests=[{"category": "museum", "priority": "must"}])
    r = engine.check(s, {"museum": cand("museum", count=0)})
    assert Violation.REACH in r.violated
    assert "museum" in r.bounds["categories_with_no_candidates"]


def test_reach_infeasible_when_category_absent_entirely(engine):
    s = spec(interests=[{"category": "nightlife", "priority": "must"}])
    r = engine.check(s, {})
    assert Violation.REACH in r.violated


def test_hours_infeasible_when_nothing_open(engine):
    s = spec(interests=[{"category": "museum", "priority": "must"}])
    r = engine.check(s, {"museum": cand("museum", open_in_window=False)})
    assert Violation.HOURS in r.violated


def test_weather_infeasible_for_outdoor_must_in_heavy_rain(engine):
    s = spec(interests=[{"category": "park", "priority": "must"}])
    r = engine.check(s, {"park": cand("park", all_outdoor=True)},
                     heavy_rain_expected=True)
    assert Violation.WEATHER in r.violated


def test_rain_does_not_block_indoor_categories(engine):
    s = spec(interests=[{"category": "museum", "priority": "must"}])
    r = engine.check(s, {"museum": cand("museum", all_outdoor=False)},
                     heavy_rain_expected=True)
    assert Violation.WEATHER not in r.violated


def test_only_must_interests_count_toward_bounds(engine):
    """A NICE_TO_HAVE must not make a trip infeasible - it gets dropped."""
    s = spec(
        start_time_local="15:00", end_time_local="17:00",
        interests=[
            {"category": "cafe", "priority": "must"},
            {"category": "museum", "count": 3, "priority": "nice_to_have"},
        ],
    )
    r = engine.check(s, {"cafe": cand("cafe"), "museum": cand("museum")})
    assert r.feasible, "3 optional museums should not block a 2-hour cafe trip"


# --- the relaxation ladder ------------------------------------------------

def test_ladder_is_ordered_by_step(engine):
    s = spec(start_time_local="15:00", end_time_local="16:30", budget_inr=50,
             interests=[
                 {"category": "restaurant", "count": 2, "priority": "must"},
                 {"category": "cafe", "count": 2, "priority": "should"},
                 {"category": "park", "priority": "nice_to_have"},
             ])
    r = engine.check(s, {"restaurant": cand("restaurant", min_cost=500),
                         "cafe": cand("cafe"), "park": cand("park")})
    steps = [x.step for x in r.suggested_relaxations]
    assert steps == sorted(steps)


def test_dropping_optional_interests_is_automatic(engine):
    s = spec(start_time_local="15:00", end_time_local="16:00",
             interests=[
                 {"category": "museum", "count": 2, "priority": "must"},
                 {"category": "park", "priority": "nice_to_have"},
             ])
    r = engine.check(s, {"museum": cand("museum"), "park": cand("park")})
    drop_nice = [x for x in r.suggested_relaxations if x.action == "drop_nice"]
    assert drop_nice and not drop_nice[0].requires_confirmation


def test_reducing_must_counts_always_requires_confirmation(engine):
    """THE rule. A MUST is what the user insisted on - the system must not
    quietly decide they meant something less."""
    s = spec(start_time_local="15:00", end_time_local="16:00",
             interests=[{"category": "museum", "count": 3, "priority": "must"}])
    r = engine.check(s, {"museum": cand("museum")})
    for x in r.suggested_relaxations:
        if x.action in ("reduce_must_counts", "drop_must"):
            assert x.requires_confirmation, f"{x.action} must be confirmed"


def test_extending_time_requires_confirmation(engine):
    s = spec(start_time_local="15:00", end_time_local="16:00",
             interests=[{"category": "museum", "count": 2, "priority": "must"}])
    r = engine.check(s, {"museum": cand("museum")})
    ext = [x for x in r.suggested_relaxations if x.action == "extend_end"]
    if ext:
        assert ext[0].requires_confirmation


def test_extension_never_pushes_past_ten_pm(engine):
    s = spec(start_time_local="19:00", end_time_local="21:30",
             interests=[{"category": "museum", "count": 4, "priority": "must"}])
    r = engine.check(s, {"museum": cand("museum")})
    for x in r.suggested_relaxations:
        if x.action == "extend_end":
            assert x.payload["new_end_minute"] <= 22 * 60


# --- apply_relaxation is pure --------------------------------------------

def test_apply_drop_nice_removes_only_optional(engine):
    """drop_nice must remove NICE_TO_HAVE and leave MUST and SHOULD intact."""
    s = spec(
        start_time_local="15:00", end_time_local="16:00",
        interests=[
            {"category": "museum", "count": 2, "priority": "must"},
            {"category": "cafe", "priority": "should"},
            {"category": "park", "priority": "nice_to_have"},
        ],
    )
    r = engine.check(s, {"museum": cand("museum"), "cafe": cand("cafe"),
                         "park": cand("park")})
    drop = next(x for x in r.suggested_relaxations if x.action == "drop_nice")
    out = apply_relaxation(s, drop)
    assert {i.category.value for i in out.interests} == {"museum", "cafe"}

def test_apply_never_mutates_the_original(engine):
    s = spec(interests=[
        {"category": "restaurant", "count": 3, "priority": "must"}])
    before = s.model_dump_json()
    r = engine.check(spec(start_time_local="15:00", end_time_local="16:00",
                          interests=[{"category": "museum", "count": 3,
                                      "priority": "must"}]),
                     {"museum": cand("museum")})
    red = next((x for x in r.suggested_relaxations
                if x.action == "reduce_must_counts"), None)
    if red:
        apply_relaxation(s, red)
    assert s.model_dump_json() == before


def test_apply_extend_end_produces_valid_spec(engine):
    s = spec(start_time_local="15:00", end_time_local="16:30")
    r = engine.check(
        spec(start_time_local="15:00", end_time_local="16:30",
             interests=[{"category": "museum", "count": 2, "priority": "must"}]),
        {"museum": cand("museum")})
    ext = next((x for x in r.suggested_relaxations
                if x.action == "extend_end"), None)
    if ext:
        out = apply_relaxation(s, ext)
        assert out.end_minute > s.end_minute
        assert out.window_minutes <= 16 * 60


def test_report_serializes_for_the_api(engine):
    r = engine.check(
        spec(start_time_local="15:00", end_time_local="16:00", budget_inr=50,
             interests=[{"category": "museum", "count": 3, "priority": "must"}]),
        {"museum": cand("museum", min_cost=500)})
    d = r.to_dict()
    assert d["feasible"] is False
    assert isinstance(d["violated"], list)
    assert all("requires_confirmation" in x for x in d["suggested_relaxations"])