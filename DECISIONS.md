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

---

The records below were written as the product was rebuilt around the master
specification (Bengaluru exploration companion). Numbers not listed (011,
013-019) were never used. Code comments cite these numbers.

## ADR-020: No public transit (alias of ADR-007)
**Status:** Accepted
Some routing modules cite ADR-020 for the metro removal; the decision and its
evidence are ADR-007. Kept as an alias so the citations resolve.

## ADR-021: Product scope - DISCOVER, UNDERSTAND, PLAN within 90 km
**Status:** Accepted
**Date:** 2026-09-14
**Decision:** NavigIQ is a Bengaluru exploration companion: find things to do
(discover), learn about places (understand, with cited sources), and build
validated day plans (plan). The exploration envelope is 90 km from the city
centre. "The LLM understands and communicates; deterministic services decide
facts, rankings, constraints and validity."
**Consequences:** Every surface that states a fact (cost, hours, weather,
distance, a citation) reads it from a deterministic service or the database.
Anything outside 90 km is out of scope and is refused, not approximated.

## ADR-022: Transportation deferred
**Status:** Accepted
**Date:** 2026-09-14
**Context:** Road ETAs without live traffic were misleading at the times
people actually travel, and the metro lost every comparison (ADR-007).
**Decision:** This version calculates no travel: no routes, ETAs, fares or
traffic. Consecutive stops are separated by a fixed transition buffer (15 min
by default) and every itinerary says: "Transition buffers are included
between stops. Actual transportation time is not calculated in this
version." Core planning talks to a `TransportationProvider`; today it is the
Null provider. The OSRM routing code (NQ-018..020) is preserved under
`app/services/routing` for a future provider; the OSRM container sits behind
the compose `routing` profile.
**Consequences:** Maps show pins only, never a drawn route. An external "Open
in OpenStreetMap" link is labelled as external. Hop distance is used only as a
coherence preference (keep a day geographically tight), never as time.

## ADR-023: Discovery envelope and region buckets
**Status:** Accepted
**Decision:** `distance_from_center_km` is a WGS84 geodesic (geographiclib,
matching PostGIS geography), stored per place; 90 km is inclusive with a 10 cm
tolerance. Places fall into CITY_CORE, CITY, OUTSKIRTS and NEARBY_ESCAPE
buckets that drive search scope ("near me" never returns a day trip).

## ADR-024: Closed vocabularies
**Status:** Accepted
**Decision:** Categories, experience tags and moods are closed enums checked
against `data/config/categories.yaml`. The LLM may only choose among them;
unmapped phrases become free-text interests resolved by the lexicon.

## ADR-025: TripSpec v2 is the only planning contract
**Status:** Accepted
**Decision:** One Pydantic model (`app/schemas/tripspec.py`) feeds the planner
from the form, the assistant, modifications and what-ifs. Three validation
tiers (schema, semantic, feasibility) run in Python, never in a prompt.
Defaults applied at planning time are returned as visible assumptions.
Model-supplied coordinates are rejected unless they come from the gazetteer.

## ADR-026: Lawful, attributable data only
**Status:** Accepted
**Decision:** Place data comes from OpenStreetMap (ODbL), Wikidata (CC0) and
Wikipedia (CC BY-SA), plus a curated editorial set. Photos only from
Wikimedia Commons with artist and licence stored and shown. No scraping of
commercial review sites; no ratings (ADR-008). The pipeline is staged,
idempotent and writes an artefact and drop reasons per stage.

## ADR-027: Deterministic recommendations with reasons
**Status:** Accepted
**Decision:** Hard filters exclude; twelve weighted components rank; a
diversity-aware selection picks; reason codes are derived from the
components. The model may phrase reasons but never add one. Ranking weights
live in `data/config/recommendation_weights.yaml` with a version recorded on
every response.

## ADR-028: Bounded agent as a finite-state machine
**Status:** Accepted
**Decision:** The assistant is an explicit state machine with a transition
table, a typed tool registry with per-role authorisation enforced in Python,
hard limits (steps, tool calls, identical calls, model calls, wall time) and
one bounded round of model-selected read-only tools. Read-only tool results
are memoised per turn. Verified by 500 chaotic-model fuzz runs, the
prompt-injection suite and failure injection (all terminate; no unauthorised
tool ever runs).

