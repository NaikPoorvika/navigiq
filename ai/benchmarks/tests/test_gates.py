"""The ADR-012 gates, including the rule that absent evidence never passes."""
from __future__ import annotations

from nq027 import gates
from nq027.gates import GateStatus
from nq027.metrics import CellSummary
from nq027.tasks import REFERENCE_DATE


def cell(task="tripspec_extract", *, n_runs=50, n_valid=50, ctx=8192,
         conc=1, constrained=True, p95=3000.0, accuracy=0.9,
         outcomes=None) -> CellSummary:
    return CellSummary(
        model="m", task=task, num_ctx=ctx, concurrency=conc,
        schema_constrained=constrained, n_runs=n_runs, n_valid=n_valid,
        outcomes=outcomes or {"valid": n_valid},
        latency_ms={"n": n_valid, "mean": p95 * 0.7, "p50": p95 * 0.8,
                    "p95": p95, "minimum": 100.0, "maximum": p95},
        ttft_ms=None, gen_tps=None, prompt_tps=None, accuracy_mean=accuracy,
    )


def probe(*, resident=True, free=8000, ctx=8192) -> dict:
    return {"probes": [{"num_ctx": ctx, "fully_resident": resident,
                        "vram_mib": 9000, "gpu_free_mib_after_load": free,
                        "offloaded_fraction": 0.0 if resident else 0.35,
                        "headroom_ok": free >= 2560, "smoke_outcome": "valid"}]}


# --- absent evidence ------------------------------------------------------

def test_missing_evidence_is_unknown_not_pass():
    result = gates.gate_schema_validity([])
    assert result.status is GateStatus.UNKNOWN
    assert not result.passed


def test_unknown_blocks_eligibility():
    verdict = gates.evaluate("m", {}, [], [])
    assert not verdict.eligible
    assert verdict.failed_gates


def test_latency_gate_is_unknown_when_no_run_was_valid():
    dead = cell(n_valid=0, outcomes={"truncated": 50})
    dead.latency_ms = None
    result = gates.gate_extraction_latency([dead])
    assert result.status is GateStatus.UNKNOWN


# --- individual gates -----------------------------------------------------

def test_residency_fails_on_cpu_offload():
    result = gates.gate_residency(probe(resident=False))
    assert result.status is GateStatus.FAIL


def test_residency_passes_when_fully_in_vram():
    assert gates.gate_residency(probe()).status is GateStatus.PASS


def test_headroom_fails_below_the_embedding_reserve():
    result = gates.gate_embedding_headroom(probe(free=1200))
    assert result.status is GateStatus.FAIL


def test_schema_validity_threshold():
    assert gates.gate_schema_validity(
        [cell(n_valid=48)]).status is GateStatus.PASS      # 96%
    assert gates.gate_schema_validity(
        [cell(n_valid=47)]).status is GateStatus.FAIL      # 94%


def test_fully_truncated_class_fails():
    dead = cell(task="explain_itinerary", n_valid=0,
                outcomes={"truncated": 50})
    result = gates.gate_no_class_fully_truncated([cell(), dead])
    assert result.status is GateStatus.FAIL
    assert "explain_itinerary" in str(result.measured)


def test_partially_truncated_class_passes():
    mixed = cell(task="explain_itinerary", n_valid=30,
                 outcomes={"valid": 30, "truncated": 20})
    assert gates.gate_no_class_fully_truncated(
        [cell(), mixed]).status is GateStatus.PASS


def test_latency_budget():
    assert gates.gate_extraction_latency(
        [cell(p95=7999.0)]).status is GateStatus.PASS
    assert gates.gate_extraction_latency(
        [cell(p95=8001.0)]).status is GateStatus.FAIL


def test_accuracy_threshold():
    assert gates.gate_critical_field_accuracy(
        [cell(accuracy=0.80)]).status is GateStatus.PASS
    assert gates.gate_critical_field_accuracy(
        [cell(accuracy=0.79)]).status is GateStatus.FAIL


# --- combination ----------------------------------------------------------

def test_all_gates_passing_is_eligible():
    verdict = gates.evaluate("m", probe(), [cell()], [cell()])
    assert verdict.eligible, verdict.failed_gates


def test_one_failure_blocks_eligibility():
    verdict = gates.evaluate("m", probe(resident=False), [cell()], [cell()])
    assert not verdict.eligible
    assert "gpu_residency" in verdict.failed_gates


def test_ineligible_never_outranks_eligible():
    good = gates.evaluate("good", probe(), [cell()], [cell(accuracy=0.82)])
    bad = gates.evaluate("bad", probe(resident=False), [cell()],
                         [cell(accuracy=0.99)])
    ranking = gates.rank([bad, good], {
        "good": [cell(accuracy=0.82)], "bad": [cell(accuracy=0.99)]})
    assert ranking[0]["model"] == "good"


def test_reference_date_is_fixed_for_reproducibility():
    assert REFERENCE_DATE == "2026-10-01"
