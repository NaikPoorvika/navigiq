"""Tests for the NQ-030 scorer, and the freeze on the held-out set.

    python -m pytest ai/evals/nq030 -q

No Ollama, no GPU. The freeze tests exist so that "we did not tune against
the held-out set" is something a reviewer can check rather than trust:
editing heldout.json or the v2 prompt breaks the build until the hash is
updated in a reviewed commit that has to say why.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend"))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq_user:navigiq_password@localhost:5433/navigiq",
)

from evaluate import load_dev, load_heldout, sha256  # noqa: E402
from scoring import (  # noqa: E402
    BENIGN, CLARIFYING, DRAFT_FIELDS, PLAN_ALTERING, classify,
    restraint_fields, score_case, summarise,
)

# Frozen 2026-09-22, before any prompt was run against the set. Changing
# either file means a new held-out set or a new prompt version (v3), never
# an edit in place - see ai/evals/nq030/README.md.
HELDOUT_SHA256 = "2d768e27b66e4d27ca88240d115b077b90b9565109475a7822bbd1352e78c3cb"
PROMPT_V2_SHA256 = "52879a64dfcb5a54ece0756f3b56b33a59d9c78467be8c6c1c044a8a26eda991"
PROMPT_V1_SHA256 = "811cff33f26e8c22a403912ba154eadb1df2704c1b277049bbc499a116798503"

PROMPTS = REPO / "backend" / "app" / "llm" / "prompts"


def _case(expected=None, allow=(), category="t"):
    return {"id": "t", "category": category, "input": "t",
            "expected": expected or {}, "allow": list(allow)}


def _score(case, draft=None, raw=None, reason=None):
    if raw is None and draft is not None:
        raw = json.dumps(draft)
    return score_case(case, draft=draft, raw_text=raw, failure_reason=reason,
                      latency_ms=1.0)


# --- the freeze ------------------------------------------------------------------

def test_heldout_set_is_frozen():
    assert sha256(HERE / "heldout.json") == HELDOUT_SHA256, (
        "heldout.json changed. A held-out set that is edited after results "
        "are seen is no longer held out - create a new set instead.")


def test_prompt_v2_is_frozen():
    assert sha256(PROMPTS / "tripdraft_extraction_v2.md") == PROMPT_V2_SHA256, (
        "v2 changed after its held-out evaluation. Create v3 instead.")


def test_prompt_v1_is_still_the_nq029_baseline():
    assert sha256(PROMPTS / "tripdraft_extraction_v1.md") == PROMPT_V1_SHA256


def _ngrams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def test_no_heldout_input_shares_a_phrase_with_the_v2_prompt():
    """Leakage guard: no 5-word sequence of any held-out input appears in
    the prompt. The concepts overlap by design (bus-like modes, vague
    budgets); the wording must not."""
    prompt = _ngrams((PROMPTS / "tripdraft_extraction_v2.md").read_text(
        encoding="utf-8"))
    leaks = {c["id"]: sorted(_ngrams(c["input"]) & prompt)
             for c in load_heldout()}
    assert not {k: v for k, v in leaks.items() if v}


def test_no_heldout_input_repeats_a_dev_input():
    dev = {c["input"].lower() for c in load_dev()}
    assert not [c["id"] for c in load_heldout() if c["input"].lower() in dev]


def test_heldout_has_the_required_shape():
    cases = load_heldout()
    assert 30 <= len(cases) <= 40
    assert len({c["id"] for c in cases}) == len(cases)
    cats = {c["category"] for c in cases}
    assert cats == {"explicit_extraction", "missing_info_restraint",
                    "ambiguous_wording", "unsupported_enum", "date_time",
                    "place_interest", "indian_english_noisy"}


@pytest.mark.parametrize("case", load_heldout(), ids=lambda c: c["id"])
def test_expected_date_phrases_resolve(case):
    """The set must never demand a phrase the resolver cannot use."""
    from datetime import date

    from app.services.planning.draft_builder import resolve_date_phrase
    phrase = case["expected"].get("date_phrase")
    if phrase:
        assert resolve_date_phrase(phrase, date(2026, 9, 21)) is not None


@pytest.mark.parametrize("case", load_heldout(), ids=lambda c: c["id"])
def test_expected_values_are_valid_tripdraft_values(case):
    from app.schemas.tripspec import Category, PlanningMode, TransportMode
    exp = case["expected"]
    for cat in exp.get("interests") or []:
        Category(cat)
    for mode in exp.get("transport") or []:
        TransportMode(mode)
    if exp.get("mode"):
        PlanningMode(exp["mode"])


# --- stated fields: correct / missing / wrong ------------------------------------

def test_expected_extraction_is_scored_correct():
    s = _score(_case({"budget_inr": 2500}), draft={"budget_inr": 2500})
    assert [c.status for c in s.stated] == ["correct"]


def test_an_absent_stated_field_is_under_extraction():
    s = _score(_case({"budget_inr": 2500}), draft={})
    assert [c.status for c in s.stated] == ["missing"]
    assert summarise([s])["under_extraction_rate"] == 1.0


def test_a_different_value_is_wrong_not_missing():
    s = _score(_case({"party_size": 3}), draft={"party_size": 4})
    assert [c.status for c in s.stated] == ["wrong"]


def test_a_wrong_stated_value_is_plan_altering():
    """bus -> auto is a substitution. NQ-029 filed it as a miss."""
    s = _score(_case({"transport": ["cab"]}), draft={"transport": ["auto"]})
    assert s.plan_altering == ["transport (wrong)"]


def test_a_failed_extraction_misses_every_stated_field():
    s = _score(_case({"origin": "X", "party_size": 2}), reason="invalid_json")
    assert [c.status for c in s.stated] == ["missing", "missing"]
    assert not s.clean


def test_place_spellings_and_supersets_match():
    case = _case({"origin": ["Koramangala", "kormangala"]})
    assert _score(case, draft={"origin": {"name": "kormangala"}}).clean
    assert _score(case, draft={"origin": {"name": "Koramangala, Bengaluru"}}).clean


def test_date_phrases_compare_by_resolved_date():
    case = _case({"date_phrase": "this Sunday"})
    assert _score(case, draft={"date_phrase": "sunday"}).clean
    assert not _score(case, draft={"date_phrase": "saturday"}).clean


def test_interests_need_the_exact_set():
    case = _case({"interests": ["cafe"]})
    assert not _score(case, draft={"interests": [{"category": "cafe"},
                                                 {"category": "bar"}]}).clean


# --- expected omission --------------------------------------------------------------

def test_an_explicit_empty_expectation_is_a_restraint_check():
    case = _case({"origin": "X", "transport": []})
    assert "transport" in restraint_fields(case["expected"], [])
    s = _score(case, draft={"origin": {"name": "X"}})
    assert s.clean
    s = _score(case, draft={"origin": {"name": "X"}, "transport": ["auto"]})
    assert s.plan_altering == ["transport"]


def test_every_unmentioned_field_is_a_restraint_check():
    fields = restraint_fields({"origin": "X"}, [])
    assert set(fields) == set(DRAFT_FIELDS) - {"origin"}


def test_allow_exempts_a_field():
    assert "interests" not in restraint_fields({"origin": "X"}, ["interests"])


def test_place_any_exempts_both_places():
    fields = restraint_fields({"place_any": "X"}, [])
    assert "origin" not in fields and "destination" not in fields


def test_scorer_fields_match_the_schema():
    from app.schemas.trip_draft import TripDraft
    assert set(DRAFT_FIELDS) == set(TripDraft.model_fields)


# --- severity classification ----------------------------------------------------------

@pytest.mark.parametrize("field,value,severity", [
    ("vegetarian", False, BENIGN),
    ("vegetarian", True, PLAN_ALTERING),
    ("mode", "balanced", BENIGN),
    ("mode", "relaxed", PLAN_ALTERING),
    ("party_size", 1, BENIGN),
    ("party_size", 2, PLAN_ALTERING),
    ("days", 1, BENIGN),
    ("max_walking_km", 3.0, BENIGN),
    ("max_walking_km", 5, PLAN_ALTERING),
    ("transport", ["auto", "walking"], BENIGN),
    ("transport", ["auto"], PLAN_ALTERING),
    ("budget_inr", 0, PLAN_ALTERING),
    ("date_phrase", "next week", CLARIFYING),
    ("date_phrase", "evening", CLARIFYING),
    ("date_phrase", "today", PLAN_ALTERING),
    ("destination", {"name": "park"}, PLAN_ALTERING),
    ("interests", [{"category": "cafe"}], PLAN_ALTERING),
    ("free_text_interests", ["outing"], BENIGN),
    ("start_time_local", "09:00", PLAN_ALTERING),
])
def test_severity_follows_draft_builder_defaults(field, value, severity):
    assert classify(field, value) == severity


def test_the_defaults_table_matches_draft_builder():
    """If draft_builder's defaults move, 'benign' must move with them."""
    from app.services.planning import draft_builder
    assert set(draft_builder.DEFAULT_TRANSPORT) == {"walking", "auto"}
    src = Path(draft_builder.__file__).read_text(encoding="utf-8")
    assert "party_size=draft.party_size or 1" in src
    assert "days=draft.days or 1" in src
    assert 'mode=draft.mode or "balanced"' in src
    assert "else 3.0" in src
    assert '"vegetarian": bool(draft.vegetarian)' in src


