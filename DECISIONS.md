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

## ADR-015: Fame in ranking, from Wikidata sitelinks
**Status:** Accepted
**Date:** 2026-09-22

**Context:** Ranking picked the nearest matching POI, so a neighbourhood
temple 200 m away beat Bangalore Palace. Prominence was meant to carry
notability, but 94% of POIs score below 0.06, so it barely orders anything.

**Decision:** Add a `fame` component: the number of Wikipedia language
editions about a place, from `wikidata_sitelinks` (collected by
wikidata_enrich.py), log-scaled and saturating at 30. Weight 0.18, taken
from proximity, diversity and prominence.

**Consequences:** Well-known places win over merely near ones within the
search radius, while proximity (0.20) still rules out a famous place across
the city. Only ~80 POIs carry sitelinks today, so for most categories fame
is 0 for every candidate and ordering is unchanged. This is notability, not
quality — ADR-008 still stands: no star ratings.



## ADR-016: Accounts and profile on the server
**Status:** Accepted
**Date:** 2026-09-22

**Context:** Sign-up, sign-in and the profile lived in the browser. Public
sign-up also accepted `is_superuser`, so any caller could register as an
administrator.

**Decision:** Public sign-up takes email and password only; the server sets
everything else. Emails are normalised to lowercase and password rules are
enforced server-side. The planning profile — display name, home, interests,
vegetarian — lives on the user row, changed through `PATCH /auth/users/me`,
with interests checked against real categories and home against the region.
`DELETE /auth/users/me` removes an account, asking for the password again.

**Consequences:** A profile follows the account to any device. The login
token is kept in browser storage — adequate here, and a secure cookie is the
known next hardening step. Planning still works signed out; an account only
adds saving.

## ADR-017: Plans are changed by replanning, not editing
**Status:** Accepted
**Date:** 2026-09-22

**Context:** People want a different café without redoing the whole form.

**Decision:** Swap and Remove add the place to `constraints.avoid_poi_ids`
and run the planner again. Remove also decreases that category's count.
Nothing edits an itinerary in place.

**Rejected — editing the itinerary directly.** Moving or replacing a stop by
hand breaks the guarantees everything else rests on: times, opening hours,
budget and travel would all need rechecking, and a hand-edited plan could no
longer claim the validator passed it. Replanning keeps one path to an
itinerary (ADR-002).

**Consequences:** A swap may reshuffle other stops, because the whole day is
re-optimised. Saved plans cannot be edited — they are records. Choosing a
specific replacement needs the optimizer to accept a pinned place, which is
a separate decision.