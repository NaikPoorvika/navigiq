"""Draft ADR-012 from a benchmark result file.

    python ai/benchmarks/select_model.py results/<run>.json

Applies the gates to the recorded evidence and writes a decision record with
the measured numbers already filled in, to `docs/adr/ADR-012-model-selection.md`.

It does NOT decide. The draft it writes leaves the decision line blank and
lists what passed, what failed and what was never measured. A human reads it,
chooses, and pastes the outcome into DECISIONS.md. Automating the choice would
put the model selection in the hands of whichever thresholds happened to be
typed into gates.py, which is precisely the judgement that should stay human.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nq027 import gates
from nq027.metrics import CellSummary
from nq027.report import _cell_kwargs

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = REPO_ROOT / "docs" / "adr" / "ADR-012-model-selection.md"


def _cells(rows: list[dict]) -> list[CellSummary]:
    return [CellSummary(**_cell_kwargs(r)) for r in rows]


def _find(cells: list[CellSummary], **criteria) -> CellSummary | None:
    for cell in cells:
        if all(getattr(cell, k) == v for k, v in criteria.items()):
            return cell
    return None


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _ms(value) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


def _rate(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def draft(payload: dict, evidence_path: str) -> str:
    env = payload.get("environment", {})
    gpu = env.get("gpu", {})
    probes = payload.get("probes", {})
    quality = payload.get("quality", {})
    sweep = payload.get("sweep", {})
    embeddings = payload.get("embeddings") or {}

    lines: list[str] = []
    add = lines.append

    add("# ADR-012: Local model selection")
    add("")
    add("**Status:** DRAFT - awaiting a human decision  ")
    add("**Owner:** B1  ")
    # The literal path passed on the command line, not reconstructed from
    # run_id: a merged file's run_id and filename need not match, and a
    # citation pointing at a file that does not exist is worse than no
    # citation.
    add(f"**Evidence:** `{evidence_path}`  ")
    add(f"**Measured:** {env.get('captured_at_utc')} on "
        f"{gpu.get('name')} ({gpu.get('memory_total_mib')} MiB), "
        f"driver {gpu.get('driver_version')}, Ollama {env.get('ollama_version')}  ")
    add(f"**Commit:** `{env.get('git_commit')}`"
        + ("  **(dirty tree)**" if env.get("git_dirty") else ""))
    add("")
    add("## Decision")
    add("")
    add("**Generation model:** _(not yet decided - fill in and set Status to "
        "Accepted)_  ")
    add("**Embedding model:** _(not yet decided)_  ")
    add("**Embedding dimension `vector(N)`:** _(not yet decided)_")
    add("")
    add("This record fixes two things that are expensive to reverse: the "
        "resident generation model every LLM task class routes to through "
        "NQ-028's gateway, and the embedding model - and with it the "
        "`vector(N)` dimension hard-coded in NQ-034's migration. Changing `N` "
        "later means re-embedding the corpus and rebuilding the HNSW index.")
    add("")

    # --- candidates ---
    add("## Candidates, as measured")
    add("")
    add("| model | quant | VRAM @8k | resident | schema validity "
        "| critical-field accuracy | extract p95 | eligible |")
    add("|---|---|---|---|---|---|---|---|")

    for row in payload.get("ranking", []):
        model = row["model"]
        probe = probes.get(model, {})
        ident = probe.get("identity", {})
        at_8k = next((p for p in probe.get("probes", [])
                      if p.get("num_ctx") == 8192), {})
        eligible = ("yes" if row["eligible"]
                    else "no - " + ", ".join(row["failed_gates"]))
        add(f"| `{model}` | {ident.get('quantization_level', '?')} "
            f"| {at_8k.get('vram_mib', 'n/a')} MiB "
            f"| {'yes' if at_8k.get('fully_resident') else 'NO'} "
            f"| {_pct(row.get('schema_validity'))} "
            f"| {_pct(row.get('critical_field_accuracy'))} "
            f"| {_ms(row.get('extract_p95_ms'))} "
            f"| {eligible} |")
    add("")

    # --- schema vs no schema ---
    add("## Structured output: schema-constrained vs unconstrained")
    add("")
    add("Both columns are `tripspec_extract` over the same 50 cases, same "
        "seed, same context. The only difference is whether Ollama was given "
        "the TripSpec JSON Schema as a decoding grammar.")
    add("")
    add("| model | constrained validity | unconstrained validity "
        "| constrained accuracy | unconstrained accuracy |")
    add("|---|---|---|---|---|")
    for model, rows in quality.items():
        cells = _cells(rows)
        on = _find(cells, task="tripspec_extract", schema_constrained=True)
        off = _find(cells, task="tripspec_extract", schema_constrained=False)
        add(f"| `{model}` "
            f"| {_pct(on.validity_rate) if on else 'n/a'} "
            f"| {_pct(off.validity_rate) if off else 'n/a'} "
            f"| {_pct(on.accuracy_mean) if on else 'n/a'} "
            f"| {_pct(off.accuracy_mean) if off else 'n/a'} |")
    add("")

    # --- concurrency and context, from the sweep matrix ---
    if sweep:
        add("## Concurrency and context (the sweep matrix)")
        add("")
        add("`tripspec_extract`, schema-constrained, at the concurrency "
            "budget context - p95 latency and throughput per concurrency "
            "level. Flat throughput across levels means the server is "
            "queueing requests rather than running them in parallel; rising "
            "p95 in step with concurrency is the queue, not a slowdown.")
        add("")
        add("| model | conc 1 p95 | conc 2 p95 | conc 4 p95 | throughput req/s (1 / 2 / 4) |")
        add("|---|---|---|---|---|")
        for model, rows in sweep.items():
            cells = _cells(rows)
            by_conc = {c.concurrency: c for c in cells
                      if c.task == "tripspec_extract"
                      and c.num_ctx == gates.TRIPSPEC_BUDGET_CONTEXT
                      and c.schema_constrained}
            if not by_conc:
                continue
            p95 = {k: (v.latency_ms["p95"] if v.latency_ms else None)
                   for k, v in by_conc.items()}
            tput = {k: v.throughput_rps for k, v in by_conc.items()}
            add(f"| `{model}` "
                f"| {_ms(p95.get(1))} | {_ms(p95.get(2))} | {_ms(p95.get(4))} "
                f"| {_rate(tput.get(1))} / {_rate(tput.get(2))} / "
                f"{_rate(tput.get(4))} |")
        add("")
        add("Context size (4096 / 8192 / 16384) showed no measurable latency "
            "cost at these prompt lengths for the models that were swept "
            "across all three; longer context costs VRAM at load time "
            "instead (see the residency probe and `embedding_headroom`).")
        add("")

    # --- embeddings ---
    if embeddings:
        add("## Embedding models")
        add("")
        add("Dimension is the length of a vector this machine returned, not a "
            "figure from a model card.")
        add("")
        add("| model | dimension | VRAM | single p50 | texts/s | "
            "similarity checks |")
        add("|---|---|---|---|---|---|")
        for cand in embeddings.get("candidates", []):
            single = cand.get("single_latency_ms") or {}
            add(f"| `{cand.get('model')}` | **{cand.get('dimension')}** "
                f"| {cand.get('vram_mib')} MiB "
                f"| {single.get('p50')} ms "
                f"| {cand.get('texts_per_second')} "
                f"| {cand.get('similarity_score')} |")
        add("")

    # --- gates ---
    add("## Gates")
    add("")
    add("Thresholds are defined once, in `ai/benchmarks/nq027/gates.py`. "
        "`UNKNOWN` means the evidence needed to judge the gate is missing, "
        "and does not count as a pass.")
    add("")
    for verdict in payload.get("verdicts", []):
        add(f"### `{verdict['model']}` - "
            f"{'ELIGIBLE' if verdict['eligible'] else 'NOT ELIGIBLE'}")
        add("")
        add("| gate | status | measured | threshold |")
        add("|---|---|---|---|")
        for gate in verdict["gates"]:
            add(f"| {gate['name']} | {gate['status'].upper()} "
                f"| {gate['measured']} | {gate['threshold']} |")
        add("")

    # --- what is not covered ---
    add("## What this evidence does not cover")
    add("")
    add("- Concurrency figures reflect the Ollama server's parallelism as "
        "configured on this machine at measurement time; the recorded "
        "`OLLAMA_*` environment is in the result file.")
    add("- Accuracy is measured on authored cases, not on production traffic. "
        "NQ-030 builds the eval set that supersedes this.")
    add("- Every figure is single-seed at temperature 0. Reproducible, but not "
        "a variance estimate.")
    add("")
    add("---")
    add("")
    add("Generated by `ai/benchmarks/select_model.py` from the run named "
        "above. The benchmark measures; the decision is human.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft ADR-012 from results")
    parser.add_argument("results", help="path to a benchmark result JSON")
    parser.add_argument("--out", default=str(ADR_PATH))
    args = parser.parse_args()

    with open(args.results, encoding="utf-8") as fh:
        payload = json.load(fh)

    # Re-apply the gates rather than trusting what the run recorded, so a
    # threshold change takes effect without re-running the benchmark.
    verdicts, quality_by_model = [], {}
    for model in payload.get("probes", {}):
        sweep_cells = _cells(payload.get("sweep", {}).get(model, []))
        quality_cells = _cells(payload.get("quality", {}).get(model, []))
        quality_by_model[model] = quality_cells
        verdicts.append(gates.evaluate(model, payload["probes"][model],
                                       sweep_cells, quality_cells))
    payload["verdicts"] = [v.to_dict() for v in verdicts]
    payload["ranking"] = gates.rank(verdicts, quality_by_model)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    evidence_path = Path(args.results).as_posix()
    try:
        evidence_path = Path(args.results).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        pass          # results file lives outside the repo; keep the raw path
    out.write_text(draft(payload, evidence_path), encoding="utf-8")

    print(f"ADR-012 draft -> {out}")
    eligible = [v.model for v in verdicts if v.eligible]
    if eligible:
        print(f"eligible candidates: {', '.join(eligible)}")
        print("Read the draft, decide, then paste the decision into "
              "DECISIONS.md.")
    else:
        print("NO candidate passed every gate. ADR-012 cannot be closed on "
              "this evidence.")
        for v in verdicts:
            print(f"  {v.model}: {', '.join(v.failed_gates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
