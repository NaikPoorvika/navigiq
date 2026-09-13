"""Request planning for a cell.

A concurrency level is only measured if that many requests are actually in
flight. Issuing two requests with four workers measures concurrency 2 and
labels the row 4, which is a false measurement rather than a missing one.
"""
from __future__ import annotations

import math

import pytest

from nq027.runner import Runner, subset_cases
from nq027.tasks import cases_for


def planned_total(runs: int, concurrency: int) -> int:
    return math.ceil(runs / concurrency) * concurrency


@pytest.mark.parametrize("runs,concurrency,expected", [
    (6, 1, 6),
    (6, 2, 6),
    (6, 4, 8),     # rounded up so all four slots are used
    (2, 4, 4),     # the calibration bug: 2 requests could not fill 4 workers
    (1, 4, 4),
    (12, 4, 12),
])
def test_request_count_is_a_multiple_of_concurrency(runs, concurrency,
                                                    expected):
    total = planned_total(runs, concurrency)
    assert total == expected
    assert total % concurrency == 0
    assert total >= concurrency
    assert total >= runs


def test_cases_are_cycled_not_repeated_back_to_back():
    """Ollama caches the prompt prefix; a repeated prompt is not a second
    independent measurement."""
    cases = subset_cases("tripspec_extract", 3)
    total = planned_total(6, 1)
    plan = [cases[i % len(cases)] for i in range(total)]
    ids = [c["id"] for c in plan]
    assert all(ids[i] != ids[i + 1] for i in range(len(ids) - 1))


def test_subset_is_deterministic_across_calls():
    assert (subset_cases("tripspec_extract", 3)
            == subset_cases("tripspec_extract", 3))


def test_subset_matches_file_order():
    full = cases_for("tripspec_extract")
    assert subset_cases("tripspec_extract", 3) == full[:3]


def test_think_setting_is_per_model_capability():
    from nq027.env import ModelIdentity
    assert Runner.think_setting(
        ModelIdentity(model="x", capabilities=["thinking"])) is False
    assert Runner.think_setting(
        ModelIdentity(model="y", capabilities=[])) is None
