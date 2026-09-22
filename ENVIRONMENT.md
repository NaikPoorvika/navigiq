# NavigIQ environment

## Runtime on this workstation (2026-09-22)

| Service | Where | Port | Notes |
|---|---|---|---|
| PostgreSQL 16 + PostGIS 3.4 + pgvector 0.8 | container `navigiq_db` (`infrastructure/database`) | 5433 | database `navigiq`; tests create `navigiq_test` |
| Redis 7 | container `navigiq_redis` | 6379 | optional: rate limits shared across API workers, caches |
| NavigIQ API (FastAPI) | `backend/` venv or container `navigiq_backend` | **8010** | 8000 belongs to another service on this machine (baymax-api) — do not use it |
| Web app | Vite dev server / container `navigiq_web` (nginx) | 5173 dev · 8080 container | proxies `/api` to the API |
| Ollama | host (GPU) | 11434 | `qwen3:14b`, `nomic-embed-text`; optional |
| OSRM | container, `routing` profile only | 5000 | deferred (ADR-022) |

Toolchain used: Python 3.11 (backend venv), Node 22.14, npm 10.9, Docker
28 / Compose 2.33, Playwright browsers (Chromium, Firefox, WebKit).

Settings: `backend/.env.example` (every API setting, with defaults),
`infrastructure/.env.example` (database credentials for compose),
`frontend/.env.example` (dev proxy target, E2E base URL). Real `.env` files
are git-ignored.

Known constraint of this network: the Python package index and the Docker
registry were unreachable during the final work, so the container images were
validated with `docker compose config` but not built here; CI builds them.

---

The sections below are the original environment notes, kept for history.


## OSRM build (NQ-018)

- Source: infrastructure/osrm-data/map.osm.pbf (72.7 MB, BBBike extract)
- Car profile: extract 6.1 s, partition 12.8 s, customize ~3 s
- Peak RAM: 1.22 GB (extract), 1.12 GB (partition), 0.64 GB (customize)
- Graph: 8,249,479 raw nodes -> 2,707,241 used, 3,206,689 edge-expanded edges
- Boundary nodes: L1 149,006 / L2 25,745 / L3 4,292
- Algorithm: MLD (supports alternative routes, needed for NQ-052 rerouting)
- Verified: Indiranagar -> Cubbon Park = 6,433 m / 517 s
- Serving: osrm-car :5000, osrm-foot :5001, --max-table-size 100

## OSRM build (NQ-018)

- Source: infrastructure/osrm-data/map.osm.pbf (72.7 MB, BBBike extract)
- Car profile: extract 6.1 s, partition 12.8 s, customize ~3 s
- Peak RAM: 1.22 GB extract, 1.12 GB partition, 0.64 GB customize
- Graph: 8,249,479 raw nodes -> 2,707,241 used, 3,206,689 edge-expanded edges
- Boundary nodes: L1 149,006 / L2 25,745 / L3 4,292
- Algorithm: MLD (supports alternative routes, needed for NQ-052 rerouting)
- Verified: Indiranagar -> Cubbon Park = 6,433 m / 517 s
- Serving: osrm-car :5000, osrm-foot :5001, --max-table-size 100

## Ollama / LLM benchmark environment (NQ-027)

- GPU: NVIDIA RTX A5000, 24,564 MiB total, driver 596.51
- Ollama: 0.33.3, served at http://localhost:11434, models on E:\Ollama\Models
- Measured 2026-09-12. Full environment (OS, Python, git commit) is captured
  automatically per run in `ai/benchmarks/results/*.json` rather than copied
  here by hand, so it cannot drift from what actually produced the numbers.
- Candidate models present locally at benchmark time (no downloads needed):
  qwen3:8b, qwen3.5:9b, gemma3:12b, qwen3:14b, mistral-small3.2:24b,
  llama3:8b, bge-m3, nomic-embed-text
- All six generation candidates loaded fully into VRAM (no CPU offload) at
  every context they support; `llama3:8b` is capped at 8192 context by the
  model itself - requesting 16384 is silently clamped by Ollama, caught by
  the benchmark's residency probe rather than assumed from documentation.
- Ollama serialises generation on this single-GPU workstation: request
  throughput was flat across concurrency 1/2/4 for every candidate, while p95
  latency scaled roughly linearly with the concurrency level. Concurrent
  submission does not increase throughput here - see ADR-012.
- Full results, methodology and the ADR-012 decision evidence:
  `ai/benchmarks/README.md`, `ai/benchmarks/results/nq027_final.json`,
  `docs/adr/ADR-012-model-selection.md`.
