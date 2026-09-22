"""NQ-029 extraction eval runner - real qwen3:14b through the real gateway.

    python ai/evals/nq029/run.py

It calls `extract_trip_draft()`, the same function the API calls, through a
recording wrapper around the configured `OllamaGateway`. Nothing about the
prompt, the schema, the temperature or the parsing is re-implemented here,
so a result from this runner is a statement about the production path and
not about a copy of it that happens to live in the eval.

Configuration comes from the normal settings (OLLAMA_HOST, OLLAMA_GEN_MODEL,
...). Nothing is hard-coded; the model actually used is recorded in the
report rather than assumed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
# Needed only so `app.config` imports; the eval never opens a connection.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq_user:navigiq_password@localhost:5433/navigiq",
)
sys.path.insert(0, str(HERE))

from app.llm import LLMError, build_llm_gateway  # noqa: E402
from app.llm.extraction import (  # noqa: E402
    PROMPT_VERSION,
    TripDraftExtractionFailed,
    extract_trip_draft,
)
from app.llm.types import ChatMessage, Embeddings, Generation  # noqa: E402

from cases import CASES  # noqa: E402
from score import CaseResult, score_case, summarise  # noqa: E402


class RecordingGateway:
    """Delegates to the real gateway and keeps the last raw Generation.

    The eval needs the model's unvalidated text to measure coordinate
    leakage and malformed times. Rather than re-implementing the call to get
    at it, it is captured on the way past.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.last: Generation | None = None

    @property
    def generation_model(self) -> str:
        return self._inner.generation_model

    @property
    def embedding_model(self) -> str:
        return self._inner.embedding_model

    @property
    def embedding_dimension(self) -> int:
        return self._inner.embedding_dimension

    async def generate(self, messages: Sequence[ChatMessage], **kwargs: Any) -> Generation:
        self.last = None
        generation = await self._inner.generate(messages, **kwargs)
        self.last = generation
        return generation

    async def embed(self, texts: Sequence[str]) -> Embeddings:
        return await self._inner.embed(texts)

    async def aclose(self) -> None:
        await self._inner.aclose()


async def run_case(case, gateway: RecordingGateway) -> CaseResult:
    started = time.perf_counter()
    draft = None
    failure_reason = None
    try:
        extraction = await extract_trip_draft(case.text, gateway=gateway)
        draft = extraction.draft.model_dump(mode="json")
    except TripDraftExtractionFailed as exc:
        failure_reason = exc.reason
    except LLMError as exc:
        failure_reason = exc.code
    latency_ms = (time.perf_counter() - started) * 1000

    raw = gateway.last.text if gateway.last is not None else None
    return score_case(case, draft=draft, raw_text=raw,
                      failure_reason=failure_reason, latency_ms=latency_ms)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", default=None,
                        help="run only these case ids (repeatable)")
    parser.add_argument("--out", default=str(HERE / "results"),
                        help="directory for results.json and report.md")
    args = parser.parse_args()

    cases = CASES
    if args.case:
        wanted = set(args.case)
        cases = [c for c in CASES if c.id in wanted]
        if not cases:
            print(f"no cases matched {sorted(wanted)}", file=sys.stderr)
            return 2

    from app.config import settings

    gateway = RecordingGateway(build_llm_gateway(settings))
    results: list[CaseResult] = []
    try:
        for index, case in enumerate(cases, 1):
            print(f"[{index}/{len(cases)}] {case.id} ...",
                  end=" ", flush=True)
            result = await run_case(case, gateway)
            results.append(result)
            verdict = ("ok" if result.ok else f"FAILED({result.failure_reason})")
            print(f"{verdict} {result.correct}/{result.total} "
                  f"{result.latency_ms:.0f}ms")
    finally:
        await gateway.aclose()

    summary = summarise(results)
    meta = {
        "task": "NQ-029",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.OLLAMA_GEN_MODEL,
        "num_ctx": settings.OLLAMA_NUM_CTX,
        "prompt_version": PROMPT_VERSION,
        "ollama_host": settings.OLLAMA_HOST,
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "summary": summary,
        "cases": [
            {
                "case_id": r.case_id,
                "case_class": r.case_class,
                "ok": r.ok,
                "failure_reason": r.failure_reason,
                "checks": [{"field": f, "ok": ok, "got": got}
                           for f, ok, got in r.checks],
                "hallucinated": r.hallucinated,
                "coordinate_leak": r.coordinate_leak,
                "malformed_times": r.malformed_times,
                "unsupported_date_phrase": r.unsupported_date_phrase,
                "latency_ms": round(r.latency_ms, 1),
                "raw": r.raw_text,
            }
            for r in results
        ],
    }
    (out_dir / "results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(
        render_report(meta, summary, results), encoding="utf-8")

    print()
    print(_summary_lines(summary))
    print(f"\nwritten to {out_dir}")
    return 0


def _pct(value: float | None) -> str:
    return "not measured" if value is None else f"{value * 100:.1f}%"


