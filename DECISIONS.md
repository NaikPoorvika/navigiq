# NAVIGIQ ARCHITECTURAL DECISION RECORDS (DECISIONS.md)

## ADR-001: Single Workstation
**Status:** Accepted
**Decision:** The application is designed for ONE physical workstation (Intel Xeon W-2295, 128GB RAM, RTX A5000 24GB). Cloud APIs or distributed GPU setups will not be used.

## ADR-002: LLM is not authoritative
**Status:** Accepted
**Decision:** The LLM will only be used for orchestration, reasoning, and language generation. It is NOT the source of truth for coordinates, distances, routing, or budget calculations.

## ADR-003: Bounded Agentic AI
**Status:** Accepted
**Decision:** Agentic behavior is restricted. The agent must use strict typed tools to interact with deterministic services and must never execute arbitrary shell commands or SQL.

## ADR-004: Typed tool registry
**Status:** Accepted
**Decision:** All agentic capabilities will be exposed through a controlled registry of typed tools, preventing the fabrication of external requests or data.

## ADR-005: Deterministic planning core
**Status:** Accepted
**Decision:** All math, routing (OSRM), optimization (OR-Tools), and constraint validations are handled strictly by deterministic code, acting as the authoritative planner.

## ADR-006: Prefer modular monolith
**Status:** Accepted
**Decision:** The system will be built as a modular monolith. Separate containers are acceptable only where operationally justified (e.g., PostgreSQL, Redis, OSRM, Ollama), avoiding unnecessary microservices.

## ADR-007: Metro removed
**Status:** Accepted
**Date:** 2026-09-04

**Context:** NQ-020 built a static Namma Metro graph, since OSRM cannot route
transit — ~20 stations, Dijkstra, headway/2 wait, interchange penalties,
distance-band fares, plus a multi-modal arc builder.

**Measured outcome:** Metro lost every arc tested. Indiranagar to Lalbagh was
47 min by metro against ~25 by auto — 80–84% slower once access walk, headway
wait and the Majestic interchange are counted. A 3×3 matrix across Indiranagar,
MG Road and Lalbagh chose auto for all six arcs.

**Decision:** Remove metro entirely — graph module, four YAML data files, enum
values in the TripSpec schema and cost model, fare bands, arc-builder branch,
and the metro tests. Recoverable from git history.

**Consequences:** Users cannot request metro, and the planner will not silently
substitute another mode for it. NavigIQ has no public transit support; the
README must say so rather than leave it implied.

**Rejected:** Raising the arc-selection time tolerance until metro wins. That
would mean recommending routes taking twice as long to save ₹60.



## ADR-008: Prominence replaces POI ratings
**Status:** Accepted
**Date:** 2026-09-03

**Context:** No free source of POI ratings exists. OpenStreetMap has none, and
commercial place APIs are excluded by ADR-001.

**Decision:** Rank on a deterministic prominence score computed from Wikidata
presence, Wikipedia presence, tag richness and a curated landmark flag. Store
the component breakdown so any ranking can be explained.

**Consequences:** Prominence measures documentation and notability, not quality
— no star ratings may ever be displayed. Measured distribution across 14,851
POIs: 9,705 score 0.000, ~94% below 0.06, only 60 above 0.3. Its ranking weight
was therefore reduced from 0.20 to 0.10 and the difference moved to proximity
and diversity. Curated POIs carry an editorial score that overrides it.

## ADR-009: Widened coordinate bounds
**Status:** Accepted
**Date:** 2026-09-04

**Context:** The draft TripSpec bounding box (lat 12.6–13.3) would have rejected
Nandi Hills at 13.37, a genuine day-trip destination inside the OSM extract.

**Decision:** Widen to lat 11.9–13.75, lon 76.7–78.9, matching the extract.

**Consequences:** The bbox guard catches coordinates hallucinated in another
country, not trips outside the city centre. Trip radius is controlled by
radius_km and the feasibility engine, not by this guard.


## ADR-010: Deterministic solving over search breadth
**Status:** Accepted
**Date:** 2026-09-04

**Context:** CP-SAT with parallel workers is non-deterministic even with a
fixed seed — workers race and objective ties break by whichever finishes
first. The same TripSpec produced different stop orders across runs, making
plan reproducibility meaningless.

**Measured (NQ-023 benchmark):** single worker reaches optimal at N=10
(1.6 s) and N=20 (5.1 s), and times out at N=35 and N=50. Eight workers are
roughly 3x faster below N=20 but also time out at 35 and 50. Parallelism
buys speed, not optimality, at the sizes that matter.

