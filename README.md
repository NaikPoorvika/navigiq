# NavigIQ

**Bengaluru, figured out.** NavigIQ helps you decide what to do in and around
Bengaluru (up to 90 km), learn about the places you're going, and plan a day —
or a few days — that actually works: open when you arrive, within budget,
paced the way you like.

- **Discover** — ranked places for a mood, a time of day, an area or a budget,
  each with the reasons it was picked. "I'm bored" and "Surprise me" for
  when you don't know what you want.
- **Understand** — ask about a place and get an answer that cites its sources,
  or an honest "I don't have reliable information for that yet."
- **Plan** — one to seven days, from a sentence ("a relaxed Saturday with a
  lake, lunch and a museum under ₹1500") or a form. Change it by talking
  ("make day 2 cheaper", "remove the museum") or with one tap; try a what-if
  side by side; every version is kept.

The language model understands and communicates. Deterministic services
decide every fact, ranking, schedule and check (ADR-002, ADR-021).

## What NavigIQ does not do

Stated so nothing is implied that isn't there:

- **No travel times, routes or fares.** Transportation is deferred (ADR-022).
  Plans leave a buffer between stops and say so. Maps show pins, not routes.
- **No ratings or reviews.** No lawful free source exists (ADR-008). Ranking
  uses documented prominence, fit to the request, distance and diversity.
- **Costs are estimates** by category and place, per person, excluding travel.
- **Opening hours are often typical, not verified** (OSM has hours for under
  10% of places); unverified hours are flagged wherever they're shown.
- **No public transit** (ADR-007) and **no live events** in this version.

## Quick start

Requirements: Docker, Python 3.11+, Node 22+. Optional: Ollama with
`qwen3:14b` and `nomic-embed-text` (without it NavigIQ uses its rule-based
understanding and extractive answers; discovery and planning are unaffected).

```bash
# 1. Database and cache
cd infrastructure
cp .env.example .env
docker compose up -d db redis

# 2. API (port 8010 — 8000 is used by another service on this workstation)
cd ../backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # bin/ on Linux/macOS
cp .env.example .env            # set SECRET_KEY
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -m app.ingestion.run        # places (uses cached raw data if present)
.venv/Scripts/python -m app.knowledge.ingest     # knowledge corpus + embeddings
.venv/Scripts/uvicorn app.main:app --port 8010 --workers 4

# 3. Web app
cd ../frontend
npm ci
npm run dev                      # http://127.0.0.1:5173, proxies /api to :8010
```

Everything in containers instead: `cd infrastructure && docker compose up -d
--build` — web on http://localhost:8080, API on :8010 (migrations run on
start; load data with the ingestion commands via `docker compose exec backend`).

## Tests and quality gates

| Suite | Command | Current |
|---|---|---|
| Backend (unit, API, DB, migrations, agent fuzz, injection, failure injection) | `cd backend && pytest` | 895 passed, 7 skipped (live Ollama); 84% line coverage |
| Lint | `ruff check app tests evals` · `npm run lint` · `npm run typecheck` | clean |
| Frontend unit / component | `cd frontend && npm test` | 62 passed |
| End to end, real API (Chromium, Firefox, WebKit, phone) incl. axe WCAG 2.1 AA | `npx playwright test` | 72 passed, 4 skipped by design |
| Evaluation gates on held-out splits | `python -m evals.run --llm both` | see below |
| Load (1–50 users) | `python scripts/load_test.py` | 0 errors, 51 req/s at 50 users, p50 131 ms — `docs/reports/load_test.md` |
| Backup / restore | `bash scripts/backup_restore_check.sh` | identical row counts on 15 tables |

**Quality gates — latest untouched (held-out) result for each** (full history,
including every miss, in `docs/reports/evaluation_history.md`):

| Gate | Target | Latest held-out | |
|---|---|---|---|
| Intent accuracy (rules + qwen3:14b) | ≥ 0.95 | 0.967 | met |
| TripSpec schema-valid | ≥ 0.99 | 1.00 | met |
| TripSpec critical fields | ≥ 0.92 | 0.946 | met |
| TripSpec relative dates | ≥ 0.98 | 0.958 | **missed** |
| TripSpec hard constraints | ≥ 0.98 | 0.947 | **missed** |
| Modification operations / targets | ≥ 0.95 | 1.00 / 1.00 | met |
| Reference resolution | ≥ 0.95 | 1.00 | met |
| Retrieval hybrid recall@6 | ≥ 0.85 | 1.00 | met |
| Citation coverage · numeric grounding failures · fabricated citations · fabricated URLs | ≥ 0.98 · 0 · 0 · 0 | 1.00 · 0 · 0 · 0 | met |

The two TripSpec misses come from the eighth held-out split (40 new
sentences). Every miss it exposed except one deliberately ambiguous phrasing
has since been fixed with a regression test, and the full development set
(360 sentences) passes all gates. That is not a held-out result, and it is
reported as such: the next fresh split is the real check.

The Playwright suite and the evals need the loaded Bengaluru data, so they run
on the workstation; CI (`.github/workflows/ci.yml`) runs lint, the backend
suite on the project's PostGIS/pgvector image with synthetic fixtures, the
frontend unit tests and build, and the container builds.

## Repository

| Path | What |
|---|---|
| `backend/app` | FastAPI modular monolith: `api/` routes, `assistant/` bounded agent + NLU, `services/planning/` engine, CP-SAT optimizer, validators, trips, `services/recommendation/`, `knowledge/` retrieval + grounded answers, `ingestion/` data pipeline, `llm/` gateway |
| `backend/tests`, `backend/evals` | Tests; evaluation harness and datasets (`data/evals`) |
| `frontend/src` | React app: `routes/` screens, `components/`, `lib/` (API client, auth, queries), `styles/index.css` (design tokens) |
| `frontend/e2e` | Playwright end-to-end and accessibility tests |
| `data/` | Config (categories, geography, weights, collections, lexicon), curated places, knowledge guides, eval sets; `artifacts/` is regenerable and untracked |
| `infrastructure/` | Docker Compose, database image |
| `scripts/` | Load test, backup/restore check, environment checks |
| `docs/` | ADR evidence, reports (evaluation, load, data quality), frontend design brief |

Read next: [ARCHITECTURE.md](ARCHITECTURE.md), [DECISIONS.md](DECISIONS.md),
[DATA.md](DATA.md), [ENVIRONMENT.md](ENVIRONMENT.md), [TASKS.md](TASKS.md),
[docs/frontend/DESIGN.md](docs/frontend/DESIGN.md).

## Data attribution

Place data © OpenStreetMap contributors (ODbL). Descriptions from Wikipedia
(CC BY-SA 4.0); identifiers from Wikidata (CC0). Photos from Wikimedia Commons
under their stated licences, credited where shown. Weather by Open-Meteo
(CC BY 4.0). Map tiles © OpenStreetMap. Mood illustrations are AI-generated
artwork from the NavigIQ design concept and are labelled as illustrations.