def _summary_lines(s: Mapping[str, Any]) -> str:
    return "\n".join([
        f"schema validity          {_pct(s['schema_validity_rate'])}"
        f"  ({s['schema_valid']}/{s['cases']})",
        f"critical-field accuracy  {_pct(s['critical_field_accuracy'])}"
        f"  ({s['critical_field_correct']}/{s['critical_field_checks']})",
        f"hallucination rate       {_pct(s['hallucination_rate'])}"
        f"  ({s['hallucination_cases']}/{s['schema_valid']})",
        f"coordinate leakage       {_pct(s['coordinate_leakage_rate'])}"
        f"  ({s['coordinate_leak_cases']} responses)",
        f"malformed-time rate      {_pct(s['malformed_time_rate'])}"
        f"  ({s['malformed_time_cases']}/{s['responses_with_a_time']})",
        f"unsupported-date rate    {_pct(s['unsupported_date_phrase_rate'])}"
        f"  ({s['unsupported_date_phrase_cases']}"
        f"/{s['responses_with_a_date_phrase']})",
    ])


def render_report(meta: Mapping[str, Any], summary: Mapping[str, Any],
                  results: list[CaseResult]) -> str:
    lines = [
        "# NQ-029 extraction evaluation",
        "",
        f"- model: `{meta['model']}`  (selected by ADR-012, not re-evaluated here)",
        f"- prompt: `tripdraft_extraction_{meta['prompt_version']}.md`",
        f"- context: {meta['num_ctx']}",
        f"- run at: {meta['run_at']}",
        f"- cases: {summary['cases']}",
        "",
        "Measured through `extract_trip_draft()`, the same function the API",
        "calls. Coordinate leakage and malformed times are measured on the",
        "raw model response, before TripDraft drops or rejects anything.",
        "",
        "## Summary",
        "",
        "| metric | value | basis |",
        "| --- | --- | --- |",
        f"| schema validity | {_pct(summary['schema_validity_rate'])} | "
        f"{summary['schema_valid']}/{summary['cases']} cases |",
        f"| critical-field accuracy | {_pct(summary['critical_field_accuracy'])} | "
        f"{summary['critical_field_correct']}/{summary['critical_field_checks']} "
        f"field checks |",
        f"| hallucination rate | {_pct(summary['hallucination_rate'])} | "
        f"{summary['hallucination_cases']}/{summary['schema_valid']} valid drafts |",
        f"| coordinate leakage | {_pct(summary['coordinate_leakage_rate'])} | "
        f"{summary['coordinate_leak_cases']} raw responses |",
        f"| malformed-time rate | {_pct(summary['malformed_time_rate'])} | "
        f"{summary['malformed_time_cases']}/{summary['responses_with_a_time']} "
        f"responses that contained a time |",
        f"| unsupported-date-phrase rate | "
        f"{_pct(summary['unsupported_date_phrase_rate'])} | "
        f"{summary['unsupported_date_phrase_cases']}"
        f"/{summary['responses_with_a_date_phrase']} responses that contained "
        f"a date phrase |",
        f"| mean latency | {summary['latency_ms_mean']:.0f} ms | per case |",
        "",
    ]
    if summary["failures_by_reason"]:
        lines += ["Extraction failures by reason: "
                  + ", ".join(f"`{k}` x{v}" for k, v in
                              sorted(summary["failures_by_reason"].items())),
                  ""]

    lines += ["## Per case", "",
              "| case | class | draft | fields | issues |",
              "| --- | --- | --- | --- | --- |"]
    for r in results:
        issues = []
        if r.hallucinated:
            issues.append("invented " + ", ".join(r.hallucinated))
        if r.coordinate_leak:
            issues.append("COORDINATE LEAK")
        if r.malformed_times:
            issues.append("bad time: " + ", ".join(r.malformed_times))
        if r.unsupported_date_phrase:
            issues.append(f"unsupported date {r.unsupported_date_phrase!r}")
        wrong = [f for f, ok, _ in r.checks if not ok]
        if wrong:
            issues.append("missed " + ", ".join(wrong))
        lines.append(
            f"| `{r.case_id}` | {r.case_class} | "
            f"{'yes' if r.ok else 'NO (' + str(r.failure_reason) + ')'} | "
            f"{r.correct}/{r.total} | {'; '.join(issues) or '-'} |")

    lines += ["", "## Misses in detail", ""]
    any_detail = False
    for r in results:
        wrong = [(f, got) for f, ok, got in r.checks if not ok]
        if not wrong and not r.hallucinated:
            continue
        any_detail = True
        lines.append(f"**`{r.case_id}`** ({r.case_class})")
        for f, got in wrong:
            lines.append(f"- expected `{f}`, got {got}")
        for f in r.hallucinated:
            lines.append(f"- invented `{f}` (not in the request)")
        lines.append("")
    if not any_detail:
        lines.append("None.")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
