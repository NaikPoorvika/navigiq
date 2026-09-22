# NQ-029 — TripDraft extraction evaluation

One question only:

> Does `qwen3:14b` reliably produce our finalized `TripDraft` contract?

This is **not** a model comparison. NQ-027 / ADR-012 selected the model on
measured evidence; re-benchmarking candidates here is explicitly out of
scope.

## Run it

Needs a running Ollama with the configured generation model pulled. The
backend's normal settings are used — nothing is hard-coded.

```bash
# from the repo root
python ai/evals/nq029/run.py

# one or two cases while iterating
python ai/evals/nq029/run.py --case 17-ambiguous --case 24-unsupported-transport
```

The runner is pinned to the **v1** prompt that produced the committed
baseline, even though production moved to v2 in NQ-030 — otherwise re-running
it would silently measure a different prompt. `--prompt-version v2` runs the
same cases against v2. NQ-030's own evaluation (held-out set, both prompts,
repeats) lives in `ai/evals/nq030/`.

Re-running the baseline does not reproduce it bit-for-bit: qwen3:14b on
Ollama is not deterministic at temperature 0 with a fixed seed. A re-run on
2026-09-22 changed 2 of 26 raw responses (hallucination 26.9% → 30.8%). See
`ai/evals/nq030/README.md`.

Writes `results/results.json` (including every raw model response) and
`results/report.md`.

The scorer has its own tests, which need neither Ollama nor a GPU:

```bash
python -m pytest ai/evals/nq029 -q
```

## Files

| file | what it is |
| --- | --- |
| `cases.py` | the dataset: all 20 required case classes plus 6 negative cases |
| `score.py` | scoring and metrics |
| `run.py` | runner — calls the real `extract_trip_draft()` through the real gateway |
| `test_score.py` | tests for the scorer and the dataset |
| `results/` | the committed measurement |

## How it measures

**It calls the production path.** `run.py` calls `extract_trip_draft()`, the
same function the API calls, wrapping the configured `OllamaGateway` in a
recording proxy. The prompt, the JSON schema, the temperature and the
parsing are not re-implemented here, so a number from this runner is a
statement about the shipped path rather than about a copy of it.

**Two layers are scored.** Coordinate leakage and malformed times are
measured on the **raw** model response, before `TripDraft` drops or rejects
anything. A model that emitted `"lat": 12.9352` on every call would score a
perfect 0% leakage if only the validated draft were inspected — that would
be measuring our own schema, not the model.

**Hallucination is computed, not listed.** Every `TripDraft` field a case
does not expect and does not explicitly `allow` must come back empty. An
earlier version of `cases.py` hand-listed forbidden fields per case and
measurably flattered the model: on case 15 it invented `transport`,
`vegetarian` and `mode`, none of which that list happened to name, so none
counted. Switching to the computed rule moved the measured hallucination
rate from 15.4% to 26.9% on the same responses. `allow` is only for genuine
ambiguity — a sentence with two defensible readings — never for a field the
model merely tends to guess.

**Failing scores zero, not neutral.** A case whose extraction failed scores
0 for every field it was expected to produce. Failing must never look
better than answering wrongly.

**An unmeasured rate prints "not measured", not 0%.** Zero malformed times
out of zero times seen is not a good result; it is no result.

### Judgement calls, stated once

- **places** match case-insensitively, and a superset counts
  ("Koramangala, Bengaluru" satisfies "Koramangala") — the gazetteer
  resolves the name later anyway.
- **date phrases** are compared by what they *resolve to* via
  `resolve_date_phrase()` against a fixed reference Monday, so "Saturday"
  and "this Saturday" are the same answer.
- **interests** need exact set equality, so a spurious extra category is a
  miss rather than a free pass.

## Metrics

| metric | denominator |
| --- | --- |
| schema validity | all cases |
| critical-field accuracy | all expected field checks, failures included |
| hallucination rate | cases that produced a valid draft |
| coordinate leakage rate | raw responses received |
| malformed-time rate | raw responses that contained a time |
| unsupported-date-phrase rate | raw responses that contained a date phrase |

"Unsupported" means `resolve_date_phrase()` returns `None` for it — the
phrase would become a clarifying question instead of a date.

## A note on tuning

The prompt in `backend/app/llm/prompts/` has **not** been tuned against this
dataset. The committed numbers are therefore a measurement, not a training
score. If a future task edits the prompt to fix the failures below, the
honest comparison needs a held-out set — see NQ-030, which owns eval
datasets and baselines.
