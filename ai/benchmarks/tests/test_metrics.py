"""Aggregation must never let a failed run into a performance statistic."""
from __future__ import annotations

import pytest

from nq027.metrics import RunRecord, distribution, summarise
from nq027.validity import Outcome


def rec(outcome: str = "valid", wall_ms: float = 1000.0,
        accuracy: float | None = 1.0, **kwargs) -> RunRecord:
    base = dict(
        model="m", task="t", case_id="c", num_ctx=8192, concurrency=1,
        schema_constrained=True, outcome=outcome, detail="", wall_ms=wall_ms,
        ttft_ms=100.0, gen_tps=50.0, prompt_tps=500.0, eval_count=100,
        prompt_eval_count=50, done_reason="stop", num_predict=512,
        load_ms=0.0, accuracy=accuracy,
    )
    base.update(kwargs)
    return RunRecord(**base)


def test_failed_runs_are_excluded_from_latency():
    """A fast failure must not drag the reported latency down."""
    records = [
        rec(wall_ms=1000.0),
        rec(outcome=Outcome.TRUNCATED.value, wall_ms=10.0, accuracy=None),
        rec(outcome=Outcome.EMPTY.value, wall_ms=5.0, accuracy=None),
    ]
    summary = summarise(records)
    assert summary.n_runs == 3
    assert summary.n_valid == 1
    assert summary.latency_ms["mean"] == 1000.0
    assert summary.latency_ms["n"] == 1


def test_no_valid_runs_reports_none_not_zero():
    records = [rec(outcome=Outcome.TRUNCATED.value, accuracy=None)
               for _ in range(5)]
    summary = summarise(records)
    assert summary.n_valid == 0
    assert summary.latency_ms is None
    assert summary.ttft_ms is None
    assert summary.gen_tps is None
    assert summary.accuracy_mean is None
    assert summary.validity_rate == 0.0


def test_all_truncated_is_detected():
    records = [rec(outcome=Outcome.TRUNCATED.value, accuracy=None)
               for _ in range(4)]
    summary = summarise(records)
    assert summary.all_truncated
    assert summary.truncation_rate == 1.0


def test_partial_truncation_is_not_all_truncated():
    records = [rec(), rec(outcome=Outcome.TRUNCATED.value, accuracy=None)]
    summary = summarise(records)
    assert not summary.all_truncated
    assert summary.truncation_rate == 0.5


def test_outcome_breakdown_is_preserved():
    records = [rec(), rec(outcome=Outcome.INVALID_JSON.value, accuracy=None),
               rec(outcome=Outcome.INVALID_JSON.value, accuracy=None)]
    summary = summarise(records)
    assert summary.outcomes == {"valid": 1, "invalid_json": 2}


def test_accuracy_averages_only_scored_valid_runs():
    records = [rec(accuracy=1.0), rec(accuracy=0.5),
               rec(outcome=Outcome.EMPTY.value, accuracy=None)]
    summary = summarise(records)
    assert summary.accuracy_mean == pytest.approx(0.75)


def test_throughput_counts_valid_runs_only():
    records = [rec(), rec(), rec(outcome=Outcome.TRUNCATED.value,
                                 accuracy=None)]
    summary = summarise(records, wall_clock_s=2.0)
    assert summary.throughput_rps == pytest.approx(1.0)


def test_distribution_of_nothing_is_none():
    assert distribution([]) is None
    assert distribution([None, None]) is None


def test_percentiles_report_observed_values():
    dist = distribution([10.0, 20.0, 30.0, 40.0])
    assert dist.p50 in (10.0, 20.0, 30.0, 40.0)
    assert dist.p95 == 40.0
    assert dist.minimum == 10.0
    assert dist.maximum == 40.0


def test_empty_cell_is_an_error_not_a_zero_row():
    with pytest.raises(ValueError):
        summarise([])
