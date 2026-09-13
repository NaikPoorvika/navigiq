
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
