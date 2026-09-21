# NavigIQ

## Project Purpose
NavigIQ is a constraint-aware travel planner for Bengaluru that runs entirely on
one workstation. Given where you are, when you're free, your budget and what
you'd like to do, it returns a real itinerary — real places, real travel times,
real opening hours — verified by an independent validator.

**Governing principle:** LLMs understand, orchestrate and explain.
Deterministic systems calculate, optimize, validate and enforce. The model is
never the source of truth for coordinates, distances, times, costs or hours.
If the LLM is unavailable, the planner still works.

## Current Status
- **Phase 1 — Deterministic Planner:** 15 of 16 tasks. Only NQ-026 (map UI) remains
- **Also built:** place gazetteer (ADR-011), multi-day trips (ADR-012),
  LLM draft contract (ADR-013)
- **Data:** 14,851 POIs and 9,163 places from OpenStreetMap
- **Tests:** 190 backend + 30 pipeline

## Architecture Summary
A **modular monolith** on a single workstation. The **deterministic planner**
(PostGIS search, OSRM routing, OR-Tools CP-SAT optimization, independent
validation) is authoritative. The **LLM** is an orchestration and language
layer that reaches the planner only through typed tools.

```
TripSpec -> semantic validation -> weather -> feasibility precheck
         -> POI search -> ranking -> multi-modal arcs -> CP-SAT
         -> independent validation -> persistence
```

## Hardware Constraints
- CPU: Intel Xeon W-2295 @ 3.00 GHz (18 cores / 36 threads)
- RAM: 128 GB
- GPU: NVIDIA RTX A5000 (24 GB VRAM)
- Storage: 1.4 TB
- OS: Windows 64-bit (WSL2 supported)

## Prerequisites
- Python 3.10+
- Node.js & npm (React/Vite frontend)
- Docker & Docker Compose
- Git
- Ollama (local inference, from Phase 2)

## Quick Start

```powershell
# 1. Environment files (gitignored - create from the examples)
copy infrastructure\.env.example infrastructure\.env
copy backend\.env.example backend\.env     # then set a unique SECRET_KEY

# 2. Services
docker compose -f infrastructure\docker-compose.yml up -d db redis osrm-car osrm-foot

# 3. Schema and categories
cd backend
alembic upgrade head
cd ..

# 4. Data (OSM extract at infrastructure/osrm-data/map.osm.pbf - see DATA.md)
python data\pipelines\osm_extract.py
python data\pipelines\load_pois.py
python data\pipelines\parse_hours.py
python data\pipelines\place_extract.py
python data\pipelines\load_places.py

# 5. API
cd backend
python -m uvicorn app.main:app --port 8000 --reload
```

OSRM graphs are built from the same `.pbf` — see `ENVIRONMENT.md`.
`python scripts\audit.py` checks git, services, requirements and tests in one run.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/plan` | One-day itinerary |
| POST | `/api/v1/plan/trip` | Multi-day trip (independent days) |
| POST | `/api/v1/plan/draft` | LLM draft → clarifying questions or a planned trip |
| POST | `/api/v1/plan/preview-feasibility` | Fast feasibility check, no optimization |
| GET | `/api/v1/places/resolve?q=` | Place name → coordinates, with confidence |
| GET | `/api/v1/pois/search` | Filtered POI search |
| GET | `/api/v1/pois/categories` | Categories with POI counts |
| GET | `/api/v1/pois/{id}` | POI detail with opening hours |

Errors carry a stable `code` (`INFEASIBLE`, `NO_CANDIDATES`,
`ROUTING_UNAVAILABLE`, `SEMANTIC_INVALID`, `VALIDATION_FAILED`). Clients switch
on the code, never on the message. Times are minutes since midnight; costs are
integer rupees.

## Repository Structure
- `/backend` — FastAPI app, SQLAlchemy models, Alembic migrations, tests
- `/frontend` — React, Vite and Leaflet
- `/data/pipelines` — OSM extraction and loading
- `/data/config` — fares, traffic factors, ranking weights
- `/data/mappings` — OSM tag → category mapping
- `/infrastructure` — Docker Compose, database image, OSRM data
- `/scripts` — smoke tests, benchmarks, audit
- `/ai` — LLM orchestration and benchmarks

## Development Instructions
Work is task-gated. Read `CLAUDE.md`, `ARCHITECTURE.md`, `DECISIONS.md` and
`TASKS.md` before starting — they are binding, not advisory.

## What NavigIQ does not do

Stated explicitly so nothing is implied that isn't supported:

- **No live traffic.** Travel times come from free-flow routing adjusted by a
  static time-of-day table. They are estimates and are labelled as such.
- **No public transit.** Metro was built and removed (ADR-007) after losing
  every route comparison. Bus routing is not implemented.
- **No real-time fares.** Auto and cab costs are formula-based estimates from
  published fare structures, not live pricing.
- **No POI ratings.** No lawful free source exists. Ranking uses a
  documentation-based prominence score (ADR-008); star ratings are never shown.
- **Opening hours are sparse, and enforced only where known.** Only 8.5% of
  POIs carry real hours from OpenStreetMap; those are hard constraints. The rest
  use category defaults at low confidence and stay soft — shown as "hours
  unverified".
- **No true multi-day planning.** Multiple days are planned as independent
  single days from the same starting point. No accommodation, no overnight
  travel, no optimization across days (ADR-012).

## Data attribution

POI, place and map data © OpenStreetMap contributors, licensed under ODbL.
Weather from Open-Meteo.