"""NQ-032 - a grounded explanation of a plan.

The model is given the fact block and nothing else, told to use only what is
there, and its answer is checked number by number before anyone sees it. If
a number isn't supported, the answer is thrown away and a plain sentence
built from the facts is returned instead.

That is the whole point: the explanation can be wrong about tone, or dull,
but it cannot be wrong about a time, a price or a distance.
"""
from __future__ import annotations

import logging

from app.llm.errors import LLMError
from app.llm.types import ChatMessage

from .entailment import unsupported_numbers
from .facts import FactBlock, plain_summary

log = logging.getLogger(__name__)

EXPLANATION_VERSION = "explain-v1"

SYSTEM = """You explain a travel plan that has already been made.

RULES, in order of importance:
1. Use ONLY the facts below. Every name, time, price, distance and duration
   you write must appear in them exactly.
2. Never add a fact that is not there - no opening hours, no ratings, no
   descriptions of what a place is like, no advice about what to order.
3. If something was asked for but is not in the plan, you may say so; do not
   guess why beyond what the facts say.
4. Write 2 to 4 short sentences in plain English, addressed to the traveller.
   No lists, no headings, no emoji.
5. Times are 24-hour, exactly as written in the facts."""


async def explain_plan(gateway, facts: FactBlock) -> dict:
    """An explanation of this plan, or a plain one built from the facts.

    Always returns something true. `grounded` says whether the model's own
    words survived the numeric check.
    """
    fallback = {
        "text": plain_summary(facts),
        "source": "facts",
        "grounded": True,
        "version": EXPLANATION_VERSION,
    }

    try:
        generation = await gateway.generate(
            [
                ChatMessage(role="system", content=SYSTEM),
                ChatMessage(role="user", content=f"FACTS:\n{facts.to_prompt()}"),
            ],
            max_tokens=300,
            temperature=0.0,
        )
    except LLMError as exc:
        log.info("explanation unavailable (%s) - using the plain summary", exc.code)
        return {**fallback, "reason": "model unavailable"}

    text = generation.text.strip()
    unsupported = unsupported_numbers(text, facts.allowed_numbers())
    if unsupported:
        # One invented figure is enough to distrust the rest.
        log.warning("explanation refused: %s not in the facts", ", ".join(unsupported))
        return {**fallback, "reason": "unsupported numbers",
                "rejected_numbers": unsupported, "model": generation.model}

    return {
        "text": text,
        "source": "model",
        "grounded": True,
        "version": EXPLANATION_VERSION,
        "model": generation.model,
        "latency_ms": round(generation.latency_ms, 1),
    }