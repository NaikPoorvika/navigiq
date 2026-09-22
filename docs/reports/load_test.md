# Load test — 2026-09-22

`scripts/load_test.py` against the real stack on the workstation (FastAPI,
PostgreSQL/PostGIS/pgvector with the full Bengaluru inventory, Redis, CP-SAT,
Open-Meteo, and qwen3:14b on the RTX A5000). Nothing is mocked.

Each virtual user is its own browser session and loops over a realistic mix
with 0.2–0.8 s of think time: context 10%, recommendations 25%, text search
20%, place details 15%, collections 10%, plan preview (a full CP-SAT plan)
10%, assistant message 10%. 30 s per level.

## Results

### One API process (before ADR-034)

| Users | Requests | Req/s | Errors | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 38 | 1.2 | 0 | 25 | 1962 | 3139 |
| 5 | 209 | 6.9 | 0 | 40 | 1583 | 2740 |
| 10 | 388 | 11.8 | 0 | 79 | 1949 | 2971 |
| 25 | 716 | 21.8 | 0 | 315 | 2299 | 3639 |
| 50 | 729 | 20.8 | 0 | **1258** | 4326 | 5357 |

Throughput stops growing at ~21 req/s: recommendation scoring is CPU-bound
Python, and every request in the process waits for it. Even a place-detail
read took 1.2 s at the median under 50 users.

### Four API processes (ADR-034, the shipped configuration)

| Users | Requests | Req/s | Errors | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 38 | 1.2 | 0 | 23 | 1970 | 3195 |
| 5 | 190 | 6.1 | 0 | 38 | 2167 | 2819 |
| 10 | 373 | 11.4 | 0 | 49 | 2047 | 3538 |
| 25 | 925 | 27.7 | 0 | 81 | 2430 | 3481 |
| 50 | 1714 | **50.9** | 0 | **131** | 2293 | 3915 |

Per endpoint at 50 users:

| Endpoint | n | p50 | p95 | max |
|---|---:|---:|---:|---:|
| GET /context | 194 | 19 | 217 | 295 |
| GET /collections | 146 | 22 | 279 | 356 |
| GET /pois/{id} | 226 | 43 | 327 | 595 |
| GET /pois?q= | 370 | 61 | 413 | 744 |
| POST /pois/recommend | 418 | 221 | 628 | 1270 |
| POST /assistant/chat | 190 | 351 | 2326 | 6033 |
| POST /plans/preview | 170 | 1968 | 4170 | 4347 |

Throughput still rises linearly with users at 50, so this is not the ceiling.

### Four processes, one model call per process

Same as above with `LLM_MAX_CONCURRENCY=1` (and Redis-shared rate limits):
50 users, 1,571 requests, 37.6 req/s, 0 errors, p50 110 ms — but assistant
p95 rose to 10.3 s because model calls queued in the API instead of on the
GPU. The shipped setting is therefore 2 per process (8 in flight at most;
Ollama queues the rest on the GPU, and each process keeps its breaker and
queue timeout).

## What it means

- **Zero errors at every level**, including the model-backed assistant.
- Reads (context, collections, place pages, search) stay well under half a
  second at p95 with 50 simultaneous users.
- The slow path is honest work: a plan preview is a full CP-SAT solve plus
  independent validation (~2 s median under load, 0.4–1 s idle). Multi-day
  trips cost one solve per day.
- The first `GET /context` of a cold process fetches the forecast
  (Open-Meteo, ~2–3 s); it is cached afterwards, and if the provider is down
  the answer says "unavailable" after a 3 s timeout and backs off for 5 min.

## Not measured here

- A multi-hour soak. The per-conversation state is bounded (capped lists in
  `ConversationState`), caches are LRU-bounded, and the rate limiter caps its
  key table; a long soak run is still worth doing before a public launch.
- More than one machine. NavigIQ is single-workstation by design (ADR-001).

Reproduce: start the API (`uvicorn app.main:app --port 8010 --workers 4`),
then `python scripts/load_test.py --duration 30`.
