"""The regression tests for the failure this task exists to correct.

If any test in this file stops passing, the harness has regained the ability
to score a capped, empty or malformed generation as a success, and no number
it produces can be cited.
"""
from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from nq027.client import GenResult
from nq027.validity import (
    FAILURE_OUTCOMES,
    Outcome,
    judge,
    looks_truncated,
    numbers_in,
    strip_reasoning,
    ungrounded_numbers,
)


class Person(BaseModel):
    name: str
    age: int


def gen(text: str = "", *, done_reason: str = "stop", eval_count: int = 10,
        num_predict: int = 512, transport_ok: bool = True,
        error: str | None = None, thinking: str = "") -> GenResult:
    return GenResult(
        transport_ok=transport_ok, error=error, text=text, thinking=thinking,
        done=True if transport_ok else None, done_reason=done_reason,
        eval_count=eval_count, prompt_eval_count=50,
        eval_duration_ns=1_000_000_000, prompt_eval_duration_ns=100_000_000,
        wall_ms=1234.0, ttft_ms=100.0, model="test", num_ctx=8192,
        num_predict=num_predict,
    )


# --- the central guarantee ------------------------------------------------

def test_only_valid_is_a_success():
    assert Outcome.VALID.is_success
    for outcome in FAILURE_OUTCOMES:
        assert not outcome.is_success, f"{outcome} must not count as success"


def test_every_outcome_is_classified():
    """A new outcome must be deliberately added to one set or the other."""
    assert FAILURE_OUTCOMES | {Outcome.VALID} == set(Outcome)


# --- truncation -----------------------------------------------------------

def test_truncated_json_that_parses_is_still_a_failure():
    """The exact bug. Constrained decoding can emit a closed object and still
    stop at the cap; parsing first would score this a success."""
    body = json.dumps({"name": "Asha", "age": 30})
    verdict = judge(gen(body, done_reason="length", eval_count=512,
                        num_predict=512),
                    expects_json=True,
                    schema_validator=Person.model_validate)
    assert verdict.outcome is Outcome.TRUNCATED
    assert not verdict.is_success


def test_truncated_free_text_is_a_failure():
    verdict = judge(gen("Your day begins at Cubbon Park and then",
                        done_reason="length", eval_count=600, num_predict=600),
                    expects_json=False)
    assert verdict.outcome is Outcome.TRUNCATED


def test_eval_count_at_cap_is_truncation_without_done_reason():
    """Defensive signal: a server that omits done_reason cannot hide a cap."""
    assert looks_truncated(gen("x", done_reason=None, eval_count=256,
                               num_predict=256))


def test_finishing_below_the_cap_is_not_truncation():
    assert not looks_truncated(gen("done", done_reason="stop", eval_count=99,
                                   num_predict=512))


def test_done_true_does_not_imply_success():
    """Ollama sets done=True on a capped generation. Trusting it is the bug."""
    result = gen("partial", done_reason="length", eval_count=512,
                 num_predict=512)
    assert result.done is True
    assert judge(result, expects_json=False).outcome is Outcome.TRUNCATED


# --- emptiness ------------------------------------------------------------

def test_empty_response_is_a_failure():
    assert judge(gen(""), expects_json=False).outcome is Outcome.EMPTY


def test_whitespace_only_is_empty():
    assert judge(gen("   \n\t  "), expects_json=False).outcome is Outcome.EMPTY


def test_reasoning_only_response_is_empty():
    """A model that thought and never answered produced nothing usable."""
    verdict = judge(gen("<think>Let me consider the options at length</think>"),
                    expects_json=False)
    assert verdict.outcome is Outcome.EMPTY


def test_reasoning_in_separate_field_with_no_content_is_empty():
    verdict = judge(gen("", thinking="a long internal monologue"),
                    expects_json=False)
    assert verdict.outcome is Outcome.EMPTY


def test_unclosed_think_block_is_stripped():
    assert strip_reasoning("<think>cut off mid thought") == ""


def test_reasoning_before_a_real_answer_is_kept():
    verdict = judge(gen("<think>hmm</think>The plan starts at Cubbon Park."),
                    expects_json=False)
    assert verdict.is_success
    assert verdict.cleaned_text == "The plan starts at Cubbon Park."


# --- json and schema ------------------------------------------------------

