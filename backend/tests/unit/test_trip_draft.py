"""Schema-level tests for the TripDraft contract (pre-NQ-029 hardening).

Pure Pydantic tests, no database. draft_builder.py's own behaviour (place
resolution, date-phrase resolution, clarification generation) is tested in
test_draft_builder.py; this file covers only what TripDraft itself accepts
or rejects, independent of any resolver.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.schemas.trip_draft import (  # noqa: E402
    FREE_TEXT_MAX_ITEMS,
    FREE_TEXT_MAX_LENGTH,
    DraftInterest,
    PlaceRef,
    TripDraft,
)


# --- Change #1: strict HH:MM time validation -------------------------------

@pytest.mark.parametrize("value", [
    "09:00", "13:30", "18:45", "23:59", "00:00",
])
def test_valid_hhmm_times_are_accepted(value):
    d = TripDraft(start_time_local=value, end_time_local=value)
    assert d.start_time_local == value
    assert d.end_time_local == value


@pytest.mark.parametrize("value", [
    "9:00", "9 AM", "09 AM", "25:00", "12:60", "abc", "morning", "evening",
    "9:0", "09:0", "9:00 ", " 09:00", "09:00:00", "",
])
def test_malformed_times_are_rejected(value):
    with pytest.raises(ValidationError):
        TripDraft(start_time_local=value)
    with pytest.raises(ValidationError):
        TripDraft(end_time_local=value)


def test_missing_time_stays_none_not_invented():
    """The schema must not default a missing time - draft_builder owns that."""
    d = TripDraft()
    assert d.start_time_local is None
    assert d.end_time_local is None


def test_time_validation_applies_independently_to_both_fields():
    with pytest.raises(ValidationError):
        TripDraft(start_time_local="09:00", end_time_local="9:00")


# --- Change #3: free_text_interests bounds ----------------------------------

def test_free_text_interests_empty_list_is_valid():
    assert TripDraft(free_text_interests=[]).free_text_interests == []


def test_free_text_interests_within_bounds_is_valid():
    items = ["rooftop hookah lounge", "live jazz venue"]
    assert TripDraft(free_text_interests=items).free_text_interests == items


def test_free_text_interests_at_the_item_limit_is_valid():
    items = [f"concept {i}" for i in range(FREE_TEXT_MAX_ITEMS)]
    assert len(TripDraft(free_text_interests=items).free_text_interests) == \
        FREE_TEXT_MAX_ITEMS


def test_free_text_interests_over_the_item_limit_is_rejected():
    items = [f"concept {i}" for i in range(FREE_TEXT_MAX_ITEMS + 1)]
    with pytest.raises(ValidationError):
        TripDraft(free_text_interests=items)


def test_free_text_interests_at_the_length_limit_is_valid():
    phrase = "x" * FREE_TEXT_MAX_LENGTH
    assert TripDraft(free_text_interests=[phrase]).free_text_interests == [phrase]


def test_free_text_interests_over_the_length_limit_is_rejected():
    with pytest.raises(ValidationError):
        TripDraft(free_text_interests=["x" * (FREE_TEXT_MAX_LENGTH + 1)])


def test_free_text_interests_combines_with_normal_category_interests():
    """The overflow bucket coexists with closed-enum interests; it is not
    a replacement for them."""
    d = TripDraft(
        interests=[{"category": "cafe"}, {"category": "park"}],
        free_text_interests=["rooftop hookah lounge"],
    )
    assert [i.category.value for i in d.interests] == ["cafe", "park"]
    assert d.free_text_interests == ["rooftop hookah lounge"]


def test_free_text_interests_bounds_match_tripspecs_own_bounds():
    """Documented as a deliberate match in the module docstring - pin it."""
    from app.schemas.tripspec import TripSpec
    assert FREE_TEXT_MAX_ITEMS == 10
    assert FREE_TEXT_MAX_LENGTH == 80
    # TripSpec enforces the same numbers via its own validator (tripspec.py
    # _bounded_free_text) - checked here by behaviour, since TripSpec does
    # not expose its bound as named constants.
    with pytest.raises(ValidationError):
        TripSpec(
            origin={"lat": 12.9784, "lon": 77.6408}, date="2026-10-03",
            start_time_local="10:00", end_time_local="18:00",
            interests=[{"category": "cafe"}],
            free_text_interests=["x"] * 11,
        )


# --- Category enum stays closed (unchanged, regression-pinned) -------------

def test_draft_interest_rejects_invented_category():
    with pytest.raises(ValidationError):
        DraftInterest(category="rooftop_hookah_lounge")


def test_trip_draft_rejects_invented_category_in_interests():
    with pytest.raises(ValidationError):
        TripDraft(interests=[{"category": "rooftop_hookah_lounge"}])


# --- unknown fields are ignored everywhere (unchanged, regression-pinned) --

def test_unknown_top_level_fields_are_ignored():
    d = TripDraft(origin={"name": "Jayanagar"}, rating=5, secret="x")
    dumped = d.model_dump()
    assert "rating" not in dumped
    assert "secret" not in dumped


def test_unknown_fields_on_place_ref_are_ignored():
    ref = PlaceRef(name="Jayanagar", extra_field="x")
    assert ref.model_dump() == {"name": "Jayanagar"}


def test_unknown_fields_on_draft_interest_are_ignored():
    interest = DraftInterest(category="cafe", rating=5)
    assert "rating" not in interest.model_dump()


# --- Change #9: coordinate safety (unchanged, regression-pinned) -----------

def test_place_ref_has_no_coordinate_fields_at_all():
    """Not merely optional - the type itself carries no lat/lon."""
    assert "lat" not in PlaceRef.model_fields
    assert "lon" not in PlaceRef.model_fields


def test_hallucinated_coordinates_never_reach_the_model_instance():
    d = TripDraft(origin={"name": "Koramangala", "lat": 99.9, "lon": 99.9},
                  destination={"name": "Indiranagar", "lat": -1.0, "lon": -1.0})
    assert not hasattr(d.origin, "lat")
    assert not hasattr(d.destination, "lat")
    assert d.origin.model_dump() == {"name": "Koramangala"}
    assert d.destination.model_dump() == {"name": "Indiranagar"}


def test_hallucinated_coordinates_do_not_survive_a_dict_round_trip():
    """The property a downstream consumer actually depends on: serialising
    the validated instance can never leak coordinates back out."""
    d = TripDraft(origin={"name": "Koramangala", "lat": 99.9, "lon": 99.9})
    dumped = d.model_dump(mode="json")
    assert "lat" not in str(dumped)
    assert "lon" not in str(dumped)


# --- Change #10: model_json_schema() suitability for constrained decoding --

def test_json_schema_has_no_required_fields():
    """Everything optional - missing fields become clarifying questions,
    not a schema-level rejection."""
    schema = TripDraft.model_json_schema()
    assert schema.get("required") in (None, [])


def test_json_schema_exposes_place_name_only():
    schema = TripDraft.model_json_schema()
    assert "origin" in schema["properties"]
    place_ref_schema = schema["$defs"]["PlaceRef"]
    assert "lat" not in str(place_ref_schema)
    assert "lon" not in str(place_ref_schema)
    assert place_ref_schema["properties"].keys() == {"name"}


def test_json_schema_represents_the_category_enum():
    schema = TripDraft.model_json_schema()
    from app.schemas.tripspec import Category
    assert set(schema["$defs"]["Category"]["enum"]) == {c.value for c in Category}


def test_json_schema_represents_the_time_pattern():
    schema = TripDraft.model_json_schema()
    import json
    assert "([01]" in json.dumps(schema["properties"]["start_time_local"])
    assert "([01]" in json.dumps(schema["properties"]["end_time_local"])


def test_json_schema_represents_free_text_bounds():
    schema = TripDraft.model_json_schema()
    field = schema["properties"]["free_text_interests"]
    assert field["maxItems"] == FREE_TEXT_MAX_ITEMS
    assert field["items"]["maxLength"] == FREE_TEXT_MAX_LENGTH


def test_json_schema_has_zero_coordinate_fields_anywhere():
    import json
    schema_text = json.dumps(TripDraft.model_json_schema())
    assert '"lat"' not in schema_text
    assert '"lon"' not in schema_text


def test_json_schema_has_no_tripspec_only_fields():
    """version/source/confidence are TripSpec metadata the LLM must never
    set - they must not exist on the draft schema at all."""
    schema = TripDraft.model_json_schema()
    for leaked in ("version", "source", "confidence"):
        assert leaked not in schema["properties"], leaked


def test_json_schema_is_a_plain_object_schema_usable_by_the_llm_gateway():
    schema = TripDraft.model_json_schema()
    assert schema["type"] == "object"
    assert isinstance(schema["properties"], dict)
    assert len(schema["properties"]) > 0
