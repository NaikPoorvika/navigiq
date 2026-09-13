"""Aggregation over runs.

One invariant, enforced here rather than trusted to callers: performance
statistics are computed over runs whose outcome is VALID, and over nothing
else. A capped generation has a latency, and reporting it is how a token cap
gets mistaken for a model being fast.

When no run in a cell was valid, every performance figure is None - not zero,
not the failed runs' timings. The report prints "no valid runs" and the gate
sees a cell it cannot score. Silence is the correct output for an empty
sample; a number would be a lie.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .validity import Judgement, Outcome


@dataclass
class Distribution:
    n: int
    mean: float
    p50: float
    p95: float
    minimum: float
    maximum: float

    def to_dict(self) -> dict:
        return {k: (round(v, 2) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def distribution(values: list[float]) -> Distribution | None:
    """None for an empty sample. Never a zero standing in for no data."""
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if not clean:
        return None
    clean.sort()
    return Distribution(
        n=len(clean),
        mean=sum(clean) / len(clean),
        p50=_percentile(clean, 0.50),
        p95=_percentile(clean, 0.95),
        minimum=clean[0],
        maximum=clean[-1],
    )


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile.

    Nearest-rank rather than interpolation: with the small n per cell that a
    local sweep can afford, an interpolated p95 invents a value between two
    observations. Nearest-rank always reports a measurement that happened.
    """
    if not sorted_values:
        raise ValueError("no values")
    rank = max(1, math.ceil(q * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


@dataclass
class RunRecord:
    """One request: what was asked, what came back, how it was judged."""
    model: str
    task: str
    case_id: str
    num_ctx: int
    concurrency: int
    schema_constrained: bool
    outcome: str
    detail: str
    wall_ms: float
    ttft_ms: float | None
    gen_tps: float | None
    prompt_tps: float | None
    eval_count: int | None
    prompt_eval_count: int | None
    done_reason: str | None
    num_predict: int | None
    load_ms: float | None
    accuracy: float | None
    accuracy_detail: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.outcome == Outcome.VALID.value

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CellSummary:
    """One (model, task, num_ctx, concurrency, schema) cell."""
    model: str
    task: str
    num_ctx: int
    concurrency: int
    schema_constrained: bool

    n_runs: int
    n_valid: int
    outcomes: dict[str, int]

    latency_ms: dict | None
    ttft_ms: dict | None
    gen_tps: dict | None
    prompt_tps: dict | None
    accuracy_mean: float | None
    wall_clock_s: float | None = None
    throughput_rps: float | None = None

    @property
    def validity_rate(self) -> float:
        return self.n_valid / self.n_runs if self.n_runs else 0.0

    @property
    def truncation_rate(self) -> float:
        return (self.outcomes.get(Outcome.TRUNCATED.value, 0) / self.n_runs
                if self.n_runs else 0.0)

    @property
    def all_truncated(self) -> bool:
        """Every run hit the cap. The specific failure that invalidated the
        superseded 2026-09-04 results, so it is named and gated explicitly."""
        return (self.n_runs > 0
                and self.outcomes.get(Outcome.TRUNCATED.value, 0) == self.n_runs)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "task": self.task,
            "num_ctx": self.num_ctx,
            "concurrency": self.concurrency,
            "schema_constrained": self.schema_constrained,
            "n_runs": self.n_runs,
            "n_valid": self.n_valid,
            "validity_rate": round(self.validity_rate, 4),
            "truncation_rate": round(self.truncation_rate, 4),
            "all_truncated": self.all_truncated,
            "outcomes": self.outcomes,
            "latency_ms": self.latency_ms,
            "ttft_ms": self.ttft_ms,
            "gen_tps": self.gen_tps,
            "prompt_tps": self.prompt_tps,
            "accuracy_mean": (round(self.accuracy_mean, 4)
                              if self.accuracy_mean is not None else None),
            "wall_clock_s": (round(self.wall_clock_s, 2)
                             if self.wall_clock_s is not None else None),
            "throughput_rps": (round(self.throughput_rps, 3)
                               if self.throughput_rps is not None else None),
        }


def summarise(records: list[RunRecord], *, wall_clock_s: float | None = None
              ) -> CellSummary:
    """Collapse one cell. Performance fields come from valid runs only."""
    if not records:
        raise ValueError("cannot summarise an empty cell")

    first = records[0]
    outcomes: dict[str, int] = {}
    for r in records:
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1

    valid = [r for r in records if r.is_valid]

    lat = distribution([r.wall_ms for r in valid])
    ttft = distribution([r.ttft_ms for r in valid if r.ttft_ms is not None])
    gtps = distribution([r.gen_tps for r in valid if r.gen_tps is not None])
    ptps = distribution([r.prompt_tps for r in valid if r.prompt_tps is not None])

    scored = [r.accuracy for r in valid if r.accuracy is not None]
    accuracy = sum(scored) / len(scored) if scored else None

    throughput = None
    if wall_clock_s and wall_clock_s > 0 and valid:
        throughput = len(valid) / wall_clock_s

    return CellSummary(
        model=first.model,
        task=first.task,
        num_ctx=first.num_ctx,
        concurrency=first.concurrency,
        schema_constrained=first.schema_constrained,
        n_runs=len(records),
        n_valid=len(valid),
        outcomes=outcomes,
        latency_ms=lat.to_dict() if lat else None,
        ttft_ms=ttft.to_dict() if ttft else None,
        gen_tps=gtps.to_dict() if gtps else None,
        prompt_tps=ptps.to_dict() if ptps else None,
        accuracy_mean=accuracy,
        wall_clock_s=wall_clock_s,
        throughput_rps=throughput,
    )


def record_from(judgement: Judgement, gen, *, model: str, task: str,
                case_id: str, concurrency: int) -> RunRecord:
    """Build the persisted row from a judged generation."""
    return RunRecord(
        model=model,
        task=task,
        case_id=case_id,
        num_ctx=gen.num_ctx,
        concurrency=concurrency,
        schema_constrained=gen.schema_constrained,
        outcome=judgement.outcome.value,
        detail=judgement.detail,
        wall_ms=gen.wall_ms,
        ttft_ms=gen.ttft_ms,
        gen_tps=gen.gen_tps,
        prompt_tps=gen.prompt_tps,
        eval_count=gen.eval_count,
        prompt_eval_count=gen.prompt_eval_count,
        done_reason=gen.done_reason,
        num_predict=gen.num_predict,
        load_ms=gen.load_ms,
        accuracy=judgement.accuracy,
        accuracy_detail=judgement.accuracy_detail,
        error=gen.error,
    )
