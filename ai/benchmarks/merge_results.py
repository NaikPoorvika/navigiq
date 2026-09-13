"""Consolidate separately-run stages into one payload.

The staged design lets probe/sweep/quality/embed run as independent
invocations (useful when chaining them, or resuming after an interruption).
This stitches their outputs back into a single file with the shape
run_benchmark.py's own report/select tooling expects, taking each section
from whichever source file actually has it - a smoke-test resume pointed at
the wrong sibling file does not lose data that exists elsewhere on disk.

    python ai/benchmarks/merge_results.py --out results/nq027_final.json \
        --probe results/nq027_probe_X.json \
        --sweep results/nq027_sweep_Y.json \
        --quality results/nq027_full_Z.json \
        --embed results/nq027_full_W.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nq027 import gates
from nq027.metrics import CellSummary
from nq027.report import _cell_kwargs, write_json, write_markdown


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cells(rows: list[dict]) -> list[CellSummary]:
    return [CellSummary(**_cell_kwargs(r)) for r in rows]


def main() -> int:
    p = argparse.ArgumentParser(description="Merge NQ-027 stage outputs")
    p.add_argument("--probe", required=True)
    p.add_argument("--sweep", required=True)
    p.add_argument("--quality", required=True)
    p.add_argument("--embed", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--run-id", default="nq027_final")
    args = p.parse_args()

    probe_doc = _load(args.probe)
    sweep_doc = _load(args.sweep)
    quality_doc = _load(args.quality)
    embed_doc = _load(args.embed)

    # The environment captured at probe time is the one that matters most -
    # it is when every candidate's residency was established - but each
    # stage recaptured its own, so the choice is recorded explicitly rather
    # than silently picking one.
    payload = {
        "run_id": args.run_id,
        "seed": probe_doc.get("seed"),
        "environment": probe_doc.get("environment"),
        "environment_by_stage": {
            "probe": probe_doc.get("environment", {}).get("captured_at_utc"),
            "sweep": sweep_doc.get("environment", {}).get("captured_at_utc"),
            "quality": quality_doc.get("environment", {}).get("captured_at_utc"),
            "embed": embed_doc.get("environment", {}).get("captured_at_utc"),
        },
        "source_files": {
            "probe": args.probe, "sweep": args.sweep,
            "quality": args.quality, "embed": args.embed,
        },
        "config": sweep_doc.get("config") or quality_doc.get("config"),
        "probes": probe_doc.get("probes", {}),
        "sweep": sweep_doc.get("sweep", {}),
        "quality": quality_doc.get("quality", {}),
        "embeddings": embed_doc.get("embeddings"),
    }

    if not payload["probes"]:
        print("warning: no probe data found", file=sys.stderr)
    if not payload["sweep"]:
        print("warning: no sweep data found", file=sys.stderr)
    if not payload["quality"]:
        print("warning: no quality data found", file=sys.stderr)
    if not payload["embeddings"]:
        print("warning: no embedding data found", file=sys.stderr)

    # Recompute gates from the merged evidence rather than trusting any one
    # stage's partial view of it.
    verdicts, quality_by_model = [], {}
    all_models = set(payload["probes"]) | set(payload["sweep"]) | set(payload["quality"])
    for model in sorted(all_models):
        sweep_cells = _cells(payload["sweep"].get(model, []))
        quality_cells = _cells(payload["quality"].get(model, []))
        quality_by_model[model] = quality_cells
        verdicts.append(gates.evaluate(model, payload["probes"].get(model, {}),
                                       sweep_cells, quality_cells))

    payload["verdicts"] = [v.to_dict() for v in verdicts]
    payload["ranking"] = gates.rank(verdicts, quality_by_model)

    out = Path(args.out)
    json_path = write_json(payload, out.name, results_dir=out.parent)
    md_path = write_markdown(payload, out.stem + ".md", results_dir=out.parent)

    print(f"merged  -> {json_path}")
    print(f"report  -> {md_path}")
    eligible = [v.model for v in verdicts if v.eligible]
    print(f"eligible candidates: {eligible or 'NONE'}")
    for v in verdicts:
        if not v.eligible:
            print(f"  {v.model}: failed {v.failed_gates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
