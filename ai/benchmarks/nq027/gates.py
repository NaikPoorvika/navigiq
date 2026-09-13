"""The ADR-012 decision rules, as executable checks.

Written as code so the selection is reproducible and arguable: anyone can
read what the threshold was, see the measured value beside it, and disagree
with the threshold rather than with a conclusion.

A gate returns UNKNOWN when the evidence needed to judge it is missing. That
is deliberately not a pass. The failure this whole task exists to correct was
a harness treating absent evidence as acceptable evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .metrics import CellSummary

# --- thresholds ----------------------------------------------------------
# Each is stated once, here, and cited by name in ADR-012.

SCHEMA_VALIDITY_MIN = 0.95        # constrained tripspec_extract
CRITICAL_FIELD_ACCURACY_MIN = 0.80
EMBEDDING_HEADROOM_MIB = 2560     # must stay free for the embedding model

# Interactive budget for TripSpec extraction. See ASSUMPTION-002: the LLM is
# one stage in front of a deterministic pipeline that itself takes a second
# or two, and the whole perceived wait should stay near ten seconds.
TRIPSPEC_LATENCY_P95_BUDGET_MS = 8000
TRIPSPEC_BUDGET_CONTEXT = 8192
TRIPSPEC_BUDGET_CONCURRENCY = 1


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"       # not measured; never counts as a pass


@dataclass
class GateResult:
    name: str
    status: GateStatus
    measured: object
    threshold: object
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status is GateStatus.PASS

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "measured": self.measured,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass
class CandidateVerdict:
    model: str
    gates: list[GateResult]

    @property
    def eligible(self) -> bool:
        """Every gate must pass. UNKNOWN blocks, by design."""
        return bool(self.gates) and all(g.passed for g in self.gates)

    @property
    def failed_gates(self) -> list[str]:
        return [g.name for g in self.gates if not g.passed]

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "eligible": self.eligible,
            "failed_gates": self.failed_gates,
            "gates": [g.to_dict() for g in self.gates],
        }


def _find(cells: list[CellSummary], **criteria) -> CellSummary | None:
    for cell in cells:
        if all(getattr(cell, k) == v for k, v in criteria.items()):
            return cell
    return None


def _best_evidence(cells: list[CellSummary], **criteria) -> CellSummary | None:
    """The matching cell with the most valid runs.

    The same (task, ctx, concurrency, schema) combination is measured in both
    the performance matrix (few runs per cell) and the quality stage (one run
    per case, so many more). Judging a threshold on the larger sample is
    strictly better evidence, and which one that is should not depend on the
    order the stages happened to write their cells in.
    """
    matches = [c for c in cells
               if all(getattr(c, k) == v for k, v in criteria.items())]
    if not matches:
        return None
    return max(matches, key=lambda c: c.n_valid)


def gate_residency(probe: dict) -> GateResult:
    """Fully on the GPU, no CPU offload, at the working context."""
    entries = [p for p in probe.get("probes", [])
               if p.get("num_ctx") == TRIPSPEC_BUDGET_CONTEXT]
    if not entries:
        return GateResult("gpu_residency", GateStatus.UNKNOWN, None,
                          "fully resident",
                          f"no probe at ctx={TRIPSPEC_BUDGET_CONTEXT}")
    entry = entries[0]
    resident = entry.get("fully_resident")
    if resident is None:
        return GateResult("gpu_residency", GateStatus.UNKNOWN, None,
                          "fully resident", "model did not report as loaded")
    offload = entry.get("offloaded_fraction") or 0.0
    return GateResult(
        "gpu_residency",
        GateStatus.PASS if resident else GateStatus.FAIL,
        f"{(1 - offload) * 100:.1f}% in VRAM",
        "100% in VRAM",
        f"vram={entry.get('vram_mib')} MiB at ctx={TRIPSPEC_BUDGET_CONTEXT}",
    )


def gate_embedding_headroom(probe: dict) -> GateResult:
    """Room left for the embedding model to sit alongside it."""
    entries = [p for p in probe.get("probes", [])
               if p.get("num_ctx") == TRIPSPEC_BUDGET_CONTEXT]
    if not entries:
        return GateResult("embedding_headroom", GateStatus.UNKNOWN, None,
                          f">= {EMBEDDING_HEADROOM_MIB} MiB free",
                          f"no probe at ctx={TRIPSPEC_BUDGET_CONTEXT}")
    free = entries[0].get("gpu_free_mib_after_load")
    if free is None:
        return GateResult("embedding_headroom", GateStatus.UNKNOWN, None,
                          f">= {EMBEDDING_HEADROOM_MIB} MiB free",
                          "GPU free memory unreadable")
    return GateResult(
        "embedding_headroom",
        GateStatus.PASS if free >= EMBEDDING_HEADROOM_MIB else GateStatus.FAIL,
        f"{free} MiB free",
        f">= {EMBEDDING_HEADROOM_MIB} MiB free",
    )


def gate_schema_validity(cells: list[CellSummary]) -> GateResult:
    """Constrained TripSpec extraction must be consumable nearly every time."""
    cell = _find(cells, task="tripspec_extract", schema_constrained=True)
    if cell is None:
        return GateResult("schema_validity", GateStatus.UNKNOWN, None,
                          f">= {SCHEMA_VALIDITY_MIN:.0%}",
                          "no constrained tripspec_extract quality cell")
    rate = cell.validity_rate
    return GateResult(
        "schema_validity",
        GateStatus.PASS if rate >= SCHEMA_VALIDITY_MIN else GateStatus.FAIL,
        f"{rate:.1%} ({cell.n_valid}/{cell.n_runs})",
        f">= {SCHEMA_VALIDITY_MIN:.0%}",
        f"outcomes={cell.outcomes}",
    )


def gate_no_class_fully_truncated(cells: list[CellSummary]) -> GateResult:
    """No task class where every single generation hit the cap.

    This is the check the superseded 2026-09-04 run needed and did not have:
    seven of its eight task classes were truncated throughout and were still
    recorded as successes.
    """
    dead = sorted({c.task for c in cells if c.all_truncated})
    if not cells:
        return GateResult("no_class_fully_truncated", GateStatus.UNKNOWN, None,
                          "no fully-truncated class", "no cells measured")
    return GateResult(
        "no_class_fully_truncated",
        GateStatus.FAIL if dead else GateStatus.PASS,
        (f"fully truncated: {', '.join(dead)}" if dead else "none"),
        "no fully-truncated class",
    )


def gate_extraction_latency(cells: list[CellSummary]) -> GateResult:
    """TripSpec extraction inside the interactive budget (ASSUMPTION-002)."""
    cell = _best_evidence(cells, task="tripspec_extract",
                          num_ctx=TRIPSPEC_BUDGET_CONTEXT,
                          concurrency=TRIPSPEC_BUDGET_CONCURRENCY,
                          schema_constrained=True)
    if cell is None or not cell.latency_ms:
        return GateResult(
            "extraction_latency_p95", GateStatus.UNKNOWN, None,
            f"<= {TRIPSPEC_LATENCY_P95_BUDGET_MS} ms",
            f"no valid runs at ctx={TRIPSPEC_BUDGET_CONTEXT} "
            f"conc={TRIPSPEC_BUDGET_CONCURRENCY}",
        )
    p95 = cell.latency_ms["p95"]
    return GateResult(
        "extraction_latency_p95",
        GateStatus.PASS if p95 <= TRIPSPEC_LATENCY_P95_BUDGET_MS
        else GateStatus.FAIL,
        f"{p95:.0f} ms",
        f"<= {TRIPSPEC_LATENCY_P95_BUDGET_MS} ms",
        f"over {cell.n_valid} valid runs",
    )


def gate_critical_field_accuracy(cells: list[CellSummary]) -> GateResult:
    """Does the extracted spec actually say what the user asked for?"""
    cell = _find(cells, task="tripspec_extract", schema_constrained=True)
    if cell is None or cell.accuracy_mean is None:
        return GateResult("critical_field_accuracy", GateStatus.UNKNOWN, None,
                          f">= {CRITICAL_FIELD_ACCURACY_MIN:.0%}",
                          "no scored valid runs")
    acc = cell.accuracy_mean
    return GateResult(
        "critical_field_accuracy",
        GateStatus.PASS if acc >= CRITICAL_FIELD_ACCURACY_MIN
        else GateStatus.FAIL,
        f"{acc:.1%}",
        f">= {CRITICAL_FIELD_ACCURACY_MIN:.0%}",
        f"mean over {cell.n_valid} valid runs",
    )


def evaluate(model: str, probe: dict, sweep_cells: list[CellSummary],
             quality_cells: list[CellSummary]) -> CandidateVerdict:
    """Apply every gate to one candidate."""
    return CandidateVerdict(model=model, gates=[
        gate_residency(probe),
        gate_embedding_headroom(probe),
        gate_schema_validity(quality_cells),
        gate_no_class_fully_truncated(sweep_cells + quality_cells),
        gate_extraction_latency(sweep_cells + quality_cells),
        gate_critical_field_accuracy(quality_cells),
    ])


def rank(verdicts: list[CandidateVerdict],
         quality_by_model: dict[str, list[CellSummary]]) -> list[dict]:
    """Order eligible candidates. Accuracy first, then latency.

    Accuracy leads because a fast wrong TripSpec costs the user a wasted
    trip, while a slow correct one costs them a few seconds. Ineligible
    candidates are listed last and are never ranked above an eligible one,
    whatever they scored.
    """
    rows = []
    for verdict in verdicts:
        cells = quality_by_model.get(verdict.model, [])
        extract = _find(cells, task="tripspec_extract", schema_constrained=True)
        rows.append({
            "model": verdict.model,
            "eligible": verdict.eligible,
            "failed_gates": verdict.failed_gates,
            "critical_field_accuracy": (extract.accuracy_mean
                                        if extract else None),
            "schema_validity": extract.validity_rate if extract else None,
            "extract_p95_ms": (extract.latency_ms["p95"]
                               if extract and extract.latency_ms else None),
        })

    def key(row: dict):
        return (
            0 if row["eligible"] else 1,
            -(row["critical_field_accuracy"] or 0.0),
            row["extract_p95_ms"] if row["extract_p95_ms"] is not None else 1e9,
        )

    return sorted(rows, key=key)
