"""ADR-012 drafting.

The one bug worth a permanent test here: draft() once reconstructed the
evidence path from run_id ("results/{run_id}.json"), which is wrong the
moment a merged file's run_id does not match its filename - exactly the case
for a consolidated payload built by merge_results.py. A citation pointing at
a file that does not exist is worse than no citation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from select_model import draft


def minimal_payload(run_id: str = "some_run_id_that_does_not_match_the_file"):
    return {
        "run_id": run_id,
        "environment": {
            "captured_at_utc": "2026-09-12T06:08:32+00:00",
            "git_commit": "deadbeef", "git_dirty": False,
            "gpu": {"name": "RTX A5000", "memory_total_mib": 24564,
                   "driver_version": "596.51"},
            "ollama_version": "0.33.3",
        },
        "probes": {}, "sweep": {}, "quality": {}, "embeddings": None,
        "ranking": [], "verdicts": [],
    }


def test_evidence_path_is_the_literal_path_not_reconstructed_from_run_id():
    text = draft(minimal_payload(), "ai/benchmarks/results/nq027_final.json")
    assert "ai/benchmarks/results/nq027_final.json" in text
    # The old bug's output would appear here if it regressed.
    assert "some_run_id_that_does_not_match_the_file" not in text


def test_draft_never_states_a_decision():
    """The benchmark measures; the decision is human. A generated draft must
    never look like it already chose a model."""
    text = draft(minimal_payload(), "results/x.json")
    assert "not yet decided" in text
    assert "Status:** DRAFT" in text
