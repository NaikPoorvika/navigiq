"""NQ-032 - numeric entailment: every number must come from the facts.

A model explaining a plan will happily write "just a 5 minute walk" when the
facts say 11, or "opens at 9am" when no opening time was given. Reading
fluently is exactly what makes that dangerous.

So every number in the generated text is checked against the numbers in the
fact block. One unsupported number and the whole explanation is refused -
not patched, because a sentence with one invented figure gives no reason to
trust the rest of it.
"""
from __future__ import annotations

import re

# Times (21:05), money and minutes (450, 35), decimals (1.2).
NUMBER = re.compile(r"\d{1,5}(?::\d{2}|\.\d{1,2})?")

# Ordinary words that carry a number without asserting a fact.
HARMLESS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}


def numbers_in(text: str) -> list[str]:
    return NUMBER.findall(text)


def unsupported_numbers(text: str, allowed: set[str], *,
                        allow_small_counts: bool = True) -> list[str]:
    """Numbers in the text that the facts do not support, in order.

    Small counts ("two stops", "the 3rd") are allowed by default: they
    describe the list rather than assert a measurement.
    """
    out: list[str] = []
    for n in numbers_in(text):
        if n in allowed:
            continue
        if allow_small_counts and n in HARMLESS:
            continue
        if n not in out:
            out.append(n)
    return out
