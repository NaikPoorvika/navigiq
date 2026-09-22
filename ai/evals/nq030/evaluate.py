"""NQ-030 evaluation runner - v1 vs v2, on held-out and dev data.

    python ai/evals/nq030/evaluate.py                 # full matrix
    python ai/evals/nq030/evaluate.py --dataset heldout --prompt v2

Datasets:
  heldout  ai/evals/nq030/heldout.json - written after v2 was frozen and
           never used to change it. The honest number.
  dev      the NQ-029 cases, re-scored with the NQ-030 scorer. v2 was
           designed against these, so v2's dev score is optimistic by
           construction and is reported only for context.

Like the NQ-029 runner, this calls `extract_trip_draft()` - the production
path - through a recording wrapper around the configured gateway, so the
prompt, schema, temperature, seed and parsing are the shipped ones.

REPEATS. qwen3:14b on Ollama is not bit-reproducible even at temperature 0
with a fixed seed: re-running the NQ-029 baseline changed 2 of 26 raw
responses. Every (dataset, prompt) pair is therefore run --repeats times
(default 3) and reported as mean and min-max, and cases whose outcome
changes between repeats are listed as unstable rather than silently
averaged.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq_user:navigiq_password@localhost:5433/navigiq",
)

from app.llm import LLMError, build_llm_gateway  # noqa: E402
from app.llm.extraction import (  # noqa: E402
    DEFAULT_SEED,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_TEMPERATURE,
    PROMPT_DIR,
    PROMPT_VERSIONS,
    TripDraftExtractionFailed,
    extract_trip_draft,
)
from app.llm.types import ChatMessage, Embeddings, Generation  # noqa: E402

from scoring import (  # noqa: E402
    BENIGN, CLARIFYING, PLAN_ALTERING, CaseScore, score_case, summarise,
)

HELDOUT_PATH = HERE / "heldout.json"
NQ029_CASES_PATH = REPO / "ai" / "evals" / "nq029" / "cases.py"
DATASETS = ("heldout", "dev")


def sha256(path: Path) -> str:
    """Content hash with line endings normalised, so a CRLF checkout on
    Windows (core.autocrlf) hashes the same as the committed file."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_heldout() -> list[dict]:
    return json.loads(HELDOUT_PATH.read_text(encoding="utf-8"))["cases"]


def load_dev() -> list[dict]:
    """The NQ-029 cases, unchanged, adapted to the NQ-030 case format."""
    spec = importlib.util.spec_from_file_location("nq029_cases",
                                                  NQ029_CASES_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves annotations here
    spec.loader.exec_module(module)
    out = []
    for case in module.CASES:
        expected = {k: (sorted(v) if isinstance(v, set) else v)
                    for k, v in case.expect.items()}
        out.append({"id": case.id, "category": case.case_class,
                    "input": case.text, "expected": expected,
                    "allow": list(case.allow)})
    return out


def load(dataset: str) -> list[dict]:
    return load_heldout() if dataset == "heldout" else load_dev()


class RecordingGateway:
    """Delegates to the real gateway and keeps the last raw Generation."""

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

    async def generate(self, messages: Sequence[ChatMessage], **kw: Any) -> Generation:
        self.last = None
        self.last = await self._inner.generate(messages, **kw)
        return self.last

    async def embed(self, texts: Sequence[str]) -> Embeddings:
        return await self._inner.embed(texts)

    async def aclose(self) -> None:
        await self._inner.aclose()


async def run_one(case: dict, gateway: RecordingGateway,
                  prompt_version: str) -> CaseScore:
    started = time.perf_counter()
    draft, reason = None, None
    try:
        extraction = await extract_trip_draft(
            case["input"], gateway=gateway, prompt_version=prompt_version)
        draft = extraction.draft.model_dump(mode="json")
    except TripDraftExtractionFailed as exc:
        reason = exc.reason
    except LLMError as exc:
        reason = exc.code
    latency = (time.perf_counter() - started) * 1000
    raw = gateway.last.text if gateway.last is not None else None
    return score_case(case, draft=draft, raw_text=raw,
                      failure_reason=reason, latency_ms=latency)


def serialise(scores: list[CaseScore], cases: list[dict]) -> list[dict]:
    inputs = {c["id"]: c["input"] for c in cases}
    return [{
        "case_id": s.case_id, "category": s.category,
        "input": inputs[s.case_id],
        "ok": s.ok, "failure_reason": s.failure_reason, "clean": s.clean,
        "stated": [vars(c) for c in s.stated],
        "unrequested": [vars(u) for u in s.unrequested],
        "plan_altering": s.plan_altering,
        "coordinate_leak": s.coordinate_leak,
        "malformed_times": s.malformed_times,
        "unsupported_date_phrase": s.unsupported_date_phrase,
        "latency_ms": round(s.latency_ms, 1),
        "raw": s.raw_text,
    } for s in scores]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=DATASETS, action="append")
    parser.add_argument("--prompt", choices=PROMPT_VERSIONS, action="append")
    parser.add_argument("--out", default=str(HERE / "results"))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    datasets = args.dataset or list(DATASETS)
    versions = args.prompt or list(PROMPT_VERSIONS)

    from app.config import settings

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    gateway = RecordingGateway(build_llm_gateway(settings))
    runs: dict[str, dict] = {}
    try:
        for dataset in datasets:
            cases = load(dataset)
            for version in versions:
                key = f"{dataset}_{version}"
                repeats = []
                for r in range(1, args.repeats + 1):
                    print(f"== {key} repeat {r}/{args.repeats}: "
                          f"{len(cases)} cases")
                    scores = []
                    for case in cases:
                        s = await run_one(case, gateway, version)
                        scores.append(s)
                        flag = "clean" if s.clean else (
                            "FAILED" if not s.ok else "issues")
                        print(f"   {s.case_id:<32} {flag:<7} "
                              f"{s.latency_ms:6.0f}ms")
                    repeats.append({"summary": summarise(scores),
                                    "cases": serialise(scores, cases)})
                meta = {
                    "task": "NQ-030",
                    "dataset": dataset,
                    "dataset_sha256": sha256(HELDOUT_PATH if dataset == "heldout"
                                             else NQ029_CASES_PATH),
                    "prompt_version": version,
                    "prompt_sha256": sha256(
                        PROMPT_DIR / f"tripdraft_extraction_{version}.md"),
                    "model": settings.OLLAMA_GEN_MODEL,
                    "num_ctx": settings.OLLAMA_NUM_CTX,
                    "temperature": EXTRACTION_TEMPERATURE,
                    "seed": DEFAULT_SEED,
                    "max_tokens": EXTRACTION_MAX_TOKENS,
                    "repeats": args.repeats,
                    "run_at": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"),
                }
                runs[key] = {"meta": meta,
                             "aggregate": aggregate(repeats),
                             "unstable_cases": unstable(repeats),
                             "repeats": repeats}
                (out_dir / f"{key}.json").write_text(
                    json.dumps(runs[key], indent=2, ensure_ascii=False),
                    encoding="utf-8")
    finally:
        await gateway.aclose()

    if all(f"{d}_{v}" in runs for d in datasets for v in ("v1", "v2")):
        (out_dir / "report.md").write_text(render_report(runs, datasets),
                                           encoding="utf-8")
        print(f"\nreport: {out_dir / 'report.md'}")
    return 0




