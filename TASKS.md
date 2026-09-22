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
- [x] NQ-027 — Model install + benchmark on the A5000 + selection decision
  - [x] Candidate models present locally: qwen3:8b, qwen3.5:9b, gemma3:12b,
        qwen3:14b, mistral-small3.2:24b, llama3:8b, bge-m3, nomic-embed-text
  - [x] Benchmark harness built and unit-tested (`ai/benchmarks/`, 139 tests
        green, no GPU required to run them)
  - [x] Residency probe, performance sweep (task x context x concurrency) and
        the full 50-case TripSpec quality evaluation executed on the A5000
  - [x] Embedding sweep executed (bge-m3 vs nomic-embed-text), dimension
        measured from real vectors, not read from documentation
  - [x] Selection **Accepted** — `qwen3:14b` (generation), `nomic-embed-text`
        at **768** dimensions (embedding). Full audit in
        `docs/adr/ADR-012-model-selection.md`.
  - [x] `vector(N)` dimension fixed: **768** — unblocks NQ-034
  - NOTE: ADR NUMBER COLLISION. The NQ-027 branch recorded model selection as
    "ADR-012" while `develop` independently used ADR-012 for multi-day trips.
    Whichever branch merges second must renumber. Not resolved here (the
    model-selection ADR is out of scope for NQ-029).
- [x] NQ-028 — LLM Gateway + FakeLLM
  - [x] Typed internal gateway at `backend/app/llm/` — the single chokepoint
        for model access; generation (`qwen3:14b`) and embedding
        (`nomic-embed-text`, 768 dimensions validated on every vector)
  - [x] `OllamaGateway` over existing httpx; `FakeLLM` deterministic test
        double on the same `LLMGateway` interface
  - [x] Typed failures (`LLMError` subclasses) for connection failure,
        timeout, rejected request, malformed / empty / truncated response and
        wrong embedding dimension — none returned as a success
  - [x] Bounded retries for transient failures only; timeouts and
        deterministic failures raised on first occurrence
  - [x] `OLLAMA_*` settings in `backend/app/config.py`
  - [x] 110 unit tests with no GPU or live Ollama; 4 live integration tests
        that skip cleanly when Ollama is unavailable
- [x] NQ-029 prep — TripDraft contract hardened ahead of extraction
  - [x] `start_time_local`/`end_time_local` require exact `HH:MM`
        (`Field(pattern=...)`, visible in `model_json_schema()`)
  - [x] `free_text_interests` bounded to 10 entries / 80 chars, matching
        TripSpec's existing bound
  - [x] `date_phrase` vocabulary documented against the real
        `resolve_date_phrase()` behaviour, with a test pinning docs to code
  - [x] `POST /plan/draft` returns `needs_clarification` explicitly on both
        paths - no existing consumer found anywhere in the repo
  - [x] Clarification cap (`MAX_CLARIFICATIONS=2`) and coordinate safety
        (`extra="ignore"`) covered by regression tests
  - [x] ADR-015 recorded
- [x] NQ-029 — natural language -> TripDraft extraction
  - [x] `backend/app/llm/extraction.py` — the only place free text becomes
        structured fields; consumes the NQ-028 `LLMGateway`, no second
        Ollama client and no direct HTTP
  - [x] Versioned prompt at `backend/app/llm/prompts/tripdraft_extraction_v1.md`
        (under `backend/` because the image's build context is `backend/`),
        with the closed enums injected from code so it cannot drift
  - [x] Schema-constrained decoding via `TripDraft.model_json_schema()`
  - [x] Refuses rather than repairs — typed `TripDraftExtractionFailed`
        (`invalid_json` / `not_an_object` / `schema_invalid`); no fence
        stripping, no field dropping, no fabricated defaults (ADR-016)
  - [x] `POST /api/v1/plan/extract` — extraction only. `/plan/draft` and
        `/plan` are unchanged and still need no model (ADR-002)
  - [x] Gateway injected by FastAPI DI (`get_llm_gateway`, lifespan-owned,
        `aclose()` on shutdown); tests inject `FakeLLM`, none need Ollama
  - [x] 94 unit + endpoint tests; all 6 gateway failure modes covered
  - [x] Real `qwen3:14b` eval, 26 cases, `ai/evals/nq029/`: schema validity
        100%, critical-field accuracy 92.6%, coordinate leakage 0%,
        malformed-time 0%, **hallucination 26.9%**, **unsupported date
        phrase 18.2%** - the last two are recorded, not smoothed over
  - [x] ADR-016 recorded
- [ ] NQ-030 — Eval datasets + scorer + baseline report
- [ ] NQ-031 — Clarification flow
- [ ] NQ-032 — Grounded explanation + numeric entailment
- [ ] NQ-033 — NL input UI with editable chips
- [ ] NQ-034 — travel-tips corpus + pgvector migration (`vector(768)`)

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
