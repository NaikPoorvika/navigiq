# NavigIQ architecture

A modular monolith on one workstation (ADR-001, ADR-006). One FastAPI
application owns every domain; PostgreSQL (PostGIS, pgvector, pg_trgm,
tsvector) is the single source of truth; Redis is an optional accelerator;
Ollama serves the local model on the GPU. The web app is a static bundle that
talks to the API on the same origin.

```text
 Browser ── React app (Vite build, served by nginx)
    │  same origin: /api/*
    ▼
 FastAPI (4 uvicorn workers) ─────────────────────────────────────────────┐
  api/v1: pois · collections · plans · assistant · knowledge · auth · me  │
    │                                                                     │
    ├─ assistant/  bounded agent (FSM) ── typed tool registry ──┐         │
    │     NLU rules: intents, extraction, modparse, references  │         │
    │     llm/ gateway ── Ollama qwen3:14b / nomic-embed-text   │         │
    │                                                          ▼          │
    ├─ services/recommendation   deterministic ranking + reasons          │
    ├─ services/planning         TripSpec → resolve → validate → candidates│
    │                            → cluster → feasibility → CP-SAT (thread) │
    │                            → greedy fallback → independent validator │
    │                            → itinerary; trips.py: day by day         │
    ├─ knowledge/                hybrid retrieval (HNSW + tsvector, RRF)   │
    │                            → grounded answer or extractive/refusal   │
    ├─ services/weather          Open-Meteo, cached, never blocks          │
    └─ services/transport        Null provider (transport deferred)        │
                                                                          │
 PostgreSQL 16 + PostGIS + pgvector ◄─────────────────────────────────────┘
 Redis (rate limits across workers, caches; optional)
```

## The rule that shapes everything

The model **understands and communicates**; deterministic services **decide**
(ADR-002, ADR-021). Concretely:

| The model may | The model may not |
|---|---|
| classify an intent (rules first; the model breaks ties) | invent a place, a coordinate, a price, an opening hour or a rating |
| propose TripSpec fields from the closed vocabulary | set a date (it may copy a date *phrase*; Python resolves it) |
| propose closed modification operations | edit itinerary JSON, or flip what the rules parsed |
| choose read-only tools for one bounded round | call a write tool, SQL, HTTP, the shell or the filesystem |
| phrase an explanation from a fact block | state a number that isn't in the fact block or a cited source |

Every model output is validated in Python; failures fall back to rules,
extractive answers or an honest refusal.

## Main flows

**Discover** — `POST /pois/recommend` (or the assistant) builds a
`RecommendationRequest`: hard filters exclude, twelve components score,
diversity-aware selection picks, reason codes explain (ADR-027). Novelty
rules keep "show me something different" different.

**Understand** — the assistant retrieves from a licensed corpus (hybrid
dense + sparse, RRF), builds an authoritative fact block (hours, weather,
costs), generates, then validates citations, numbers and URLs. Failing any
check means an extractive answer from cited sentences, or the refusal
(ADR-029).

**Plan** — one contract, `TripSpec` (ADR-025), from the form, the assistant, a
modification or a what-if:

1. `resolve_for_planning` fills unstated date/time with visible assumptions.
2. Semantic validation (dates, windows, contradictions).
3. Candidates from the recommendation engine; meals added when asked for.
4. Geographic cluster (local, city, or a day-trip escape).
5. Feasibility pre-check with suggested relaxations.
6. CP-SAT on a worker thread: single search worker, deterministic work
   budget, candidate cap 20 (ADR-010, ADR-034); objective = fit scores +
   coverage of each requested category − compactness − back-to-back same
   category − idle start; greedy schedule as fallback.
7. Independent validator re-reads facts from the database and checks
   existence, scope, hours, overlap, buffers, window, budget, must-includes,
   exclusions, requirements. An invalid plan is never shown.
8. The itinerary: stops, times, costs (estimates, excluding transport),
   buffers (never travel times, ADR-022), weather, map frame.