# --- aggregation over repeats ------------------------------------------------------

RATE_KEYS = (
    "schema_validity_rate", "explicit_extraction_accuracy",
    "under_extraction_rate", "wrong_value_rate", "unrequested_case_rate",
    "unrequested_field_rate", "plan_altering_rate", "coordinate_leakage_rate",
    "malformed_time_rate", "unsupported_date_rate", "place_interest_accuracy",
    "clean_rate", "latency_ms_mean",
)


def aggregate(repeats: list[dict]) -> dict:
    """Mean and range of every rate across repeats. A rate that was never
    measured in any repeat stays None."""
    out = {}
    for key in RATE_KEYS:
        values = [r["summary"][key] for r in repeats
                  if r["summary"][key] is not None]
        out[key] = (None if not values else
                    {"mean": sum(values) / len(values),
                     "min": min(values), "max": max(values)})
    return out


def unstable(repeats: list[dict]) -> list[str]:
    """Cases whose clean/unclean outcome differs between repeats."""
    outcomes: dict[str, set[bool]] = {}
    for r in repeats:
        for c in r["cases"]:
            outcomes.setdefault(c["case_id"], set()).add(c["clean"])
    return sorted(k for k, v in outcomes.items() if len(v) > 1)


# --- report ----------------------------------------------------------------------

ROWS = [
    ("Schema validity", "schema_validity_rate"),
    ("Explicit extraction accuracy", "explicit_extraction_accuracy"),
    ("Under-extraction", "under_extraction_rate"),
    ("Wrong value on a stated field", "wrong_value_rate"),
    ("Unrequested fields (share of cases)", "unrequested_case_rate"),
    ("Unrequested fields (share of restraint checks)", "unrequested_field_rate"),
    ("**Plan-altering hallucination** (share of cases)", "plan_altering_rate"),
    ("Coordinate leakage", "coordinate_leakage_rate"),
    ("Malformed time", "malformed_time_rate"),
    ("Unsupported date phrase", "unsupported_date_rate"),
    ("Place/interest accuracy", "place_interest_accuracy"),
    ("Clean cases", "clean_rate"),
]


def fmt(agg: dict | None, ms: bool = False) -> str:
    if agg is None:
        return "not measured"
    if ms:
        return f"{agg['mean']:.0f} ms"
    mean = f"{agg['mean'] * 100:.1f}%"
    if abs(agg["max"] - agg["min"]) < 1e-12:
        return mean
    return f"{mean} ({agg['min'] * 100:.1f}-{agg['max'] * 100:.1f})"


