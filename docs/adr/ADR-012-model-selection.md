# ADR-012: Local model selection

**Status:** Accepted  
**Owner:** B1  
**Decided:** 2026-09-13  
**Evidence:** `ai/benchmarks/results/nq027_final.json`  
**Measured:** 2026-09-12T06:08:32+00:00 on NVIDIA RTX A5000 (24564 MiB), driver 596.51, Ollama 0.33.3  
**Commit:** `8c6e6be1929dae98c5b3b33816a2e1d2d0743dd6`  **(dirty tree)**

## Decision

**Generation model:** `qwen3:14b` (Q4_K_M, digest `bdbd181c33f2`)  
**Embedding model:** `nomic-embed-text` (digest `0a109f422b47`)  
**Embedding dimension `vector(N)`:** **768**

This record fixes two things that are expensive to reverse: the resident generation model every LLM task class routes to through NQ-028's gateway, and the embedding model - and with it the `vector(N)` dimension hard-coded in NQ-034's migration. Changing `N` later means re-embedding the corpus and rebuilding the HNSW index.

**Why `qwen3:14b` over the higher single-task scorer, `mistral-small3.2:24b`** - the full audit is below ("Why qwen3:14b, not the accuracy leader"). In one line: `mistral-small3.2:24b` scores 1.6 points higher on `tripspec_extract` alone, but `qwen3:14b` scores higher averaged across all eight task classes this one resident model must serve, uses only 52% of the latency budget against `mistral`'s 88%, and leaves nearly double the VRAM headroom for the embedding model and for NQ-034's context growth.

**Why `nomic-embed-text` over `bge-m3`** - both passed every measured check identically (dimension-consistent, unit-normalised, 3/3 similarity-ordering sanity checks); the benchmark has no evidence that discriminates retrieval *quality* between them, only resource cost, where `nomic-embed-text` is smaller (768 vs 1024 dims - a ~25% smaller pgvector/HNSW footprint), lighter (308 vs 633 MiB), and faster (171 vs 84 texts/s). Flagged explicitly below as the weaker-evidence half of this decision.

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

## Why `qwen3:14b`, not the accuracy leader

`mistral-small3.2:24b` scores highest on `tripspec_extract` in isolation.
NQ-028's gateway does not route one task through one model, though - it routes
**all eight task classes through whichever model this ADR names**. So the
question this ADR has to answer is not "which model wins `tripspec_extract`"
but "which model is the better resident model", and those have different
answers.

**Per-task accuracy, schema-constrained, all four eligible candidates:**

| task | `mistral-small3.2:24b` | `qwen3:14b` | `qwen3:8b` | `llama3:8b` |
|---|---|---|---|---|
| intent_classify | 92.9% | **100.0%** | 92.9% | 92.9% |
| tripspec_extract | **90.1%** | 88.5% | 84.0% | 83.1% |
| tripspec_modify | 93.9% | 90.4% | **99.3%** | 80.5% |
| tool_select | 100.0% | 100.0% | 100.0% | 100.0% |
| explain_itinerary | 85.7% | **100.0%** | 71.4% | 72.6% |
| rag_answer | **100.0%** | 87.5% | **100.0%** | 87.5% |
| reroute_message | 100.0% | 100.0% | 100.0% | 100.0% |
| clarify_question | 55.5% | 67.0% | 57.6% | **90.7%** |
| **all-8 average** | 89.76% | **91.68%** | 88.16% | 88.41% |

`qwen3:14b` wins five of eight task classes outright and posts the highest
unweighted average. Its two losses that matter (`tripspec_extract`,
`tripspec_modify`) are both narrow - 1.6 and 3.5 points - while its wins on
`intent_classify`, `explain_itinerary` and `clarify_question` are wide (7-45
points). `mistral-small3.2:24b`'s worst score, `clarify_question` at 55.5%, is
a task NQ-031 builds directly on top of.

**Weighted by what ships next matters more than an unweighted average.**
Phase 2's own ordering (NQ-029 extract, NQ-031 clarify, NQ-032 explain, plus
the foundational intent routing and NQ-045 modify) puts five of the eight
classes ahead of the other three (`tool_select`, `rag_answer`,
`reroute_message` - Phase 3/4 work). Averaged over just the near-term five:

| | `mistral-small3.2:24b` | `qwen3:14b` |
|---|---|---|
| near-term average (extract, modify, intent, clarify, explain) | 83.6% | **89.2%** |
| far-term average (tool_select, rag_answer, reroute) | **100.0%** | 95.8% |

The gap widens in `qwen3:14b`'s favour on exactly the work that ships first,
and the two swap on work that is one to two phases away and will very likely
be re-measured by NQ-030's eval before it matters.

**Latency margin, not just latency.** Both are inside the ASSUMPTION-002
budget, but not by the same amount:

| | `mistral-small3.2:24b` | `qwen3:14b` |
|---|---|---|
| `tripspec_extract` p95 | 7007 ms | 4131 ms |
| budget used (of 8000 ms) | 87.6% | 51.6% |
| margin | 993 ms | 3869 ms |

993 ms of margin is not a safe number to accept knowingly. ASSUMPTION-002
says explicitly that the deterministic pipeline runs after extraction and
that real user-facing prompts will grow once NQ-032 stuffs itinerary facts
into the explanation prompt and NQ-034 adds retrieved passages to RAG
answers - both measured here on short synthetic prompts. A model already
using seven-eighths of its budget on the shortest prompt it will ever see has
nowhere to go. `qwen3:14b` has 3.9 seconds of room for exactly that growth.

**VRAM headroom, for the same reason.** At the working context (8192):
`mistral-small3.2:24b` leaves 7.3 GiB free after loading against the 2.56 GiB
`embedding_headroom` floor - comfortable today, the tightest of the four
candidates, and the one most exposed if NQ-034 ever wants a second resident
model (a reranker, say) alongside it. `qwen3:14b` leaves 13.3 GiB free,
nearly double.

**Two smaller points, same direction.** `qwen3:14b` posted 100.0% schema
validity (50/50) against `mistral-small3.2:24b`'s 98.0% (one `schema_invalid`
in fifty runs) - not decisive alone, but not a point in the other model's
favour either. And `qwen3:14b` carries the `tools` capability flag, matching
ADR-004's typed tool registry that NQ-028 will build against; `llama3:8b`,
the fastest of the four, was excluded from the top choice specifically
because it carries neither `tools` nor `thinking`, and is hard-capped at
8192 context by the model itself (16384 was requested during the residency
probe and silently clamped by Ollama) - a ceiling that cannot be raised by
configuration and will matter the moment NQ-034 lengthens prompts.

**What would change this decision.** If NQ-030's real eval set shows
`tripspec_extract` accuracy matters enough on its own to outweigh the other
seven task classes combined, or if a future benchmark measures
`mistral-small3.2:24b`'s clarify/explain weaknesses as fixable by prompting
rather than inherent to the model, this call should be revisited - it is not
a proxy for "biggest model wins" or "most accurate on one task wins", it is
specifically about what the model routing all eight task classes needs.

## What this evidence does not cover

- Concurrency figures reflect the Ollama server's parallelism as configured on this machine at measurement time; the recorded `OLLAMA_*` environment is in the result file.
- Accuracy is measured on authored cases, not on production traffic. NQ-030 builds the eval set that supersedes this.
- Every figure is single-seed at temperature 0. Reproducible, but not a variance estimate.

---

Generated by `ai/benchmarks/select_model.py` from the run named above. The benchmark measures; the decision is human.