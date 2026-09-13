# NQ-027 — local model benchmark

Measures candidate models on this workstation so ADR-012 can be closed with
numbers instead of impressions. **This harness measures; it does not choose.**
The decision is a human one, recorded in `DECISIONS.md`.

## Why this exists in its current form

An earlier NQ-027 harness recorded generations that had been cut off at the
token cap as successful runs. Seven of its eight task classes were truncated
throughout, and the latency and throughput it reported for them described the
token cap rather than the task. Those results (dated 2026-09-04) are
superseded and must not be cited; this harness was written from the current
`develop` baseline rather than repaired.

The structural fix is `nq027/validity.py`. A run is classified by one ladder,
in a fixed order, and only the top rung counts:

```
transport → truncation → emptiness → JSON → schema → task check
```

Order is load-bearing. **Truncation is checked before parsing**, because a
capped response can still parse — constrained decoding emits a syntactically
closed object — and checking parse first is exactly how a capped run gets
recorded as a success. Ollama sets `done: true` on a capped generation; only
`done_reason == "length"` distinguishes it, and `eval_count >= num_predict` is
kept as a second, independent signal.

`metrics.py` then computes latency, TTFT and throughput over runs whose
outcome is `VALID` and over nothing else. A cell with no valid run reports
`n/a`, never `0`.

## Design decisions worth knowing

**The real `TripSpec` is imported, never copied.** `schemas.py` puts
`backend/` on the path and imports `app.schemas.tripspec`. Its JSON Schema is
handed to Ollama as the structured-output grammar. A schema change breaks this
benchmark loudly, which is correct; a transcribed copy would drift silently.

Note that grammar-constrained decoding guarantees *shape*, not *consistency*:
TripSpec's cross-field validators (`max_stops` below the MUST count, an
end time before the start) still reject constrained output, and those
rejections are real findings for NQ-029.

**Coordinates are supplied, not recalled.** ADR-002 makes the LLM
non-authoritative for anything numeric, so no prompt asks a model for a
coordinate. Each extraction case carries a gazetteer block and the model must
copy the right entry; an origin outside that block fails the run rather than
scoring low, because it would send the planner somewhere the user never named.

**Validity and accuracy are separate measurements.** A model that reliably
emits well-formed nonsense scores 100% on validity. Critical-field accuracy is
scored only over the fields each utterance actually determines — crediting a
model for a default it never had to infer would inflate every score.

**Free text is checked, not waved through.** `explain_itinerary`,
`rag_answer` and `reroute_message` have no schema to fail, so they are held to
a length bound, a refusal check, and numeric entailment: every number in the
answer must appear in the facts supplied. A fabricated figure fails the run.

**Thinking is disabled where the model supports it.** Reasoning tokens are the
largest single cause of hitting the cap, and NavigIQ's LLM work is structured
extraction under an interactive budget. Which setting applied is recorded on
every run.

## Task classes

| class | output | scored on |
|---|---|---|
| `intent_classify` | JSON | exact intent match |
| `tripspec_extract` | JSON (TripSpec) | critical-field accuracy, 50 cases |
| `tripspec_modify` | JSON (TripSpec) | change applied + rest preserved |
| `tool_select` | JSON | right tool (0.7) + required arguments (0.3) |
| `explain_itinerary` | text | required facts restated, nothing invented |
| `rag_answer` | text | answered from passages only |
| `reroute_message` | text | required facts restated, nothing invented |
| `clarify_question` | JSON | asks about the actually-missing field |

Cases live in `nq027/cases/` as data. Relative dates resolve from a fixed
reference date (`2026-10-01`, Thursday) so gold answers do not move with the
calendar.

## Running it

```bash
pip install -r ai/benchmarks/requirements.txt
python -m pytest ai/benchmarks/tests -q          # 103 tests, no GPU needed

python ai/benchmarks/run_benchmark.py --stage all
```

Stages run cheapest-first so GPU time is not spent on a model that has already
disqualified itself:

| stage | what it does |
|---|---|
| `probe` | loads each model at each context; records VRAM residency and headroom |
| `sweep` | performance matrix: task × context × concurrency |
| `quality` | full case sets, schema-constrained and unconstrained |
| `embed` | embedding candidates; dimension read from a real vector |
| `select` | applies the ADR-012 gates to whatever evidence exists |

Each stage writes its JSON before the next begins, so an interrupted run keeps
what it gathered. `--resume-from <file>` reuses earlier stages.

Useful flags: `--models`, `--contexts`, `--concurrencies`, `--tasks`,
`--runs` (requests per matrix cell), `--results-dir`.

## Output

`results/<run>.json` — every run row with its outcome, plus the environment
that produced it: GPU, driver, Ollama version, model digest, quantization,
context, concurrency, seed, git commit. Failures are kept, not discarded; the
failure breakdown is what tells you whether a latency figure means anything.

`results/<run>.md` — the same evidence as tables. Every timing is printed
beside `n_valid/n_runs`, so a fast-looking cell backed by two valid runs out
of twenty cannot be skimmed as a good result.

## The gates

`gates.py` holds the ADR-012 rules and the thresholds, each stated once:

| gate | threshold |
|---|---|
| `gpu_residency` | 100% of weights in VRAM, no CPU offload |
| `embedding_headroom` | ≥ 2560 MiB free after load |
| `schema_validity` | ≥ 95% valid on constrained `tripspec_extract` |
| `no_class_fully_truncated` | no task class truncated on every run |
| `extraction_latency_p95` | ≤ 8000 ms (ASSUMPTION-002) |
| `critical_field_accuracy` | ≥ 80% |

A gate returns `UNKNOWN` when the evidence to judge it is missing, and
`UNKNOWN` is not a pass. Treating absent evidence as acceptable evidence is
the failure this task exists to correct.