**Multi-day trips** — `services/planning/trips.py` (ADR-031) runs the same
pipeline once per day, passing other days' places as transient exclusions,
splitting the budget, and adding a trip-level check (no repeats, total
budget). A change to one day re-plans only that day.

**Transportation (deferred, ADR-022)** — V1 calculates no travel: no routes,
travel times, ETAs, traffic or fares, and never claims one. Consecutive stops
are separated by a fixed transition buffer (15 min by default, shown on every
itinerary with the note that travel time is not calculated), and the
optimizer keeps each day geographically coherent by penalising hop distance
— a preference, never a time. Planning asks a `TransportationProvider`
(`services/transport`); V1 uses the Null provider. A future provider can
supply real travel-time matrices through that interface (the optimizer
already accepts per-arc durations). The old OSRM client
(`services/routing`) is preserved but not imported by the active path.

**Change a plan** — the assistant's rule parser (or the model, validated)
produces closed operations (`remove_stop`, `set_budget`, `set_pace`,
`add_meal`… with an optional `day`). Python applies them to the spec, locks or
prefers the current stops, re-plans and re-validates. A modification is a new
version; a what-if is a pending variant shown next to the current plan until
it is applied or discarded. Versions are immutable; restore creates a new
version after re-validating against today's data.

## Agent (ADR-028)

`assistant/agent.py` is a finite-state machine (RECEIVE → CLASSIFY → … →
COMPLETE/FAIL) with an explicit transition table. Tools are typed Pydantic
schemas in a registry with per-role authorisation; limits on steps, tool
calls, identical calls, model calls and wall time are enforced in Python.
Read-only tool results are memoised per turn. Conversation state is bounded
and stored with the conversation, so the thread survives reloads.

## Web app (ADR-032, ADR-033)

React 19 + TypeScript (strict), Vite, Tailwind v4 design tokens, TanStack
Router (a lazy chunk per screen) and Query (all server state), Radix and vaul
for accessible overlays, react-leaflet for maps (pins only). The API client
adds the anonymous browser session header, the access token (refreshed once
on 401, one shared refresh for concurrent callers), and maps errors to the
backend's stable codes. Screens: Explore, Search, Place, Ask NavigIQ, I'm
bored, Collections, Plan builder, Plan (days, changes, what-if, versions),
Plans, Saved, Profile, Sign in/up. See `docs/frontend/DESIGN.md`.

## Data (ADR-023, ADR-024, ADR-026)

A staged, idempotent pipeline (extract → filter → normalize → categorize →
dedupe → enrich → tag → curate → score → validate → load → report) from
OpenStreetMap, Wikidata and Wikipedia plus a curated set. Every place has a
geodesic distance from the centre and a region bucket; categories, tags and
moods are closed vocabularies. See `DATA.md` and `docs/data_quality_report.md`.

## Security and privacy

- Passwords hashed (bcrypt); short-lived access tokens; rotating, revocable
  refresh tokens; account deletion cascades to plans, saved places and
  preferences.
- Ownership enforced on every plan and conversation read/write; another
  user's plan is reported as not found.
- Request size limit, per-client rate limits on auth and the assistant
  (Redis-shared), stable error codes, no stack traces to clients.
- Retrieved and user text is data, never instructions; instruction-like
  chunks are withheld; URLs must come from a source (prompt-injection suite).
- nginx sends a strict Content-Security-Policy and security headers.
- Secrets only in `.env` files, which are git-ignored; `.env.example`
  documents every setting.

## Operations

- `infrastructure/docker-compose.yml`: db, redis, backend (migrations on
  start, 4 workers), web (nginx). OSRM is not part of V1; its container sits
  behind the `routing` profile for the deferred transportation work (ADR-022).
- No task queue: V1 has no background workload (ingestion is a CLI, every
  other operation is request-scoped), so Celery is not used.
- Health: `/api/v1/health` (DB, Redis) and `/api/v1/health/deep`.
- Observability: structured logs with request ids; agent runs, tool calls and
  LLM calls are recorded with timings (retention configurable).
- Backups: `scripts/backup_restore_check.sh` (dump, restore, compare).
- Capacity: `docs/reports/load_test.md`.
