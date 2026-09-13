"""Case files and scorers.

A benchmark is only as good as its gold answers. These tests check that the
cases are internally consistent and that a perfect answer actually scores 1.0
- otherwise every model is penalised for the benchmark author's mistakes.
"""
from __future__ import annotations

import datetime as dt

import pytest

from nq027.schemas import Category, TripSpec
from nq027.tasks import (
    CRITICAL_FIELDS,
    REFERENCE_DATE,
    REFERENCE_WEEKDAY,
    TASK_IDS,
    TASK_CLASSES,
    cases_for,
    task_check_for,
    validate_case_file,
)
from nq027.validity import Judgement, Outcome


def ok(payload=None, text="") -> Judgement:
    return Judgement(outcome=Outcome.VALID, payload=payload, cleaned_text=text)


# --- structure ------------------------------------------------------------

def test_all_eight_task_classes_present():
    assert set(TASK_IDS) == {
        "intent_classify", "tripspec_extract", "tripspec_modify",
        "tool_select", "explain_itinerary", "rag_answer",
        "reroute_message", "clarify_question",
    }


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_case_files_are_well_formed(task_id):
    assert validate_case_file(task_id) == []


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_every_class_has_cases(task_id):
    assert len(cases_for(task_id)) >= 8


def test_tripspec_case_set_is_the_required_fifty():
    assert len(cases_for("tripspec_extract")) == 50


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_prompts_build_for_every_case(task_id):
    task = TASK_CLASSES[task_id]
    for case in cases_for(task_id):
        messages = task.messages_for(case, constrained=True)
        assert messages and all(m["content"] for m in messages)


def test_reference_date_matches_its_stated_weekday():
    """Relative dates in the cases resolve from this pair; a mismatch would
    silently shift every 'this Saturday' gold answer by a day."""
    parsed = dt.date.fromisoformat(REFERENCE_DATE)
    assert parsed.strftime("%A") == REFERENCE_WEEKDAY


# --- gold answers are achievable -----------------------------------------

def test_every_extract_gold_uses_real_categories():
    valid = {c.value for c in Category}
    for case in cases_for("tripspec_extract"):
        for category in case["gold"].get("categories", []):
            assert category in valid, f"{case['id']}: {category}"


def test_every_extract_gold_origin_is_in_its_gazetteer():
    for case in cases_for("tripspec_extract"):
        points = {(p["lat"], p["lon"]) for p in case["gazetteer"]}
        assert tuple(case["gold"]["origin"]) in points, case["id"]


def test_extract_golds_describe_a_constructible_tripspec():
    """The gold answer must itself be a legal TripSpec - times in order, a
    window the schema accepts, at least one interest."""
    for case in cases_for("tripspec_extract"):
        gold = case["gold"]
        spec = TripSpec.model_validate({
            "origin": {"lat": gold["origin"][0], "lon": gold["origin"][1]},
            "date": gold["date"],
            "start_time_local": gold["start_time_local"],
            "end_time_local": gold["end_time_local"],
            "interests": [{"category": c} for c in gold["categories"]],
        })
        assert spec.window_minutes >= 60, case["id"]


def test_modify_current_specs_are_valid_tripspecs():
    for case in cases_for("tripspec_modify"):
        TripSpec.model_validate(case["current_spec"])


def test_modify_gold_changes_something():
    for case in cases_for("tripspec_modify"):
        assert case["gold"]["changed"], f"{case['id']} changes nothing"


def test_modify_preserved_and_changed_do_not_overlap():
    for case in cases_for("tripspec_modify"):
        changed = set(case["gold"]["changed"])
        preserved = set(case["gold"]["preserved"])
        assert not (changed & preserved), case["id"]


def test_clarify_gold_fields_are_real_tripspec_fields():
    allowed = {"origin", "date", "start_time_local", "end_time_local",
               "interests", "budget_inr", "party_size", "transport"}
    for case in cases_for("clarify_question"):
        assert set(case["gold"]["missing_fields"]) <= allowed, case["id"]


def test_tool_select_gold_names_registry_tools():
    from nq027.schemas import ToolName
    names = {t.value for t in ToolName}
    for case in cases_for("tool_select"):
        assert case["gold"]["tool"] in names, case["id"]


# --- scorers --------------------------------------------------------------

def test_a_perfect_extraction_scores_one():
    task = TASK_CLASSES["tripspec_extract"]
    for case in cases_for("tripspec_extract"):
        gold = case["gold"]
        payload = {
            "origin": {"lat": gold["origin"][0], "lon": gold["origin"][1]},
            "date": gold["date"],
            "start_time_local": gold["start_time_local"],
            "end_time_local": gold["end_time_local"],
            "interests": [{"category": c} for c in gold["categories"]],
            "constraints": {},
        }
        for name in ("budget_inr", "party_size"):
            if name in gold:
                payload[name] = gold[name]
        if "transport" in gold:
            payload["transport"] = gold["transport"]
        if "vegetarian" in gold:
            payload["constraints"]["vegetarian"] = gold["vegetarian"]
        if "max_stops" in gold:
            payload["constraints"]["max_stops"] = gold["max_stops"]

        score, detail = task.score(case, ok(payload))
        assert score == 1.0, f"{case['id']}: {detail}"


