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

## ADR-011: Place gazetteer
**Status:** Accepted
**Date:** 2026-09-21

**Context:** The LLM must never produce coordinates (ADR-002), but nothing
turned a place name into lat/lon. Searching POIs for "Indiranagar" returned a
library, a plaque and a bar — never the neighbourhood.

**Decision:** Extract `place=*` nodes and areas from the same OSM extract into
a `places` table (9,163 rows) and resolve names across `places` and `pois`
through `GET /places/resolve`. Rank by trigram similarity, place kind,
proximity to the city centre and an exact-name bonus.

**Consequences:** Confidence comes from the score gap between the top two
*distinct* candidates. "Indiranagar" is genuinely two places 9 km apart and
returns `needs_clarification`. OSM duplicates within 200 m are not treated as
ambiguity. Spelling variants resolve ("Malleshwaram" → "Malleswaram").

## ADR-012: Multi-day trips as independent days
**Status:** Accepted
**Date:** 2026-09-21

**Context:** The original plan treated multi-day planning as research scope —
accommodation, overnight travel and cross-day optimization make it a
different product. Users still ask for "3 days in Bengaluru".

**Decision:** `TripSpec.days` (1–7). Each day is planned as its own single-day
itinerary from the same origin and time window, with no POI repeated across
days. Exposed as `POST /plan/trip`; `POST /plan` is unchanged.

**Consequences:** No accommodation, no overnight travel, no cross-day
optimization. A budget, if given, applies per day. Days run sequentially
because each must exclude earlier days' POIs — roughly 4 s per day after the
OSRM `/table` change, so 7 days is under 30 s.

## ADR-013: The LLM fills a draft, not a TripSpec
**Status:** Accepted
**Date:** 2026-09-21

**Context:** A model asked to produce a full TripSpec will invent coordinates
and compute dates, both of which it gets wrong.

**Decision:** The model produces a `TripDraft` containing only place *names*
and date *phrases*. `draft_builder` turns it into a TripSpec deterministically:
names through the gazetteer, phrases in Python. Unknown fields are ignored, so
a hallucinated lat/lon is discarded before it reaches planning.

**Consequences:** Missing or ambiguous information becomes at most two
clarifying questions rather than a guess. Defaults that are applied are
returned as explicit `assumptions`. `TripDraft.model_json_schema()` is the
schema for constrained decoding in NQ-029.


## ADR-014: POI costs are labelled category estimates
**Status:** Accepted
**Date:** 2026-09-21

**Context:** No POI has a real price. Every stop showed a category figure —
every restaurant "Rs 600", every temple "Rs 0" — presented as though it were
that venue's price.

**Decision:** Keep the category figures for planning: budgets need a food
estimate, and they let a tight budget prefer street food over restaurants.
Change the presentation: each stop carries `cost_basis: category_estimate`,
and the itinerary carries a `cost_note` saying these are typical category
costs, not venue prices.

**Rejected — dropping POI costs entirely.** Totals would cover transport only,
so a Rs 1500 budget would report "Rs 60" and the user would overspend on food.
The optimizer would also lose the ability to choose cheaper food on a tight
budget.

**Consequences:** The UI shows "≈ Rs 600 typical" rather than "Rs 600". Real
prices, when curated, use `cost_basis: poi_specific` and take precedence.

## ADR-015: TripDraft hardened ahead of NQ-029
**Status:** Accepted
**Date:** 2026-09-22

**Context:** ADR-013 established TripDraft as what the LLM fills in, but
three parts of the contract were looser than the model being asked to
produce it. `start_time_local`/`end_time_local` accepted anything
`TripSpec._hhmm` would (including "9:00", no leading zero); `free_text_interests`
had no bound at all even though the same field on TripSpec is capped at 10
entries/80 chars; and `POST /plan/draft`'s two response shapes could not be
told apart without inspecting unrelated fields - the successful path carried
no `needs_clarification` key at all, only the clarification path did.

**Decision:**
- `start_time_local`/`end_time_local` on TripDraft require exactly `HH:MM`,
  24-hour, zero-padded, via `Field(pattern=...)` rather than a hand-written
  validator, so the constraint is also visible in `TripDraft.model_json_schema()`
  and can inform schema-constrained decoding, not just reject after the
  fact. `None` (time not supplied) is unaffected - draft_builder still owns
  picking a default.
- `free_text_interests` on TripDraft is capped at 10 entries / 80 characters
  each, matching TripSpec's existing bound exactly, declared the same
  schema-visible way.
- `date_phrase` is documented, not constrained: the vocabulary
  `resolve_date_phrase()` (draft_builder.py) actually accepts is written out
  on the field so a prompt can target it, but the schema does not duplicate
  that resolution logic or reject phrases outside it.
- `POST /plan/draft` now returns `"needs_clarification": false` explicitly
  on the successful path (previously absent entirely), so a caller
  distinguishes the two outcomes by one boolean rather than by field
  presence. No consumer of this endpoint existed anywhere in the repository
  at the time of this change (searched: frontend, backend, tests, docs), so
  this is additive, not breaking.
- Clarification cap (`MAX_CLARIFICATIONS = 2`, unchanged) and coordinate
  safety (`extra="ignore"`, unchanged) are now pinned by regression tests
  rather than only by the original implementation.

**Rejected — constraining `date_phrase` to a fixed pattern/enum.** Would
duplicate `resolve_date_phrase()`'s logic in a second place, guaranteed to
drift from it. Left to prompt design and documentation instead.

**Consequences:** A malformed time or an over-long free-text list from the
model now fails at the TripDraft boundary with a field-specific error,
rather than passing TripDraft and failing later inside `draft_builder`'s
`TripSpec` construction as a generic one. NQ-029's extraction prompt can be
written directly against `TripDraft.model_json_schema()` and the documented
`date_phrase` vocabulary. No change to `draft_builder.py`'s resolution
logic, `resolve_place`, multi-day planning, or any deterministic service.

**Known gap, out of scope for this ADR:** the local database's `places`
table does not currently have the `kind` column `resolve_place()` (ADR-011)
queries - a pre-existing environment/migration sync issue, unrelated to and
not fixed by this decision. See TASKS.md and this task's final report.
