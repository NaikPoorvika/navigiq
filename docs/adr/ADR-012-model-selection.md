# ADR-012: Local model selection

**Status:** DRAFT - awaiting a human decision  
**Owner:** B1  
**Evidence:** `ai/benchmarks/results/nq027_final.json`  
**Measured:** 2026-09-12T06:08:32+00:00 on NVIDIA RTX A5000 (24564 MiB), driver 596.51, Ollama 0.33.3  
**Commit:** `8c6e6be1929dae98c5b3b33816a2e1d2d0743dd6`  **(dirty tree)**

## Decision

**Generation model:** _(not yet decided - fill in and set Status to Accepted)_  
**Embedding model:** _(not yet decided)_  
**Embedding dimension `vector(N)`:** _(not yet decided)_

This record fixes two things that are expensive to reverse: the resident generation model every LLM task class routes to through NQ-028's gateway, and the embedding model - and with it the `vector(N)` dimension hard-coded in NQ-034's migration. Changing `N` later means re-embedding the corpus and rebuilding the HNSW index.

## Candidates, as measured

| model | quant | VRAM @8k | resident | schema validity | critical-field accuracy | extract p95 | eligible |
|---|---|---|---|---|---|---|---|
| `mistral-small3.2:24b` | Q4_K_M | 15100.4 MiB | yes | 98.0% | 90.1% | 7007 ms | yes |
| `qwen3:14b` | Q4_K_M | 9983.5 MiB | yes | 100.0% | 88.5% | 4131 ms | yes |
| `qwen3:8b` | Q4_K_M | 6003.8 MiB | yes | 100.0% | 84.0% | 2713 ms | yes |
| `llama3:8b` | Q4_0 | 5412.0 MiB | yes | 100.0% | 83.1% | 1917 ms | yes |
| `gemma3:12b` | Q4_K_M | 7959.6 MiB | yes | 98.0% | 78.1% | 4380 ms | no - critical_field_accuracy |
| `qwen3.5:9b` | Q4_K_M | 5463.8 MiB | yes | 100.0% | 77.4% | 3668 ms | no - critical_field_accuracy |

## Structured output: schema-constrained vs unconstrained

Both columns are `tripspec_extract` over the same 50 cases, same seed, same context. The only difference is whether Ollama was given the TripSpec JSON Schema as a decoding grammar.

| model | constrained validity | unconstrained validity | constrained accuracy | unconstrained accuracy |
|---|---|---|---|---|
| `qwen3:8b` | 100.0% | 6.0% | 84.0% | 80.6% |
| `qwen3.5:9b` | 100.0% | 2.0% | 77.4% | 100.0% |
| `gemma3:12b` | 98.0% | 48.0% | 78.1% | 90.9% |
| `qwen3:14b` | 100.0% | 84.0% | 88.5% | 94.1% |
| `mistral-small3.2:24b` | 98.0% | 100.0% | 90.1% | 93.8% |
| `llama3:8b` | 100.0% | 62.0% | 83.1% | 89.5% |

## Concurrency and context (the sweep matrix)

`tripspec_extract`, schema-constrained, at the concurrency budget context - p95 latency and throughput per concurrency level. Flat throughput across levels means the server is queueing requests rather than running them in parallel; rising p95 in step with concurrency is the queue, not a slowdown.

| model | conc 1 p95 | conc 2 p95 | conc 4 p95 | throughput req/s (1 / 2 / 4) |
|---|---|---|---|---|
| `qwen3:8b` | 2683 ms | 3830 ms | 7432 ms | 0.54 / 0.57 / 0.57 |
| `qwen3.5:9b` | 2792 ms | 4840 ms | 9627 ms | 0.42 / 0.43 / 0.43 |
| `gemma3:12b` | 3817 ms | 5923 ms | 11509 ms | 0.37 / 0.38 / 0.37 |
| `qwen3:14b` | 4165 ms | 7849 ms | 14246 ms | 0.29 / 0.29 / 0.30 |
| `mistral-small3.2:24b` | 4789 ms | 8748 ms | 16996 ms | 0.24 / 0.24 / 0.24 |
| `llama3:8b` | 2076 ms | 3278 ms | 6396 ms | 0.68 / 0.69 / 0.68 |

Context size (4096 / 8192 / 16384) showed no measurable latency cost at these prompt lengths for the models that were swept across all three; longer context costs VRAM at load time instead (see the residency probe and `embedding_headroom`).

## Embedding models

Dimension is the length of a vector this machine returned, not a figure from a model card.

| model | dimension | VRAM | single p50 | texts/s | similarity checks |
|---|---|---|---|---|---|
| `bge-m3` | **1024** | 633.2 MiB | 58.38 ms | 84.36 | 3/3 |
| `nomic-embed-text` | **768** | 308.2 MiB | 15.38 ms | 171.33 | 3/3 |

## Gates

Thresholds are defined once, in `ai/benchmarks/nq027/gates.py`. `UNKNOWN` means the evidence needed to judge the gate is missing, and does not count as a pass.

### `qwen3:8b` - ELIGIBLE

| gate | status | measured | threshold |
|---|---|---|---|
| gpu_residency | PASS | 100.0% in VRAM | 100% in VRAM |
| embedding_headroom | PASS | 17266 MiB free | >= 2560 MiB free |
| schema_validity | PASS | 100.0% (50/50) | >= 95% |
| no_class_fully_truncated | PASS | none | no fully-truncated class |
| extraction_latency_p95 | PASS | 2713 ms | <= 8000 ms |
| critical_field_accuracy | PASS | 84.0% | >= 80% |