def test_a_wrong_field_costs_accuracy():
    task = TASK_CLASSES["tripspec_extract"]
    case = cases_for("tripspec_extract")[0]
    gold = case["gold"]
    payload = {
        "origin": {"lat": gold["origin"][0], "lon": gold["origin"][1]},
        "date": "2026-12-25",                      # wrong
        "start_time_local": gold["start_time_local"],
        "end_time_local": gold["end_time_local"],
        "budget_inr": gold["budget_inr"],
        "party_size": gold["party_size"],
        "interests": [{"category": c} for c in gold["categories"]],
    }
    score, detail = task.score(case, ok(payload))
    assert score < 1.0
    assert "date" in detail["misses"]


def test_extraction_rejects_an_invented_origin():
    """A coordinate that is not in the gazetteer fails the run outright."""
    case = cases_for("tripspec_extract")[0]
    check = task_check_for(TASK_CLASSES["tripspec_extract"], case)
    good, _ = check("", {"origin": {"lat": case["gold"]["origin"][0],
                                    "lon": case["gold"]["origin"][1]}})
    bad, detail = check("", {"origin": {"lat": 48.8566, "lon": 2.3522}})
    assert good
    assert not bad
    assert "gazetteer" in detail


def test_modify_penalises_clobbering_untouched_fields():
    task = TASK_CLASSES["tripspec_modify"]
    case = cases_for("tripspec_modify")[0]
    spec = dict(case["current_spec"])
    spec["end_time_local"] = case["gold"]["changed"]["end_time_local"]
    perfect, _ = task.score(case, ok(spec))
    assert perfect == 1.0

    clobbered = dict(spec)
    clobbered["party_size"] = 99
    worse, detail = task.score(case, ok(clobbered))
    assert worse < perfect
    assert "party_size" in detail["clobbered"]


def test_intent_scoring_is_exact():
    task = TASK_CLASSES["intent_classify"]
    case = cases_for("intent_classify")[0]
    assert task.score(case, ok({"intent": case["gold"]["intent"]}))[0] == 1.0
    assert task.score(case, ok({"intent": "out_of_scope"}))[0] == 0.0


def test_tool_scoring_splits_tool_and_arguments():
    task = TASK_CLASSES["tool_select"]
    case = cases_for("tool_select")[0]
    right = task.score(case, ok({"tool": case["gold"]["tool"],
                                 "arguments": case["gold"]["required_arguments"]}))[0]
    tool_only = task.score(case, ok({"tool": case["gold"]["tool"],
                                     "arguments": {}}))[0]
    wrong = task.score(case, ok({"tool": "create_plan", "arguments": {}}))[0]
    assert right == pytest.approx(1.0)
    assert 0.6 < tool_only < 1.0
    assert wrong == 0.0


def test_free_text_check_rejects_fabricated_numbers():
    case = cases_for("explain_itinerary")[0]
    check = task_check_for(TASK_CLASSES["explain_itinerary"], case)
    grounded = ("Your day starts at Cubbon Park, then Bangalore Palace and "
                "lunch at Koshys. The whole plan costs 660 rupees and covers "
                "8.4 km by auto over 167 minutes of activity.")
    invented = grounded + " Expect a 47.5 minute delay near the palace."
    assert check(grounded, None)[0]
    ok_flag, detail = check(invented, None)
    assert not ok_flag
    assert "47.5" in detail


def test_free_text_check_rejects_a_refusal():
    case = cases_for("explain_itinerary")[0]
    check = task_check_for(TASK_CLASSES["explain_itinerary"], case)
    refusal = ("I cannot help with that request because I do not have access "
               "to the itinerary details you are describing right now here.")
    assert not check(refusal, None)[0]


def test_mention_scoring_counts_required_facts():
    task = TASK_CLASSES["explain_itinerary"]
    case = cases_for("explain_itinerary")[0]
    every = " ".join(str(m) for m in case["gold"]["must_mention"])
    assert task.score(case, ok(text=every))[0] == 1.0
    assert task.score(case, ok(text="nothing relevant"))[0] == 0.0


def test_clarify_scoring_penalises_spurious_fields():
    task = TASK_CLASSES["clarify_question"]
    case = cases_for("clarify_question")[3]        # only origin is missing
    focused = task.score(case, ok({"question": "Where are you starting from?",
                                   "missing_fields": ["origin"]}))[0]
    noisy = task.score(case, ok({
        "question": "Where from?",
        "missing_fields": ["origin", "budget_inr", "party_size"]}))[0]
    assert focused > noisy


def test_critical_fields_are_the_documented_set():
    assert set(CRITICAL_FIELDS) == {
        "origin", "date", "start_time_local", "end_time_local", "budget_inr",
        "party_size", "categories", "transport", "vegetarian", "max_stops",
    }
