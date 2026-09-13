"""Result files and the human-readable report.

Two outputs, deliberately different in kind:

  JSON      every run row, with its outcome and the environment that produced
            it. The evidence. Nothing is discarded, including failures -
            especially including failures, since the failure breakdown is
            what tells you whether a latency figure means anything.

  Markdown  a reading of that evidence. Every table shows n_valid/n_runs
            beside any timing, so a fast-looking cell backed by two valid
            runs out of twenty cannot be skimmed as a good result.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from .metrics import CellSummary, RunRecord

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"


def _default(obj):
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    return str(obj)


def write_json(payload: dict, name: str, *, results_dir: Path | None = None
               ) -> Path:
    directory = results_dir or RESULTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=_default, ensure_ascii=False)
    return path


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


# --- markdown ------------------------------------------------------------

def _fmt(value, suffix: str = "", digits: int = 0) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def _cell_row(cell: CellSummary) -> str:
    lat = cell.latency_ms
    ttft = cell.ttft_ms
    tps = cell.gen_tps
    return (
        f"| {cell.task} | {cell.num_ctx} | {cell.concurrency} "
        f"| {'yes' if cell.schema_constrained else 'no'} "
        f"| {cell.n_valid}/{cell.n_runs} "
        f"| {cell.validity_rate:.0%} "
        f"| {_fmt(lat['p50'] if lat else None)} "
        f"| {_fmt(lat['p95'] if lat else None)} "
        f"| {_fmt(ttft['p50'] if ttft else None)} "
        f"| {_fmt(tps['mean'] if tps else None, digits=1)} "
        f"| {_fmt(cell.throughput_rps, digits=2)} "
        f"| {_fmt((cell.accuracy_mean * 100) if cell.accuracy_mean is not None else None, '%', 1)} |"
    )


_CELL_HEADER = (
    "| task | ctx | conc | schema | valid | rate | p50 ms | p95 ms "
    "| TTFT p50 | gen tok/s | req/s | accuracy |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|"
)


def markdown_report(payload: dict) -> str:
    """Render the full run to markdown."""
    env = payload.get("environment", {})
    gpu = env.get("gpu", {})
    lines: list[str] = []
    add = lines.append

    add("# NQ-027 - local model benchmark")
    add("")
    add(f"Run: `{payload.get('run_id')}`  ")
    add(f"Captured: {env.get('captured_at_utc')}  ")
    add(f"Commit: `{env.get('git_commit')}`"
        + ("  **(tree was dirty - not exactly reproducible)**"
           if env.get("git_dirty") else ""))
    add("")
    add("## Environment")
    add("")
    add(f"- GPU: {gpu.get('name')} - {gpu.get('memory_total_mib')} MiB total, "
        f"{gpu.get('memory_free_mib')} MiB free at capture")
    add(f"- Driver: {gpu.get('driver_version')}")
    add(f"- Ollama: {env.get('ollama_version')} at {env.get('ollama_host')}")
    add(f"- OLLAMA_* environment: "
        f"`{json.dumps(env.get('ollama_env', {}))}`")
    add(f"- Python {env.get('python_version')} on {env.get('platform')}")
    add(f"- Seed: {payload.get('seed')}, temperature 0")
    add("")

    add("## Method")
    add("")
    add("A run counts as valid only if it passed, in order: transport, "
        "truncation (`done_reason != \"length\"`), non-empty after reasoning "
        "is stripped, JSON parse, schema validation against the real "
        "`TripSpec`, and a task-specific usability check. Latency, TTFT and "
        "throughput are computed over valid runs only; a cell with no valid "
        "run reports `n/a` rather than a number.")
    add("")

    # --- probes ---
    probes = payload.get("probes", {})
    if probes:
        add("## Stage A - residency probe")
        add("")
        add("| model | quant | params | ctx | in VRAM | VRAM MiB "
            "| free after load | headroom | smoke |")
        add("|---|---|---|---|---|---|---|---|---|")
        for model, probe in probes.items():
            ident = probe.get("identity", {})
            for p in probe.get("probes", []):
                add(
                    f"| {model} | {ident.get('quantization_level')} "
                    f"| {ident.get('parameter_size')} | {p.get('num_ctx')} "
                    f"| {'yes' if p.get('fully_resident') else 'NO'} "
                    f"| {_fmt(p.get('vram_mib'), digits=0)} "
                    f"| {_fmt(p.get('gpu_free_mib_after_load'))} "
                    f"| {'ok' if p.get('headroom_ok') else 'TIGHT'} "
                    f"| {p.get('smoke_outcome')} |"
                )
        add("")

    # --- sweep ---
    sweep = payload.get("sweep", {})
    if sweep:
        add("## Stage B - performance matrix")
        add("")
        for model, cells in sweep.items():
            add(f"### {model}")
            add("")
            add(_CELL_HEADER)
            for cell in cells:
                add(_cell_row(CellSummary(**_cell_kwargs(cell))))
            add("")

    # --- quality ---
    quality = payload.get("quality", {})
    if quality:
        add("## Stage C - quality evaluation (full case sets)")
        add("")
        for model, cells in quality.items():
            add(f"### {model}")
            add("")
            add(_CELL_HEADER)
            for cell in cells:
                add(_cell_row(CellSummary(**_cell_kwargs(cell))))
            add("")

    # --- embeddings ---
    embeddings = payload.get("embeddings")
    if embeddings:
        add("## Stage D - embedding models")
        add("")
        add("| model | dimension | consistent | normalised | VRAM MiB "
            "| single p50 ms | texts/s | similarity |")
        add("|---|---|---|---|---|---|---|---|")
        for cand in embeddings.get("candidates", []):
            single = cand.get("single_latency_ms") or {}
            add(
                f"| {cand.get('model')} | **{cand.get('dimension')}** "
                f"| {'yes' if cand.get('dimension_consistent') else 'NO'} "
                f"| {'yes' if cand.get('normalised') else 'no'} "
                f"| {_fmt(cand.get('vram_mib'), digits=0)} "
                f"| {_fmt(single.get('p50'), digits=1)} "
                f"| {_fmt(cand.get('texts_per_second'), digits=1)} "
                f"| {cand.get('similarity_score')} |"
            )
        add("")

    # --- gates ---
    verdicts = payload.get("verdicts")
    if verdicts:
        add("## Stage E - ADR-012 gates")
        add("")
        for verdict in verdicts:
            mark = "ELIGIBLE" if verdict["eligible"] else "NOT ELIGIBLE"
            add(f"### {verdict['model']} - {mark}")
            add("")
            add("| gate | status | measured | threshold |")
            add("|---|---|---|---|")
            for gate in verdict["gates"]:
                add(f"| {gate['name']} | {gate['status'].upper()} "
                    f"| {gate['measured']} | {gate['threshold']} |")
            add("")

    ranking = payload.get("ranking")
    if ranking:
        add("## Ranking")
        add("")
        add("| # | model | eligible | critical-field accuracy "
            "| schema validity | extract p95 |")
        add("|---|---|---|---|---|---|")
        for i, row in enumerate(ranking, 1):
            acc = row.get("critical_field_accuracy")
            val = row.get("schema_validity")
            add(f"| {i} | {row['model']} "
                f"| {'yes' if row['eligible'] else 'no - ' + ', '.join(row['failed_gates'])} "
                f"| {_fmt(acc * 100 if acc is not None else None, '%', 1)} "
                f"| {_fmt(val * 100 if val is not None else None, '%', 1)} "
                f"| {_fmt(row.get('extract_p95_ms'), ' ms', 0)} |")
        add("")

    add("---")
    add("")
    add("Generated by `ai/benchmarks/run_benchmark.py`. The benchmark "
        "measures; it does not choose. The decision is ADR-012.")
    return "\n".join(lines)


_CELL_FIELDS = {
    "model", "task", "num_ctx", "concurrency", "schema_constrained",
    "n_runs", "n_valid", "outcomes", "latency_ms", "ttft_ms", "gen_tps",
    "prompt_tps", "accuracy_mean", "wall_clock_s", "throughput_rps",
}


def _cell_kwargs(cell: dict) -> dict:
    """Rebuild a CellSummary from its serialised form."""
    return {k: v for k, v in cell.items() if k in _CELL_FIELDS}


def write_markdown(payload: dict, name: str, *,
                   results_dir: Path | None = None) -> Path:
    directory = results_dir or RESULTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(markdown_report(payload), encoding="utf-8")
    return path


def write_runs(records: list[RunRecord], name: str, *,
               results_dir: Path | None = None) -> Path:
    """Every individual run, failures included."""
    return write_json({"runs": [r.to_dict() for r in records]}, name,
                      results_dir=results_dir)