### `qwen3.5:9b` - NOT ELIGIBLE

| gate | status | measured | threshold |
|---|---|---|---|
| gpu_residency | PASS | 100.0% in VRAM | 100% in VRAM |
| embedding_headroom | PASS | 16796 MiB free | >= 2560 MiB free |
| schema_validity | PASS | 100.0% (50/50) | >= 95% |
| no_class_fully_truncated | PASS | none | no fully-truncated class |
| extraction_latency_p95 | PASS | 3668 ms | <= 8000 ms |
| critical_field_accuracy | FAIL | 77.4% | >= 80% |

### `gemma3:12b` - NOT ELIGIBLE

| gate | status | measured | threshold |
|---|---|---|---|
| gpu_residency | PASS | 100.0% in VRAM | 100% in VRAM |
| embedding_headroom | PASS | 13985 MiB free | >= 2560 MiB free |
| schema_validity | PASS | 98.0% (49/50) | >= 95% |
| no_class_fully_truncated | PASS | none | no fully-truncated class |
| extraction_latency_p95 | PASS | 4380 ms | <= 8000 ms |
| critical_field_accuracy | FAIL | 78.1% | >= 80% |

### `qwen3:14b` - ELIGIBLE

| gate | status | measured | threshold |
|---|---|---|---|
| gpu_residency | PASS | 100.0% in VRAM | 100% in VRAM |
| embedding_headroom | PASS | 13276 MiB free | >= 2560 MiB free |
| schema_validity | PASS | 100.0% (50/50) | >= 95% |
| no_class_fully_truncated | PASS | none | no fully-truncated class |
| extraction_latency_p95 | PASS | 4131 ms | <= 8000 ms |
| critical_field_accuracy | PASS | 88.5% | >= 80% |

### `mistral-small3.2:24b` - ELIGIBLE

| gate | status | measured | threshold |
|---|---|---|---|
| gpu_residency | PASS | 100.0% in VRAM | 100% in VRAM |
| embedding_headroom | PASS | 7348 MiB free | >= 2560 MiB free |
| schema_validity | PASS | 98.0% (49/50) | >= 95% |
| no_class_fully_truncated | PASS | none | no fully-truncated class |
| extraction_latency_p95 | PASS | 7007 ms | <= 8000 ms |
| critical_field_accuracy | PASS | 90.1% | >= 80% |

### `llama3:8b` - ELIGIBLE

| gate | status | measured | threshold |
|---|---|---|---|
| gpu_residency | PASS | 100.0% in VRAM | 100% in VRAM |
| embedding_headroom | PASS | 17853 MiB free | >= 2560 MiB free |
| schema_validity | PASS | 100.0% (50/50) | >= 95% |
| no_class_fully_truncated | PASS | none | no fully-truncated class |
| extraction_latency_p95 | PASS | 1917 ms | <= 8000 ms |
| critical_field_accuracy | PASS | 83.1% | >= 80% |

## Reading the four eligible candidates

Not a decision - the trade-off a human still has to weigh:

- **`mistral-small3.2:24b`** - highest critical-field accuracy (90.1%) and the
  only one with clean unconstrained-mode accuracy too (93.8%), but slowest
  (7.0 s p95, against the 8.0 s budget with the least margin) and heaviest
  (15.1 GiB at 8k context, 7.3 GiB free headroom at 16k - the tightest of the
  four against the 2.56 GiB embedding reserve).
- **`qwen3:14b`** - second-highest accuracy (88.5%), comfortable latency
  (4.1 s p95) and comfortable headroom (13.3 GiB free at 8k). The balanced
  choice if 90% accuracy is not required.
- **`qwen3:8b`** - 84.0% accuracy at 2.7 s p95, the fastest model that also
  cleared the accuracy gate with a wide margin. Best fit if the 8 s budget
  needs slack for the rest of the pipeline (ASSUMPTION-002).
- **`llama3:8b`** - fastest of the four (1.9 s p95) but capped at 8192 context
  by the model itself (16384 was requested and silently clamped by Ollama -
  see the residency probe), and the only one of the four without a `tools`
  or `thinking` capability flag. Fine for extraction; a constraint if NQ-028
  ever wants native tool-calling from the same model.

`gemma3:12b` and `qwen3.5:9b` are excluded on measured accuracy alone (77-78%
against the 80% gate) - both otherwise passed every gate cleanly, so this is
not a residency or latency story.

**Unconstrained-mode accuracy is not directly comparable across rows above**:
it is computed only over the subset that happened to produce valid JSON
without a grammar (as low as 3/50 for `qwen3:8b`), so it describes accuracy
conditional on success, not accuracy overall. The schema-validity columns
above must be read alongside it. The clear finding regardless: **structured
output changes the outcome, not just the format** - three of the six
candidates lose the majority of their runs to `schema_invalid` the moment the
grammar is removed.

## What this evidence does not cover

- Concurrency figures reflect the Ollama server's parallelism as configured on this machine at measurement time; the recorded `OLLAMA_*` environment is in the result file.
- Accuracy is measured on authored cases, not on production traffic. NQ-030 builds the eval set that supersedes this.
- Every figure is single-seed at temperature 0. Reproducible, but not a variance estimate.

---

Generated by `ai/benchmarks/select_model.py` from the run named above. The benchmark measures; the decision is human.