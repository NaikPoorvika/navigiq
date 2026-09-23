"""Facts, entailment and the explanation's refusal to pass on invented numbers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.llm.errors import LLMUnavailable  # noqa: E402
from app.llm.types import Generation  # noqa: E402
from app.services.explain.entailment import unsupported_numbers  # noqa: E402
from app.services.explain.explain import explain_plan  # noqa: E402
from app.services.explain.facts import build_facts, plain_summary  # noqa: E402

PLAN = {
    "itinerary": {
        "origin": {"name": "Jayanagar", "lat": 12.93, "lon": 77.58},
        "total_cost_inr": 450, "total_duration_min": 35, "total_walk_m": 481,
        "stops": [{
            "seq": 1, "name": "Cool joint", "category": "street_food",
            "arrive_min": 1265, "depart_min": 1295, "visit_minutes": 30,
            "cost_inr": 450, "cost_basis": "category_estimate",
            "hours_verified": False, "travel_minutes_from_prev": 5,
            "mode_from_prev": "walking",
        }],
    },
    "weather": {"available": True, "condition": "clear", "mean_temp_c": 22.4},
}
SPEC = {
    "date": "2026-09-23", "start_time_local": "21:00", "end_time_local": "22:00",
    "party_size": 3, "budget_inr": None,
    "interests": [{"category": "street_food"}, {"category": "dessert"}],
}


def facts():
    return build_facts(PLAN, SPEC)


class Model:
    """Stands in for the gateway: answers with fixed text, or raises."""

    def __init__(self, text: str | None = None, raises=None):
        self.text = text
        self.raises = raises
        self.prompt = ""

    async def generate(self, messages, **kwargs):
        if self.raises:
            raise self.raises
        self.prompt = messages[-1].content
        return Generation(text=self.text or "", model="qwen3:4b", prompt_tokens=10,
                          completion_tokens=10, latency_ms=900.0, attempts=1)


# ------------------------------------------------------------------ facts

def test_facts_copy_the_plan_exactly():
    f = facts()
    assert f.stops[0].arrive == "21:05" and f.stops[0].depart == "21:35"
    assert f.total_cost_inr == 450 and f.party_size == 3
    assert f.temperature_c == 22


def test_what_was_asked_for_but_missing_is_recorded():
    assert facts().not_included == ("dessert",)


def test_prompt_mentions_unconfirmed_hours():
    assert "opening hours not confirmed" in facts().to_prompt()


def test_plain_summary_is_true_and_complete():
    s = plain_summary(facts())
    assert "Cool joint" in s and "450" in s and "481" in s


# ------------------------------------------------------------- entailment

def test_numbers_from_the_facts_pass():
    text = "You start at 21:00 and reach Cool joint at 21:05, about 450 rupees."
    assert unsupported_numbers(text, facts().allowed_numbers()) == []


def test_an_invented_walking_time_is_caught():
    """The facts say 5 minutes; the model wrote 15."""
    assert unsupported_numbers("It's a 15 minute walk.", facts().allowed_numbers()) == ["15"]


def test_an_invented_opening_time_is_caught():
    assert unsupported_numbers("It opens at 18:30.", facts().allowed_numbers()) == ["18:30"]


def test_small_counts_are_not_treated_as_claims():
    assert unsupported_numbers("Just 1 stop tonight.", facts().allowed_numbers()) == []


# ------------------------------------------------------------ explanation

@pytest.mark.asyncio
async def test_a_grounded_explanation_is_passed_through():
    good = "One stop tonight: Cool joint at 21:05, 30 minutes there, about 450 rupees."
    r = await explain_plan(Model(good), facts())
    assert r["source"] == "model" and r["text"] == good


@pytest.mark.asyncio
async def test_an_explanation_with_an_invented_number_is_refused():
    r = await explain_plan(Model("A 12 minute walk gets you there by 20:45."), facts())
    assert r["source"] == "facts"
    assert r["rejected_numbers"] == ["12", "20:45"]
    assert "Cool joint" in r["text"]          # still a true answer


@pytest.mark.asyncio
async def test_no_model_still_gives_a_true_answer():
    r = await explain_plan(Model(raises=LLMUnavailable("ollama is not running")), facts())
    assert r["source"] == "facts" and r["grounded"] is True


@pytest.mark.asyncio
async def test_the_model_sees_the_facts_and_nothing_else():
    model = Model("One stop tonight.")
    await explain_plan(model, facts())
    assert "Cool joint" in model.prompt and "lat" not in model.prompt