def comparison_table(v1: dict, v2: dict) -> list[str]:
    lines = ["| Metric | v1 (NQ-029) | v2 (NQ-030) |", "| --- | --- | --- |"]
    for label, key in ROWS:
        lines.append(f"| {label} | {fmt(v1['aggregate'][key])} | "
                     f"{fmt(v2['aggregate'][key])} |")
    lines.append(f"| Mean latency | "
                 f"{fmt(v1['aggregate']['latency_ms_mean'], ms=True)} | "
                 f"{fmt(v2['aggregate']['latency_ms_mean'], ms=True)} |")
    sev = [_severity_totals(v1), _severity_totals(v2)]
    lines.append("| Unrequested values, all repeats (benign / clarifying / "
                 f"plan-altering) | {sev[0]} | {sev[1]} |")
    return lines


def _severity_totals(run: dict) -> str:
    totals = {BENIGN: 0, CLARIFYING: 0, PLAN_ALTERING: 0}
    for r in run["repeats"]:
        for k, v in r["summary"]["unrequested_by_severity"].items():
            totals[k] += v
    return f"{totals[BENIGN]} / {totals[CLARIFYING]} / {totals[PLAN_ALTERING]}"


def category_table(v1: dict, v2: dict) -> list[str]:
    lines = [f"| Category | cases | v1 clean (per repeat) | "
             f"v2 clean (per repeat) |", "| --- | --- | --- | --- |"]
    cats = v1["repeats"][0]["summary"]["by_category"]
    for cat, info in cats.items():
        c1 = " / ".join(str(r["summary"]["by_category"][cat]["clean"])
                        for r in v1["repeats"])
        c2 = " / ".join(str(r["summary"]["by_category"][cat]["clean"])
                        for r in v2["repeats"])
        lines.append(f"| {cat} | {info['cases']} | {c1} | {c2} |")
    return lines


def failures(run: dict) -> list[str]:
    """Failures from repeat 1, with each case's outcome across repeats."""
    per_case = {}
    for r in run["repeats"]:
        for c in r["cases"]:
            per_case.setdefault(c["case_id"], []).append(c["clean"])
    lines = []
    for c in run["repeats"][0]["cases"]:
        history = per_case[c["case_id"]]
        if all(history):
            continue
        issues = []
        if not c["ok"]:
            issues.append(f"extraction failed ({c['failure_reason']})")
        for s in c["stated"]:
            if s["status"] != "correct":
                issues.append(f"{s['status']} `{s['field']}` (got {s['got']})")
        for u in c["unrequested"]:
            if u["severity"] != BENIGN:
                issues.append(f"invented `{u['field']}`={u['value']} "
                              f"[{u['severity']}]")
        record = "".join("." if ok else "x" for ok in history)
        lines.append(f"- **`{c['case_id']}`** [{record}] - \"{c['input']}\"")
        lines += [f"  - {i}" for i in issues] or [
            "  - clean in repeat 1; failed in a later repeat"]
    return lines or ["None."]


def render_report(runs: dict, datasets: list[str]) -> str:
    meta = runs[f"{datasets[0]}_v2"]["meta"]
    out = [
        "# NQ-030 evaluation results",
        "",
        f"- model `{meta['model']}`, temperature {meta['temperature']}, "
        f"seed {meta['seed']}, max_tokens {meta['max_tokens']}, "
        f"num_ctx {meta['num_ctx']}",
        f"- {meta['repeats']} repeats per dataset and prompt; rates are the "
        "mean, with the (min-max) range where repeats disagreed",
        f"- run at {meta['run_at']}",
        "- scorer: `ai/evals/nq030/scoring.py`",
        "- per-case history: `.` clean, `x` not clean, one mark per repeat",
        "",
    ]
    titles = {"heldout": "Held-out set - the honest number",
              "dev": "Dev set (the NQ-029 cases) - v2 was designed on these, "
                     "so v2's score here is optimistic by construction"}
    for d in datasets:
        v1, v2 = runs[f"{d}_v1"], runs[f"{d}_v2"]
        n = v1["repeats"][0]["summary"]["cases"]
        out += [f"## {titles[d]}", "",
                f"{n} cases. dataset sha256 "
                f"`{v1['meta']['dataset_sha256'][:16]}`; prompt sha256 "
                f"v1 `{v1['meta']['prompt_sha256'][:16]}`, "
                f"v2 `{v2['meta']['prompt_sha256'][:16]}`.", ""]
        out += comparison_table(v1, v2) + [""]
        out += ["Unstable cases (outcome changed between repeats): "
                f"v1 {', '.join(v1['unstable_cases']) or 'none'}; "
                f"v2 {', '.join(v2['unstable_cases']) or 'none'}.", ""]
        out += ["### Clean cases by category", "",
                "Clean = valid draft, every stated field right, nothing "
                "non-benign invented.", ""]
        out += category_table(v1, v2) + [""]
        out += ["### v2 cases that were not clean", ""] + failures(v2) + [""]
        out += ["### v1 cases that were not clean", ""] + failures(v1) + [""]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