## ADR-029: Grounded answers or honest refusal
**Status:** Accepted
**Decision:** Hybrid retrieval (pgvector HNSW + tsvector, fused with RRF) over
a licensed corpus. Generated answers must cite retrieved sources for every
sentence and every number must appear in a source or the fact block;
otherwise the answer falls back to cited verbatim sentences, or to "I don't
have reliable information for that yet." Retrieved text is data, never
instructions (instruction-like chunks are withheld; URLs not in a source are
rejected).

## ADR-030: Evaluation with held-out splits
**Status:** Accepted
**Decision:** Every quality gate (intent, TripSpec, dates, modifications,
references, retrieval, answers) is measured on a dev split used for tuning and
a test split that is scored before any change it prompts. A test split that
has been looked at is relabelled dev and a fresh one written. History,
including misses, is kept in `docs/reports/evaluation_history.md`.

## ADR-031: Multi-day trips as a sequence of validated days
**Status:** Accepted
**Date:** 2026-09-22
**Context:** Weekends and short holidays were the most common requests the
single-day planner could not express.
**Decision:** `TripSpec.end_date` (up to 7 days). `services/planning/trips.py`
plans each day with the unchanged single-day engine and validator. Places on
other days are passed as transient exclusions (so no place repeats, and
freeing a day frees its places); the budget is split evenly; required places
are spread across days. Each day stores the resolved spec it was planned
from, so "make day 2 cheaper" re-plans only day 2 from its own constraints
while the other days are kept verbatim. A trip-level check re-verifies no
repeats and the total budget. Modifications take an optional `day`; stop
numbers are trip-wide, or day-local with a day.
**Rejected:** One CP-SAT model across all days - the solve grows with days x
candidates, loses the per-day validator report, and makes a one-day change
re-plan the whole trip.
**Consequences:** Trip creation costs one solve per day (about 1-3 s per
day). Cross-day optimality is not attempted: day 1 gets first choice.

## ADR-032: Web app architecture and design system
**Status:** Accepted
**Date:** 2026-09-22
**Decision:** A Vite single-page app (React 19, TypeScript strict, Tailwind v4
tokens, TanStack Router with a lazy chunk per screen, TanStack Query for all
server state, Radix primitives, vaul bottom sheets, react-leaflet). The API
is always same-origin `/api` (Vite proxy in development, nginx in the
container). The visual identity is carried over from the original NavigIQ
concept (warm sand, deep olive, Sora and DM Sans) and formalised as one token
set in `frontend/src/styles/index.css`. The concept project was a reference
only; none of its mock services ship.
**Consequences:** Anonymous use is first-class (a browser session id owns
plans and conversations; they are claimed on sign-in). The structured plan
builder never needs the language model.

## ADR-033: Imagery honesty
**Status:** Accepted
**Date:** 2026-09-22
**Decision:** A place is shown with its own Wikimedia photo (credited) or with
generated category artwork (category tone, icon, contour texture varied per
place). The AI-generated images from the design concept are used only as mood
illustration (hero, collection tiles) with alt text starting "Illustration:"
and a visible "Illustration" caption on the hero; images that resembled
specific landmarks were not brought over.
**Consequences:** Only about 20 of 12k places have photos, so most cards use
artwork. That is deliberate: a pretty but wrong photo would be a fabricated
fact.

## ADR-034: Scale-out on one workstation
**Status:** Accepted
**Date:** 2026-09-22
**Measured:** one API process saturated at about 21 req/s (p50 1.26 s at 50
users) because CPU-bound scoring and the CP-SAT solve shared one event loop.
**Decision:** CP-SAT runs on a worker thread (native code releases the GIL);
the API runs 4 uvicorn workers; rate limits are counted in Redis so they hold
across workers, with the in-memory counter as a fallback.
**Result:** 50 users: 0 errors, 38-51 req/s, p50 110-131 ms
(`docs/reports/load_test.md`).
