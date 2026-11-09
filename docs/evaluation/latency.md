# Local API latency

Warm local HTTP latency including database persistence; each load uses one session, so writes serialize. Concurrent arrival can change available history. No Render/network/cold-start claim. Synthetic results only.

Reproduce from backend: `uv run python training/benchmark.py` after `docker compose up --build -d` and migrations.

Environment: `{'host': 'macOS-26.6.2-arm64-arm-64bit-Mach-O', 'architecture': 'arm64', 'logical_cpus': 8, 'python_client': '3.14.0', 'server': 'Docker Compose API Python 3.12 + PostgreSQL 17; localhost HTTP'}`. Model: `model-v2-recall-50d731a331ac`.

Each load uses 99 scored requests after one warm-up, a separate session, seed 42, and a mixed commuter simulation. Errors fail the benchmark. Session creation and batch generation are excluded from timed calls. Percentiles use nearest lower ordered samples; only 99 samples makes tail estimates noisy.

| Concurrency | Requests | p50 ms | p95 ms | p99 ms | Max ms | Requests/s |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 99 | 5.00 | 11.28 | 17.64 | 26.25 | 173.52 |
| 4 | 99 | 16.36 | 29.49 | 100.78 | 101.50 | 203.78 |

Cold process startup, provider wake-up and public-network latency were not measured. These local measurements do not predict public free-tier availability or throughput.