**Decision:** one search worker, fixed seed, candidate cap reduced from 50
to 20.

**Consequences:** Every solve is reproducible and provably optimal within its
candidate set. The optimizer chooses from the 20 best-ranked POIs rather than
50. If the cap is ever raised, the time limit must rise with it and
determinism must be re-verified.

## ADR-012: Local model selection
**Status:** Accepted
**Date:** 2026-09-13

**Context:** NQ-027 benchmarked eight locally-available models (six
generation, two embedding) against a from-scratch harness after the
2026-09-04 results were found superseded (truncated generations recorded as
successes). Full evidence, methodology and gate thresholds:
`docs/adr/ADR-012-model-selection.md`, `ai/benchmarks/results/nq027_final.json`.

**Decision:** Generation model **`qwen3:14b`** (Q4_K_M). Embedding model
**`nomic-embed-text`**, dimension **768** - this fixes `vector(N)` for the
NQ-034 migration.

`qwen3:14b` was chosen over `mistral-small3.2:24b`, which scored 1.6 points
higher on `tripspec_extract` alone (90.1% vs 88.5%), because NQ-028 routes
all eight task classes through one resident model, not just extraction:
`qwen3:14b` wins five of eight task classes, posts the higher all-task
average (91.7% vs 89.8%) and the higher near-term-weighted average (89.2% vs
83.6%, weighted toward NQ-029/031/032/045 which ship before Phase 3/4's
tool_select/rag_answer/reroute), uses 52% of the ASSUMPTION-002 latency
budget against `mistral`'s 88% (3.9 s of margin vs 1.0 s, before NQ-032/034
lengthen prompts with itinerary facts and retrieved passages), and leaves
13.3 GiB of VRAM headroom against `mistral`'s 7.3 GiB. `nomic-embed-text` was
chosen over `bge-m3` on resource cost alone (smaller, faster, equally
correct on the sanity checks run) - the benchmark has no evidence
distinguishing their retrieval *quality*, so this half of the decision rests
on weaker evidence than the generation model choice and should be revisited
if NQ-034's corpus benchmark says otherwise.

**Consequences:** NQ-028's gateway resolves to `qwen3:14b` by default.
NQ-034's migration is written against `vector(768)`. Neither is free to
change without re-running the affected halves of this benchmark:
re-embedding the corpus and rebuilding the HNSW index for a dimension
change, or re-validating every LLM task class against the new model for a
generation-model change.

## ASSUMPTION-002: Interactive latency budget for LLM stages

**Status:** Assumed, not measured against users
**Date:** 2026-09-12
**Owner:** B1
**Used by:** NQ-027 gate `extraction_latency_p95`, and NQ-028 onwards

**The assumption.** TripSpec extraction must complete within **8000 ms at p95**,
measured at context 8192, concurrency 1, schema-constrained, on a warm model.

**Why this number.** Extraction is not the whole wait. It sits in front of the
deterministic pipeline, which is itself not free: feasibility, POI search,
routing and CP-SAT all run after the spec exists, on real I/O (Postgres,
OSRM) that the NQ-025 verification run exercised for real (itinerary 7, 3
stops, a 167-minute *planned trip* - not pipeline latency - built and
persisted over HTTP). A user who types a sentence and presses plan
experiences the LLM stage plus all of that, not the LLM stage alone.
Holding the language stage to 8 s leaves the rest of the pipeline room inside a
perceived wait of roughly ten seconds, which is the range where a progress
indicator still reads as working rather than broken.

**What it is not.** It is not a measured tolerance from real users of this
product, because there are none yet. It is a design budget chosen so that the
model selected in ADR-012 cannot be one that only looks acceptable when nobody
is waiting for it.

**How it could be wrong.** Three ways, each with a visible consequence:

- If NL planning turns out to be a background action rather than an
  interactive one - the user submits and returns later - the budget is far
  too strict and is excluding models unnecessarily.
- If the deterministic pipeline is slower than assumed on a cold cache, 8 s
  for the LLM alone may already be too generous.
- The budget is stated at concurrency 1. On this workstation that is the
  honest single-user case; it says nothing about what happens when several
  requests arrive together, which the NQ-027 concurrency sweep measures
  separately.

**Revisit when:** NQ-033 puts the NL input in front of a real user, or NQ-030
produces an eval set from real traffic. If either shows the budget is wrong,
change it here first and re-run the gate rather than quietly accepting a model
that fails it.
