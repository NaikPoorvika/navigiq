"""NQ-027 benchmark entrypoint.

    python ai/benchmarks/run_benchmark.py --stage all

Stages run cheapest-first so GPU time is not spent on a model that has
already disqualified itself:

    probe    residency and VRAM headroom per context size
    sweep    performance matrix: task x context x concurrency
    quality  full case sets, schema-constrained and unconstrained
    embed    embedding candidates, dimension measured from a real vector
    select   apply the ADR-012 gates to whatever evidence exists

Every stage writes its own JSON under ai/benchmarks/results/ before the next
begins, so an interrupted run keeps the evidence it already gathered.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nq027 import embed as embed_mod
from nq027 import gates, report
from nq027.client import OllamaClient
from nq027.env import capture, model_identity
from nq027.metrics import CellSummary
from nq027.runner import Runner, subset_cases
from nq027.tasks import TASK_IDS, TASK_CLASSES, cases_for, validate_case_file

# Candidates already present locally. Deliberately not a download list: the
# point of stage A is to find which of these the machine can actually run.
DEFAULT_GEN_MODELS = [
    "qwen3:8b",
    "qwen3.5:9b",
    "gemma3:12b",
    "qwen3:14b",
    "mistral-small3.2:24b",
    "llama3:8b",
]

DEFAULT_EMBED_MODELS = ["bge-m3", "nomic-embed-text"]

DEFAULT_CONTEXTS = [4096, 8192, 16384]
DEFAULT_CONCURRENCIES = [1, 2, 4]

# Context and concurrency at which the quality evaluation runs. Fixed so that
# accuracy is compared across models under identical conditions.
QUALITY_CONTEXT = 8192
QUALITY_CONCURRENCY = 1

# Cases per cell in the performance matrix. The matrix measures speed and
# validity; coverage is stage C's job.
SWEEP_CASES_PER_TASK = 3


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NQ-027 model benchmark")
    p.add_argument("--stage", default="all",
                   choices=["probe", "sweep", "quality", "embed", "select",
                            "all"])
    p.add_argument("--models", nargs="*", default=DEFAULT_GEN_MODELS)
    p.add_argument("--embed-models", nargs="*", default=DEFAULT_EMBED_MODELS)
    p.add_argument("--contexts", nargs="*", type=int, default=DEFAULT_CONTEXTS)
    p.add_argument("--concurrencies", nargs="*", type=int,
                   default=DEFAULT_CONCURRENCIES)
    p.add_argument("--tasks", nargs="*", default=list(TASK_IDS))
    p.add_argument("--runs", type=int, default=6,
                   help="requests per performance-matrix cell")
    p.add_argument("--seed", type=int, default=20270927)
    p.add_argument("--host", default="http://localhost:11434")
    p.add_argument("--results-dir", default=None)
    p.add_argument("--label", default="nq027")
    p.add_argument("--resume-from", default=None,
                   help="reuse probe/sweep/quality from an earlier result file")
    return p.parse_args()


def _check_cases() -> None:
    """Fail before touching the GPU if the case files are malformed."""
    problems: list[str] = []
    for task_id in TASK_IDS:
        problems.extend(validate_case_file(task_id))
    if problems:
        print("Case files are invalid:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(2)


def main() -> int:
    args = _parse()
    results_dir = Path(args.results_dir) if args.results_dir else None
    client = OllamaClient(host=args.host)

    _check_cases()

    run_id = f"{args.label}_{report.stamp()}"
    print(f"NQ-027 run {run_id}")

    environment = capture(client).to_dict()
    if environment.get("ollama_version", "").startswith("unavailable"):
        print("Ollama is not reachable at " + args.host, file=sys.stderr)
        return 1

    payload: dict = {
        "run_id": run_id,
        "seed": args.seed,
        "environment": environment,
        "config": {
            "models": args.models,
            "embed_models": args.embed_models,
            "contexts": args.contexts,
            "concurrencies": args.concurrencies,
            "tasks": args.tasks,
            "runs_per_cell": args.runs,
            "quality_context": QUALITY_CONTEXT,
            "quality_concurrency": QUALITY_CONCURRENCY,
            "sweep_cases_per_task": SWEEP_CASES_PER_TASK,
            "stage": args.stage,
        },
        "probes": {},
        "sweep": {},
        "quality": {},
        "embeddings": None,
        "verdicts": [],
        "ranking": [],
    }

    if args.resume_from:
        with open(args.resume_from, encoding="utf-8") as fh:
            previous = json.load(fh)
        merged_any = False
        for key in ("probes", "sweep", "quality", "embeddings"):
            if previous.get(key):
                payload[key] = previous[key]
                merged_any = True
        if not merged_any:
            print(f"  warning: {args.resume_from} carried none of "
                  f"probes/sweep/quality/embeddings - did you pass a "
                  f"*_runs.json file by mistake? Those hold individual run "
                  f"rows only, not stage results.", file=sys.stderr)
        print(f"resumed prior stages from {args.resume_from}")

    runner = Runner(client, seed=args.seed)
    all_records = []
    identities: dict[str, object] = {}
    started = time.perf_counter()

    def _done_cells(section: str) -> set[tuple]:
        """Cells already measured, so a resumed run does not repeat them.

        A long sweep that is interrupted should cost the cell it was in, not
        the hours before it. Keyed on everything that defines a cell.
        """
        done = set()
        for model, cells in payload.get(section, {}).items():
            for cell in cells:
                done.add((model, cell["task"], cell["num_ctx"],
                          cell["concurrency"], cell["schema_constrained"]))
        return done

    done_sweep = _done_cells("sweep")
    done_quality = _done_cells("quality")
    if done_sweep or done_quality:
        print(f"  already measured: {len(done_sweep)} sweep cells, "
              f"{len(done_quality)} quality cells - these are skipped")

    want = {args.stage, "all"}

    # --- stage A ---------------------------------------------------------
    # A resumed probe is not re-run: residency does not change between stages
    # on the same machine, and re-loading every candidate to rediscover that
    # costs minutes of GPU time for no new evidence.
    if payload["probes"] and args.stage in ("all", "probe"):
        print(f"\n== stage A: reusing {len(payload['probes'])} probed models ==")
    elif "probe" in want or args.stage == "all":
        print("\n== stage A: residency probe ==")
        for model in args.models:
            probe = runner.probe(model, args.contexts)
            identities[model] = probe.identity
            payload["probes"][model] = probe.to_dict()
            usable = probe.usable_contexts()
            print(f"  {model}: usable contexts {usable or 'NONE'}")
        report.write_json(payload, f"{run_id}.json", results_dir=results_dir)

    def _identity(model: str):
        if model not in identities:
            identities[model] = model_identity(client, model)
        return identities[model]

    def _usable(model: str) -> list[int]:
        probe = payload["probes"].get(model)
        if not probe:
            return args.contexts
        return probe.get("usable_contexts", [])

    survivors = [m for m in args.models if _usable(m)]
    if payload["probes"]:
        dropped = [m for m in args.models if m not in survivors]
        if dropped:
            print(f"  dropped before sweep (no usable context): {dropped}")

    # --- stage B ---------------------------------------------------------
    if ("sweep" in want or args.stage == "all") and survivors:
        print("\n== stage B: performance matrix ==")
        for model in survivors:
            identity = _identity(model)
            think = Runner.think_setting(identity)
            contexts = [c for c in args.contexts if c in _usable(model)]
            cells: list[dict] = list(payload["sweep"].get(model, []))
            payload["sweep"][model] = cells
            print(f"  {model} (thinking_disabled={think is False})")
            warmed: set[int] = set()
            for num_ctx in contexts:
                for task_id in args.tasks:
                    task = TASK_CLASSES[task_id]
                    cases = subset_cases(task_id, SWEEP_CASES_PER_TASK)
                    constrained = task.schema is not None
                    for conc in args.concurrencies:
                        key = (model, task_id, num_ctx, conc, constrained)
                        if key in done_sweep:
                            continue
                        if num_ctx not in warmed:
                            runner.warmup(model, num_ctx, think)
                            warmed.add(num_ctx)
                        summary, records = runner.run_cell(
                            model=model, task=task, cases=cases,
                            num_ctx=num_ctx, concurrency=conc,
                            runs=args.runs, constrained=constrained,
                            think=think,
                        )
                        cells.append(summary.to_dict())
                        all_records.extend(records)
                        # Written per cell: an interrupted sweep keeps
                        # everything up to the cell it was in.
                        report.write_json(payload, f"{run_id}.json",
                                          results_dir=results_dir)
            client.unload(model)

    # --- stage C ---------------------------------------------------------
    if ("quality" in want or args.stage == "all") and survivors:
        print("\n== stage C: quality evaluation ==")
        for model in survivors:
            if QUALITY_CONTEXT not in _usable(model):
                print(f"  {model}: skipped, ctx {QUALITY_CONTEXT} not usable")
                continue
            identity = _identity(model)
            think = Runner.think_setting(identity)
            cells = list(payload["quality"].get(model, []))
            payload["quality"][model] = cells
            print(f"  {model}")
            warmed = False
            for task_id in args.tasks:
                task = TASK_CLASSES[task_id]
                cases = cases_for(task_id)
                modes = [task.schema is not None]
                # The schema-vs-no-schema comparison NQ-027 requires, run on
                # the two classes whose output the planner consumes directly.
                if task_id in ("tripspec_extract", "tripspec_modify"):
                    modes = [True, False]
                for constrained in modes:
                    key = (model, task_id, QUALITY_CONTEXT,
                           QUALITY_CONCURRENCY, constrained)
                    if key in done_quality:
                        continue
                    if not warmed:
                        runner.warmup(model, QUALITY_CONTEXT, think)
                        warmed = True
                    summary, records = runner.run_cell(
                        model=model, task=task, cases=cases,
                        num_ctx=QUALITY_CONTEXT,
                        concurrency=QUALITY_CONCURRENCY,
                        runs=len(cases), constrained=constrained, think=think,
                    )
                    cells.append(summary.to_dict())
                    all_records.extend(records)
                    report.write_json(payload, f"{run_id}.json",
                                      results_dir=results_dir)
            client.unload(model)

    # --- stage D ---------------------------------------------------------
    if "embed" in want or args.stage == "all":
        print("\n== stage D: embedding models ==")
        results = []
        for model in args.embed_models:
            print(f"  {model}")
            result = embed_mod.benchmark(client, model)
            print(f"    dimension={result.dimension} ok={result.ok} "
                  f"{result.error or ''}")
            results.append(result)
            client.unload(model)
        payload["embeddings"] = embed_mod.compare(results)
        report.write_json(payload, f"{run_id}.json", results_dir=results_dir)

    # --- stage E ---------------------------------------------------------
    print("\n== stage E: ADR-012 gates ==")
    verdicts = []
    quality_by_model: dict[str, list[CellSummary]] = {}
    for model in args.models:
        sweep_cells = [_cell(c) for c in payload["sweep"].get(model, [])]
        quality_cells = [_cell(c) for c in payload["quality"].get(model, [])]
        quality_by_model[model] = quality_cells
        verdict = gates.evaluate(model, payload["probes"].get(model, {}),
                                 sweep_cells, quality_cells)
        verdicts.append(verdict)
        mark = "ELIGIBLE" if verdict.eligible else "not eligible"
        print(f"  {model}: {mark}"
              + (f" ({', '.join(verdict.failed_gates)})"
                 if verdict.failed_gates else ""))

    payload["verdicts"] = [v.to_dict() for v in verdicts]
    payload["ranking"] = gates.rank(verdicts, quality_by_model)
    payload["elapsed_s"] = round(time.perf_counter() - started, 1)

    json_path = report.write_json(payload, f"{run_id}.json",
                                  results_dir=results_dir)
    md_path = report.write_markdown(payload, f"{run_id}.md",
                                    results_dir=results_dir)
    if all_records:
        runs_path = report.write_runs(all_records, f"{run_id}_runs.json",
                                      results_dir=results_dir)
        print(f"\nruns   -> {runs_path}")
    print(f"result -> {json_path}")
    print(f"report -> {md_path}")
    print(f"elapsed: {payload['elapsed_s']} s")
    return 0


def _cell(data: dict) -> CellSummary:
    from nq027.report import _cell_kwargs
    return CellSummary(**_cell_kwargs(data))


if __name__ == "__main__":
    raise SystemExit(main())
