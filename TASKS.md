# NAVIGIQ TASKS (TASKS.md)

Legend:
- [ ] NOT STARTED
- [~] IN PROGRESS
- [x] COMPLETE
- [!] BLOCKED

## Phase 0 — FOUNDATION
- [x] NQ-001 — Repository + project control files
- [x] NQ-002 — Host / environment verification
- [x] NQ-003 — PostgreSQL + PostGIS + pgvector
- [x] NQ-GH-01 — GitHub Remote Push
- [x] NQ-004 — FastAPI foundation
- [x] NQ-005 — Database models + migrations
- [x] NQ-006 — Authentication
- [x] NQ-007 — React frontend shell
- [x] NQ-008 — Redis
- [x] NQ-009 — Observability / tracing
- [x] NQ-010 — Testing infrastructure

## Phase 1 — DETERMINISTIC PLANNER
- [ ] NQ-011 — OSM extract -> Bengaluru clip -> tag filter -> staging JSONL
- [ ] NQ-012 — POI schema migration
- [ ] NQ-013 — Normalize -> dedupe -> enrich -> load + curated seed set
- [ ] NQ-014 — Opening-hours parsing
- [ ] NQ-015 — Cost model: POI costs, auto/cab/metro fare estimator
- [ ] NQ-016 — POI search service + hard filters + endpoints
- [ ] NQ-017 — Deterministic ranking
- [ ] NQ-018 — OSRM car + foot builds, containers, health checks
- [ ] NQ-019 — Routing service: client, retries, cache, time-of-day multipliers
- [ ] NQ-020 — Static metro graph
- [ ] NQ-021 — TripSpec Pydantic schema + semantic validation
- [ ] NQ-022 — Feasibility pre-check + relaxation ladder
- [ ] NQ-023 — OR-Tools CP-SAT optimizer + fallback
- [ ] NQ-024 — Independent itinerary validator
- [ ] NQ-025 — Planning orchestrator + `POST /plan` + weather client
- [ ] NQ-026 — Plan form + Leaflet map + timeline + cost breakdown

## Phase 2 — LLM + RAG
(Tasks TBD upon entering phase)

- [~] NQ-029 prep — TripDraft contract hardened ahead of extraction
  - [x] `start_time_local`/`end_time_local` require exact `HH:MM`
        (`Field(pattern=...)`, visible in `model_json_schema()`)
  - [x] `free_text_interests` bounded to 10 entries / 80 chars, matching
        TripSpec's existing bound
  - [x] `date_phrase` vocabulary documented against the real
        `resolve_date_phrase()` behaviour, with a test pinning docs to code
  - [x] `POST /plan/draft` returns `needs_clarification` explicitly on both
        paths (was previously absent on the successful path) - no existing
        consumer found anywhere in the repo, confirmed additive
  - [x] Clarification cap (`MAX_CLARIFICATIONS=2`) and coordinate safety
        (`extra="ignore"`) now covered by regression tests
  - [x] ADR-015 recorded
  - [ ] NQ-029 itself (LLM extraction against this contract) - not started,
        out of scope for this task
  - NOTE: destination-resolution tests were added but currently fail/skip -
    the local `places` table is missing the `kind` column `resolve_place()`
    queries (pre-existing DB/migration sync issue, not introduced or fixed
    here). See DECISIONS.md ADR-015 and this task's final report.

## Phase 3 — AGENTIC AI
(Tasks TBD upon entering phase)

## Phase 4 — LIVE EVENT INTELLIGENCE
(Tasks TBD upon entering phase)

## Phase 5 — PERSONALIZATION / ML
(Tasks TBD upon entering phase)

## Phase 6 — ADVANCED FEATURES
(Tasks TBD upon entering phase)

## Deferred idea - Google Maps export (for NQ-026 / NQ-055)

Build a Google Maps directions URL from itinerary coordinates:
  https://www.google.com/maps/dir/?api=1&origin=LAT,LON&destination=LAT,LON
    &waypoints=LAT,LON|LAT,LON&travelmode=driving

Gives the USER live traffic and turn-by-turn without any API key or cost.
Does NOT give NavigIQ live traffic - planning still uses our estimates.
Waypoint cap is 9 intermediate stops; itineraries are 3-6, so fine.

NQ-026: "Open in Google Maps" button on the itinerary.
NQ-055: "Navigate to next stop" during an active trip.