def test_invalid_json_is_a_failure():
    verdict = judge(gen("{name: Asha, age: }"), expects_json=True,
                    schema_validator=Person.model_validate)
    assert verdict.outcome is Outcome.INVALID_JSON


def test_prose_where_json_was_required_is_a_failure():
    verdict = judge(gen("Sure! Here is the person you asked for."),
                    expects_json=True, schema_validator=Person.model_validate)
    assert verdict.outcome is Outcome.INVALID_JSON


def test_schema_violation_is_a_failure():
    verdict = judge(gen(json.dumps({"name": "Asha"})), expects_json=True,
                    schema_validator=Person.model_validate)
    assert verdict.outcome is Outcome.SCHEMA_INVALID
    assert verdict.payload == {"name": "Asha"}


def test_valid_json_passes_and_carries_the_payload():
    verdict = judge(gen(json.dumps({"name": "Asha", "age": 30})),
                    expects_json=True, schema_validator=Person.model_validate)
    assert verdict.is_success
    assert verdict.payload["age"] == 30


def test_markdown_fence_is_unwrapped():
    fenced = "```json\n{\"name\": \"Asha\", \"age\": 30}\n```"
    verdict = judge(gen(fenced), expects_json=True,
                    schema_validator=Person.model_validate)
    assert verdict.is_success


# --- transport ------------------------------------------------------------

def test_transport_failure_is_not_scored_on_its_partial_text():
    verdict = judge(gen("partial text that arrived", transport_ok=False,
                        error="connection reset"), expects_json=False)
    assert verdict.outcome is Outcome.TRANSPORT_ERROR


def test_timeout_is_distinguished_from_other_transport_errors():
    verdict = judge(gen(transport_ok=False, error="timeout after 300.0s"),
                    expects_json=False)
    assert verdict.outcome is Outcome.TIMEOUT


# --- task check -----------------------------------------------------------

def test_task_check_can_reject_output_that_parsed_and_validated():
    def reject(_text, _payload):
        return False, "fabricated a coordinate"

    verdict = judge(gen(json.dumps({"name": "Asha", "age": 30})),
                    expects_json=True, schema_validator=Person.model_validate,
                    task_check=reject)
    assert verdict.outcome is Outcome.TASK_CHECK_FAILED


def test_task_check_applies_to_free_text_too():
    def reject(_text, _payload):
        return False, "refusal"

    verdict = judge(gen("I cannot help with that."), expects_json=False,
                    task_check=reject)
    assert verdict.outcome is Outcome.TASK_CHECK_FAILED


# --- ladder order ---------------------------------------------------------

def test_truncation_beats_every_later_rung():
    """Truncated AND unparseable AND schema-invalid still reports TRUNCATED,
    which is the diagnosis that tells you to raise the cap."""
    verdict = judge(gen("{\"name\": \"As", done_reason="length",
                        eval_count=64, num_predict=64),
                    expects_json=True, schema_validator=Person.model_validate)
    assert verdict.outcome is Outcome.TRUNCATED


def test_transport_beats_truncation():
    verdict = judge(gen("x", done_reason="length", eval_count=64,
                        num_predict=64, transport_ok=False, error="boom"),
                    expects_json=False)
    assert verdict.outcome is Outcome.TRANSPORT_ERROR


# --- grounding ------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("costs 1,500 rupees", {"1500"}),
    ("6.4 km", {"6.4"}),
    ("no numbers here", set()),
    ("arrive 13:20", {"13", "20"}),
])
def test_number_extraction(text, expected):
    assert numbers_in(text) == expected


def test_fabricated_number_is_detected():
    facts = json.dumps({"total_cost_inr": 660, "distance_km": 8.4})
    invented = ungrounded_numbers("It costs 660 and takes 47.5 minutes", facts)
    assert invented == {"47.5"}


def test_restating_supplied_numbers_is_clean():
    facts = json.dumps({"total_cost_inr": 660, "distance_km": 8.4})
    assert ungrounded_numbers("660 rupees over 8.4 km", facts) == set()


def test_small_integers_are_tolerated():
    """Ordinals and counts are not fabrications worth flagging."""
    facts = json.dumps({"total_cost_inr": 660})
    assert ungrounded_numbers("your 3 stops cost 660", facts) == set()


def test_thousands_separator_matches_plain_digits():
    facts = json.dumps({"budget_inr": 1500})
    assert ungrounded_numbers("your budget of 1,500", facts) == set()
