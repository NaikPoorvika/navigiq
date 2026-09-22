# NAVIGIQ TASKS (TASKS.md)

Legend: [x] complete · [~] in progress · [ ] not started · [!] blocked · [-] deferred by decision

The project was re-planned around the master specification (ADR-021:
Bengaluru exploration companion — DISCOVER / UNDERSTAND / PLAN within 90 km).
The original NQ-001..034 plan is kept at the bottom for history; items it
listed that the new scope dropped are marked deferred with the ADR.

## Phase 0 — Foundation
- [x] Repository, control files, environment verification
- [x] PostgreSQL 16 + PostGIS + pgvector image; Alembic migrations
- [x] FastAPI foundation, settings, structured logging, request ids
- [x] Authentication (register/login/refresh rotation/logout/delete account)
- [x] Redis (optional; rate limits and caches)
- [x] Testing infrastructure: isolated migrated test DB with synthetic fixtures

## Phase 1 — Data
- [x] Staged, idempotent ingestion pipeline (OSM → Wikidata/Wikipedia → curated) with per-stage artefacts and drop reasons (ADR-026)
- [x] Geodesic envelope (90 km) and region buckets (ADR-023)
- [x] Closed vocabularies: categories, tags, moods (ADR-024)
- [x] Opening hours parsing with confidence; cost model (per-person estimates)
- [x] Gazetteer (areas resolved, unknown names reported)
- [x] Data quality report (`docs/data_quality_report.md`)

## Phase 2 — Discover
- [x] Deterministic recommendation engine with reasons, diversity, novelty (ADR-027)
- [x] Search, filters, place details, similar places, surprise, collections
- [x] Saved places, dismiss, interactions, preferences

## Phase 3 — Plan
- [x] TripSpec v2 contract, resolution with assumptions, semantic validation (ADR-025)
- [x] Feasibility pre-check with relaxations
- [x] CP-SAT optimizer (deterministic, category coverage, compactness, variety) + greedy fallback
- [x] Independent itinerary validator
- [x] Plan lifecycle: versions, modifications (closed ops), what-if variants, restore, compare
- [x] Multi-day trips, day-scoped changes (ADR-031)
- [-] Road routing / ETAs / fares — deferred (ADR-022); OSRM code preserved
- [-] Public transit — removed (ADR-007)

## Phase 4 — Understand + assistant
- [x] LLM gateway (Ollama, FakeLLM), model selection (ADR-012)
- [x] Knowledge corpus + hybrid retrieval (pgvector HNSW + tsvector, RRF)
- [x] Grounded answers with citation/number/URL validation, extractive fallback, refusal (ADR-029)
- [x] Intent classification (rules + model arbitration), TripSpec extraction, modification parsing, reference resolution — English, Hinglish, romanized and script Kannada
- [x] Bounded agent FSM with typed tools, limits, memoisation (ADR-028)
- [x] Robustness suites: 500-run chaotic-model fuzz, prompt injection, failure injection

## Phase 5 — Product UI
- [x] Web app: Explore, Search, Place, Ask NavigIQ, I'm bored, Collections, Plan builder, Plan (days, changes, what-if, versions), Plans, Saved, Profile, Auth (ADR-032)
- [x] Design system tokens; imagery honesty policy (ADR-033)
- [x] Accessibility (axe WCAG 2.1 AA on every main screen), phone layouts
- [x] Unit/component tests (Vitest), end-to-end tests on the real API (Playwright: Chromium, Firefox, WebKit, phone)

## Phase 6 — Quality and operations
- [x] Evaluation harness with held-out splits and history (ADR-030)
- [~] TripSpec held-out gates: latest split missed the date (0.958) and hard-constraint (0.947) gates; fixes verified on dev only — **next: a fresh held-out split**
- [x] Load test 1–50 users; scale-out (solver thread, 4 workers, Redis rate limits) (ADR-034)
- [x] Backup/restore check
- [x] Docker Compose stack (db, redis, api, web/nginx), CI workflow
- [ ] Container images built and started end to end on this machine (blocked here: no access to the Docker registry from this network; CI builds them)
- [ ] Multi-hour soak test
- [ ] Mutation testing of the validator and the NLU rules

## Next candidates (need a decision)
- [ ] Transportation provider (OSRM road times with honest labelling) — reverses ADR-022
- [ ] Live events (festivals, closures) — needs a lawful source
- [ ] More place photos from Wikimedia Commons (only ~20 of 12k have one)
- [ ] Update CLAUDE.md "Technology Direction" to match the decisions (OSRM and Celery are not used in this version) — requires the owner's approval

---

## History: original plan (NQ-001..034)

Completed under the original plan and carried forward: NQ-001..010 (foundation),
NQ-011..017 (data, hours, costs, search, ranking), NQ-018/019 (OSRM builds and
routing client — preserved, not used, ADR-022), NQ-020 (metro — removed,
ADR-007), NQ-021..025 (TripSpec, feasibility, CP-SAT, validator, orchestrator),
NQ-027 (model benchmark, ADR-012), NQ-028 (LLM gateway). NQ-026 and NQ-029..034
were superseded by the phases above.

Deferred idea kept for the transportation work: an "Open in Google Maps"
multi-stop link. The web app currently links single places to OpenStreetMap,
labelled as external.
