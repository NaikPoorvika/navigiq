"""Tests for the NQ-029 eval scorer.

A scorer nobody tests is a scorer that reports whatever you hoped for. The
cases here are the ones where a lenient bug would silently flatter the
model: a failed extraction scoring as neutral, leakage being measured on the
cleaned draft instead of the raw response, and an empty denominator being
printed as 0%.

    python -m pytest ai/evals/nq029 -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "backend"))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq_user:navigiq_password@localhost:5433/navigiq",
)

from cases import CASES, CASE_CLASSES, DRAFT_FIELDS, Case  # noqa: E402
from score import _rate, score_case, summarise  # noqa: E402


class _Case:
    def __init__(self, expect=None, forbid=()):
        self.id = "t"
        self.case_class = "test"
        self.text = "t"
        self.expect = expect or {}
        self.forbid = forbid


def _score(case, draft=None, raw=None, reason=None):
    return score_case(case, draft=draft, raw_text=raw,
                      failure_reason=reason, latency_ms=1.0)


# --- failing must never score better than answering ------------------------

def test_a_failed_extraction_scores_zero_for_every_expected_field():
    case = _Case(expect={"origin": "Koramangala", "party_size": 2})
    result = _score(case, draft=None, reason="invalid_json")
    assert result.total == 2
    assert result.correct == 0


def test_failed_cases_still_count_in_the_accuracy_denominator():
    good = _score(_Case(expect={"party_size": 2}), draft={"party_size": 2})
    bad = _score(_Case(expect={"party_size": 2}), reason="invalid_json")
    summary = summarise([good, bad])
    assert summary["critical_field_accuracy"] == 0.5
    assert summary["schema_validity_rate"] == 0.5


# --- raw-layer measurement ---------------------------------------------------

def test_coordinate_leakage_is_detected_even_though_the_draft_is_clean():
    """TripDraft drops the lat, so the validated draft looks perfect. The
    model still emitted a coordinate, and that is what is reported."""
    raw = '{"origin": {"name": "Koramangala", "lat": 12.9352}}'
    result = _score(_Case(), draft={"origin": {"name": "Koramangala"}}, raw=raw)
    assert result.coordinate_leak is True


def test_a_coordinate_hidden_in_a_string_is_still_leakage():
    raw = '{"origin": {"name": "12.9352, 77.6245"}}'
    assert _score(_Case(), draft={}, raw=raw).coordinate_leak is True


def test_ordinary_numbers_are_not_mistaken_for_coordinates():
    raw = '{"budget_inr": 2500, "party_size": 4, "max_walking_km": 3.5}'
    assert _score(_Case(), draft={}, raw=raw).coordinate_leak is False


def test_malformed_times_are_counted_from_the_raw_response():
    raw = '{"start_time_local": "9am"}'
    result = _score(_Case(), draft=None, raw=raw, reason="schema_invalid")
    assert result.had_time_in_raw is True
    assert result.malformed_times


def test_a_well_formed_time_is_not_counted_as_malformed():
    result = _score(_Case(), draft={}, raw='{"start_time_local": "09:00"}')
    assert result.had_time_in_raw is True
    assert result.malformed_times == []


def test_an_unsupported_date_phrase_is_detected():
    result = _score(_Case(), draft={}, raw='{"date_phrase": "next week"}')
    assert result.unsupported_date_phrase == "next week"


def test_a_supported_date_phrase_is_not_flagged():
    result = _score(_Case(), draft={}, raw='{"date_phrase": "day after tomorrow"}')
    assert result.unsupported_date_phrase is None


# --- field comparison rules ---------------------------------------------------

def test_a_more_specific_place_name_still_matches():
    case = _Case(expect={"origin": "Koramangala"})
    draft = {"origin": {"name": "Koramangala, Bengaluru"}}
    assert _score(case, draft=draft).correct == 1


def test_a_different_place_does_not_match():
    case = _Case(expect={"origin": "Koramangala"})
    assert _score(case, draft={"origin": {"name": "Jayanagar"}}).correct == 0


def test_date_phrases_are_compared_by_what_they_resolve_to():
    case = _Case(expect={"date_phrase": "Saturday"})
    assert _score(case, draft={"date_phrase": "this saturday"}).correct == 1


def test_a_different_day_does_not_match():
    case = _Case(expect={"date_phrase": "Saturday"})
    assert _score(case, draft={"date_phrase": "sunday"}).correct == 0


def test_an_extra_interest_is_a_miss_not_a_free_pass():
    case = _Case(expect={"interests": {"cafe"}})
    draft = {"interests": [{"category": "cafe"}, {"category": "bar"}]}
    assert _score(case, draft=draft).correct == 0


def test_hallucination_is_any_forbidden_field_being_populated():
    case = _Case(forbid=("budget_inr", "party_size"))
    result = _score(case, draft={"budget_inr": 5000, "party_size": None})
    assert result.hallucinated == ["budget_inr"]


def test_an_empty_list_is_not_a_populated_field():
    case = _Case(forbid=("interests", "transport"))
    assert _score(case, draft={"interests": [], "transport": []}).hallucinated == []


# --- reporting honesty ---------------------------------------------------------

def test_an_unmeasured_rate_is_none_not_zero():
    """0% malformed times out of zero times seen is not a good result, it
    is no result."""
    assert _rate(0, 0) is None
    assert _rate(0, 4) == 0.0


def test_a_run_with_no_times_reports_the_time_rate_as_unmeasured():
    summary = summarise([_score(_Case(), draft={}, raw="{}")])
    assert summary["malformed_time_rate"] is None
    assert summary["responses_with_a_time"] == 0


# --- the dataset itself ---------------------------------------------------------

def test_all_twenty_required_case_classes_are_covered():
    required = [
        "simple domestic trip", "origin + destination", "missing origin",
        "missing destination", "explicit date", "relative date", "time",
        "budget", "party size", "multiple interests", "unmappable interest",
        "transport", "vegetarian preference", "walking constraint",
        "noisy natural-language request", "incomplete request",
        "ambiguous wording", "multilingual / Indian-English phrasing",
        "coordinate-injection attempt", "irrelevant extra information",
    ]
    missing = [c for c in required if c not in CASE_CLASSES]
    assert not missing, missing


def test_case_ids_are_unique():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_every_case_asserts_something(case):
    """A case with no expectation must at least forbid the whole schema -
    that is what makes 'hi, can you help me plan something?' a real test."""
    assert case.expect or len(case.forbid) == len(DRAFT_FIELDS)


# --- the computed hallucination rule ------------------------------------------

def test_every_unexpected_field_is_forbidden_by_default():
    """The bug this rule replaced: a hand-written forbid list that simply
    forgot `transport`, so inventing one scored free."""
    case = Case(id="x", case_class="x", text="x", expect={"origin": "K"})
    assert "transport" in case.forbid
    assert "mode" in case.forbid
    assert "vegetarian" in case.forbid
    assert "origin" not in case.forbid


def test_allow_is_the_only_way_a_field_escapes_the_rule():
    case = Case(id="x", case_class="x", text="x", expect={"origin": "K"},
                allow=("transport",))
    assert "transport" not in case.forbid
    assert "mode" in case.forbid


def test_place_any_exempts_both_place_fields():
    case = Case(id="x", case_class="x", text="x", expect={"place_any": "MG Road"})
    assert "origin" not in case.forbid
    assert "destination" not in case.forbid


def test_the_rule_covers_every_schema_field():
    """If TripDraft gains a field, it must become measurable here without
    anyone remembering to add it to a list."""
    from app.schemas.trip_draft import TripDraft
    assert set(DRAFT_FIELDS) == set(TripDraft.model_fields)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_expected_date_phrases_are_ones_the_resolver_accepts(case):
    """The dataset must not demand a phrase the deterministic layer cannot
    use - that would make the model wrong for being right."""
    from datetime import date

    from app.services.planning.draft_builder import resolve_date_phrase
    phrase = case.expect.get("date_phrase")
    if phrase is None:
        return
    assert resolve_date_phrase(phrase, date(2026, 9, 21)) is not None, phrase
