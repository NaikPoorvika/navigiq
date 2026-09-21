"""Regression floors for the deterministic evaluation suites (section 105).

The rules-only numbers are the product's behaviour when the language model is
down, so they must not silently regress. Floors sit a little under the
current results on ALL splits (dev + held-out); the model-backed gates are
checked by `python -m evals.run --llm on` (see docs/reports/evaluation.md).
These run against the loaded development database (names like "Nandi Hills"
must resolve), so they are skipped when it is not available.
"""
from __future__ import annotations

import pytest

from evals import intent, modification, references, tripspec

pytestmark = pytest.mark.realdata


async def test_intent_rules_only_floor(real_db):
    res = await intent.run(real_db, llm=None, split="all")
    assert res.metrics["accuracy"] >= 0.88, res.failures[:10]


async def test_tripspec_rules_floor(real_db):
    res = await tripspec.run(real_db, llm=None, split="all")
    assert res.metrics["schema_valid"] == 1.0
    assert res.metrics["critical_field_accuracy"] >= 0.97, res.failures[:10]
    assert res.metrics["relative_date_accuracy"] >= 0.98, res.failures[:10]
    assert res.metrics["hard_constraint_accuracy"] >= 0.97, res.failures[:10]


async def test_modification_rules_floor(real_db):
    res = await modification.run(real_db, llm=None, split="all")
    assert res.metrics["operation_accuracy"] >= 0.95, res.failures[:10]
    assert res.metrics["target_resolution_accuracy"] >= 0.95


async def test_reference_resolution_floor(real_db):
    res = await references.run(real_db, llm=None, split="all")
    assert res.metrics["resolution_accuracy"] >= 0.95, res.failures
