"""Tests for NQ-021 TripSpec and semantic validation."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.schemas.tripspec import (  # noqa: E402
    TRIPSPEC_VERSION,
    Category,
    PlanningMode,
    Priority,
    TransportMode,
    TripSpec,
    migrate_tripspec,
)
from app.services.planning.validators.semantic import (  # noqa: E402
    Severity,
    validate_semantics,
)

TODAY = date(2026, 9, 4)
ORIGIN = {"lat": 12.9784, "lon": 77.6408, "name": "Indiranagar"}


def spec(**over) -> TripSpec:
    base = dict(
        origin=ORIGIN, date="2026-09-05",
        start_time_local="15:00", end_time_local="20:00",
        budget_inr=1500,
        interests=[{"category": "restaurant", "priority": "must"}],
    )
    base.update(over)
    return TripSpec(**base)


# --- tier 1: schema ------------------------------------------------------

def test_minimal_valid_spec():
    s = spec()
    assert s.version == TRIPSPEC_VERSION
    assert s.mode == PlanningMode.BALANCED
    assert TransportMode.WALKING in s.transport


def test_derived_properties():
    s = spec(start_time_local="09:30", end_time_local="17:45")
    assert s.start_minute == 570
    assert s.end_minute == 1065
    assert s.window_minutes == 495


def test_end_before_start_rejected():
    with pytest.raises(ValidationError, match="after start_time"):
        spec(start_time_local="18:00", end_time_local="10:00")


def test_window_under_an_hour_rejected():
    with pytest.raises(ValidationError, match="at least 60 minutes"):
        spec(start_time_local="15:00", end_time_local="15:30")


def test_window_over_sixteen_hours_rejected():
    with pytest.raises(ValidationError, match="16 hours"):
        spec(start_time_local="05:00", end_time_local="23:00")


def test_malformed_time_rejected():
    with pytest.raises(ValidationError):
        spec(start_time_local="3pm")


def test_out_of_range_time_rejected():
    with pytest.raises(ValidationError):
        spec(start_time_local="25:00")


@pytest.mark.parametrize("lat,lon", [
    (13.3702, 77.6835),   # Nandi Hills - would have failed the draft bbox
    (12.5, 77.5),
    (13.7, 78.8),
])
def test_widened_bbox_accepts_regional_points(lat, lon):
    """The guard catches hallucinated coordinates in another country, not
    trips outside the city centre. Nandi Hills at 13.37 must be valid."""
    spec(origin={"lat": lat, "lon": lon})


@pytest.mark.parametrize("lat,lon", [
    (28.6139, 77.2090),   # Delhi
    (0.0, 0.0),
    (11.0, 77.5),
])
def test_bbox_rejects_points_outside_the_region(lat, lon):
    with pytest.raises(ValidationError):
        spec(origin={"lat": lat, "lon": lon})


def test_category_enum_is_closed():
    """An open category field is how a model invents categories."""
    with pytest.raises(ValidationError):
        spec(interests=[{"category": "rooftop_hookah_lounge"}])


def test_at_least_one_interest_required():
    with pytest.raises(ValidationError):
        spec(interests=[])


def test_category_both_wanted_and_avoided_rejected():
    with pytest.raises(ValidationError, match="both requested and excluded"):
        spec(interests=[{"category": "bar"}],
             constraints={"avoid_categories": ["bar"]})


def test_walking_only_needs_walking_budget():
    with pytest.raises(ValidationError, match="max_walking_km"):
        spec(transport=["walking"], constraints={"max_walking_km": 0.5})


def test_max_stops_below_must_count_rejected():
    with pytest.raises(ValidationError, match="marked MUST"):
        spec(interests=[{"category": "restaurant", "count": 3, "priority": "must"}],
             constraints={"max_stops": 2})


def test_free_text_interests_are_bounded():
    with pytest.raises(ValidationError):
        spec(free_text_interests=["x"] * 11)


def test_must_interests_and_stop_count():
    s = spec(interests=[
        {"category": "restaurant", "count": 2, "priority": "must"},
        {"category": "park", "priority": "nice_to_have"},
    ])
    assert len(s.must_interests) == 1
    assert s.total_requested_stops == 3


# --- versioning ----------------------------------------------------------

def test_migration_accepts_current_version():
    raw = spec().model_dump(mode="json")
    assert migrate_tripspec(raw).version == TRIPSPEC_VERSION


def test_migration_rejects_unknown_version():
    raw = spec().model_dump(mode="json")
    raw["version"] = "0.9"
    with pytest.raises(ValueError, match="no migration path"):
        migrate_tripspec(raw)


def test_version_bump_requires_a_migration_branch():
    """Guard against silently unreadable stored specs. If TRIPSPEC_VERSION
    changes, migrate_tripspec must gain a branch for the old value."""
    assert TRIPSPEC_VERSION == "1.0", (
        "TRIPSPEC_VERSION changed - add a migration branch in "
        "migrate_tripspec and update this test")


# --- tier 2: semantics ---------------------------------------------------

def test_past_date_is_an_error():
    r = validate_semantics(spec(date="2020-01-01"), today=TODAY)
    assert not r.is_valid
    assert any(i.code == "DATE_IN_PAST" for i in r.errors)


def test_budget_below_floor_is_an_error():
    r = validate_semantics(spec(budget_inr=10, party_size=4), today=TODAY)
    assert any(i.code == "BUDGET_TOO_LOW" for i in r.errors)


def test_no_walking_is_a_warning_not_an_error():
    r = validate_semantics(spec(transport=["auto"]), today=TODAY)
    assert r.is_valid
    assert any(i.code == "NO_WALKING" for i in r.warnings)


def test_outdoor_after_dark_warns():
    r = validate_semantics(
        spec(start_time_local="19:30", end_time_local="22:00",
             interests=[{"category": "park", "priority": "must"}]),
        today=TODAY)
    assert any(i.code == "OUTDOOR_AFTER_DARK" for i in r.warnings)


def test_duplicate_interest_is_an_error():
    r = validate_semantics(
        spec(interests=[{"category": "cafe"}, {"category": "cafe"}]),
        today=TODAY)
    assert any(i.code == "DUPLICATE_INTEREST" for i in r.errors)


def test_diet_without_food_warns():
    r = validate_semantics(
        spec(interests=[{"category": "park"}],
             constraints={"vegetarian": True}),
        today=TODAY)
    assert any(i.code == "DIET_WITHOUT_FOOD" for i in r.warnings)


def test_clean_spec_produces_no_errors():
    r = validate_semantics(spec(), today=TODAY)
    assert r.is_valid
    assert r.to_dict()["valid"] is True


def test_issues_carry_a_field_for_the_ui():
    """NQ-026 highlights a specific form field; NQ-031 asks about it."""
    r = validate_semantics(spec(budget_inr=5), today=TODAY)
    for issue in r.errors:
        assert issue.field
        assert issue.code