def test_a_benign_invention_does_not_make_a_case_unclean():
    s = _score(_case({"origin": "X"}),
               draft={"origin": {"name": "X"}, "vegetarian": False})
    assert s.unrequested and s.clean
    assert summarise([s])["plan_altering_rate"] == 0.0
    assert summarise([s])["unrequested_case_rate"] == 1.0


# --- raw-layer and reporting honesty --------------------------------------------------

def test_coordinate_leak_is_read_from_raw_output():
    s = _score(_case({"origin": "X"}), draft={"origin": {"name": "X"}},
               raw='{"origin": {"name": "X", "lat": 12.9352}}')
    assert s.coordinate_leak


def test_unsupported_date_is_read_from_raw_output():
    s = _score(_case(), draft={}, raw='{"date_phrase": "friday night"}')
    assert s.unsupported_date_phrase == "friday night"


def test_unmeasured_rates_are_none():
    summary = summarise([_score(_case(), draft={})])
    assert summary["malformed_time_rate"] is None
    assert summary["place_interest_accuracy"] is None


def test_place_interest_accuracy_catches_a_generic_destination():
    case = _case({"origin": "X", "interests": ["park"], "destination": None},
                 category="place_interest")
    good = _score(case, draft={"origin": {"name": "X"},
                               "interests": [{"category": "park"}]})
    bad = _score(case, draft={"origin": {"name": "X"},
                              "destination": {"name": "park"}})
    assert good.place_interest_correct
    assert not bad.place_interest_correct
    assert summarise([good, bad])["place_interest_accuracy"] == 0.5


def test_scoring_is_deterministic():
    case = _case({"origin": "X", "party_size": 2})
    draft = {"origin": {"name": "X"}, "party_size": 2, "mode": "quick"}
    a = summarise([_score(case, draft=draft)])
    b = summarise([_score(case, draft=draft)])
    assert a == b
