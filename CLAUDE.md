# NAVIGIQ — AI CODING AGENT CONTRACT (CLAUDE.md)

## 1. Project Purpose
NavigIQ is a highly controlled, agentic AI software engineering project aimed at building a travel planning application. It emphasizes correctness, maintainability, architectural consistency, and small verified increments.

## 2. Architecture Principles
- **Modular Monolith**: Over unnecessary microservices.
- **Single-Machine Constraint**: Designed for one physical workstation (Windows 64-bit, 128GB RAM, RTX A5000 24GB).
- **Technology Direction (V1, active)**: React, Vite, Leaflet, Python, FastAPI, PostgreSQL, PostGIS, pgvector, OR-Tools (CP-SAT), Redis (optional cache and shared rate limits), Ollama (local LLM).
- **Transportation is deferred (ADR-022)**:
  - V1 calculates no travel: no routes, travel times, ETAs, traffic or fares. NavigIQ never claims an actual travel time.
  - The planner separates consecutive stops with a documented transition buffer and keeps a day geographically coherent (hop distance is a preference, never a time).
  - There is no OSRM dependency in the active V1 path. Core planning asks a `TransportationProvider` (today the Null provider); a future provider may supply real travel-time matrices through that integration point.
  - OSRM (NQ-018/019, code preserved under `backend/app/services/routing`, container behind the compose `routing` profile) is a deferred/future capability. Public transit was removed (ADR-007).
- **Background jobs**: Celery is not used. No V1 workload needs a task queue (ingestion runs as a CLI; everything else is request-scoped). Add it only when a real background workload exists.

## 3. Boundaries & Restrictions
- **LLM Boundaries**: The LLM understands, reasons, orchestrates, selects tools, and explains. It is an orchestration and language layer.
- **Deterministic Boundaries**: The deterministic system calculates, optimizes, validates, enforces constraints, and provides authoritative data.
- **Agent Restrictions**: Agentic AI is bounded. The agent flow must always use typed tools, run deterministic services, and validate results before responding.
- **No Arbitrary Execution**: 
  - No arbitrary SQL.
  - No arbitrary shell commands.
  - No arbitrary filesystem access.
  - No arbitrary HTTP requests.
- **No Fabricated Data**: Never invent external data or coordinates.
- **No Unnecessary Microservices**: Only separate containers when operationally necessary.
- **No Silent Architecture Changes**: Any material change requires explicit user approval.

## 4. Execution Workflow
- **Task-by-Task Execution**: The agent must work on ONLY ONE TASK at a time.
- **Approval Gate**: The agent MUST NOT automatically continue to the next task without EXPLICIT user approval.
- **Testing Rules**: Test-first mindset. Implement, test, fix, re-test, verify integration. Do not report success merely because code compiles.
- **Security Rules**: Never commit secrets (.env, API keys, etc.). Use `.env.example`.

## 5. Definition of Done
A task is complete only when:
- [ ] Requirements understood
- [ ] Implementation completed
- [ ] Code reviewed
- [ ] Tests/checks executed
- [ ] Errors resolved
- [ ] Relevant integration verified
- [ ] Documentation updated
- [ ] TASKS.md updated
- [ ] Git diff reviewed
- [ ] Commit created if appropriate
- [ ] Result reported to user
- [ ] User approval requested for next task
