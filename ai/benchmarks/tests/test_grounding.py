"""Grounding checks must reject fabrication without punishing honest answers.

Both directions matter. A check that lets invented figures through makes the
free-text classes meaningless; one that flags figures the model was given
fails every model for the harness's own mistake.
"""
from __future__ import annotations

import json

import pytest

from nq027.tasks import TASK_CLASSES, cases_for, task_check_for
from nq027.validity import ungrounded_numbers


# --- allow lists ---------------------------------------------------------

def test_numeric_allow_entries_match_extracted_strings():
    """allowed_numbers is authored as numbers; extraction yields strings."""
    assert ungrounded_numbers("surcharge from 22:00", "{}", allow={22}) == set()


def test_float_allow_entries_match():
    assert ungrounded_numbers("about 47.5 minutes", "{}", allow={47.5}) == set()


def test_string_allow_entries_match():
    assert ungrounded_numbers("built in 1887", "{}", allow={"1887"}) == set()


def test_allow_list_does_not_permit_everything():
    assert ungrounded_numbers("it costs 9999", "{}", allow={22}) == {"9999"}


# --- per-class grounding sources -----------------------------------------

def test_rag_answers_are_grounded_in_their_passages():
    """rag cases carry `passages`, not `facts`. Grounding against the wrong
    key treats every figure in the passage as invented."""
    case = next(c for c in cases_for("rag_answer") if c["id"] == "rag-002")
    check = task_check_for(TASK_CLASSES["rag_answer"], case)
    answer = ("A night surcharge applies to auto fares between 22:00 and "
              "05:00, and drivers must run the meter.")
    ok, detail = check(answer, None)
    assert ok, detail


def test_rag_answer_still_rejects_an_invented_figure():
    case = next(c for c in cases_for("rag_answer") if c["id"] == "rag-005")
    check = task_check_for(TASK_CLASSES["rag_answer"], case)
    ok, detail = check("The airport is 35 km away and costs 1450 rupees.", None)
    assert not ok
    assert "1450" in detail


def test_explain_grounds_in_facts():
    case = next(c for c in cases_for("explain_itinerary") if c["id"] == "exp-003")
    check = task_check_for(TASK_CLASSES["explain_itinerary"], case)
    answer = ("Your plan comes to 1180 rupees against a budget of 1500, "
              "which leaves 320 rupees spare for the two of you on the day.")
    ok, detail = check(answer, None)
    assert ok, detail


def test_reroute_grounds_in_facts():
    case = cases_for("reroute_message")[0]
    check = task_check_for(TASK_CLASSES["reroute_message"], case)
    ok, detail = check(
        "Your route to Bangalore Palace changed and now arrives at 13:20, "
        "about 14 minutes later than planned.", None)
    assert ok, detail


@pytest.mark.parametrize("task_id", ["explain_itinerary", "rag_answer",
                                     "reroute_message"])
def test_every_free_text_case_has_a_grounding_source(task_id):
    """A missing grounding source raises rather than silently grounding
    against an empty object, which would fail every number."""
    for case in cases_for(task_id):
        check = task_check_for(TASK_CLASSES[task_id], case)
        check("a plain answer with no numbers at all in it whatsoever", None)


def test_missing_grounding_source_is_loud():
    from nq027.tasks import _grounded_text_check
    check = _grounded_text_check(1, 500, facts_key="nope")({"id": "x"})
    with pytest.raises(KeyError):
        check("some answer", None)


# --- the gold answers are themselves grounded ----------------------------

@pytest.mark.parametrize("task_id", ["explain_itinerary", "reroute_message"])
def test_required_mentions_appear_in_the_supplied_facts(task_id):
    """If a must_mention string is not in the facts, the case is asking the
    model to state something it was never told."""
    for case in cases_for(task_id):
        facts = json.dumps(case["facts"], ensure_ascii=False)
        for mention in case["gold"]["must_mention"]:
            assert str(mention) in facts, f"{case['id']}: {mention}"


def test_rag_required_mentions_appear_in_passages_or_are_negations():
    for case in cases_for("rag_answer"):
        passages = " ".join(case["passages"])
        for mention in case["gold"]["must_mention"]:
            # "not" marks the cases whose correct answer is that the passages
            # do not contain the answer.
            assert mention == "not" or str(mention) in passages, case["id"]
