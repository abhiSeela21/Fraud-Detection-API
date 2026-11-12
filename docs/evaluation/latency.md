# Local scoring load test

Host: `macOS-26.6.2-arm64-arm-64bit-Mach-O` (8 logical CPUs). Client: Python 3.14.0. Server: one Uvicorn worker in Docker Compose with PostgreSQL 17, over localhost HTTP.
Model: `model-v2-recall-50d731a331ac`.

Each row pools three trials of 240 new scores. Eight independent seeded runs each submit 30 transactions in event order. Concurrency is the maximum number of requests in flight. In shared mode the runs use one session and contend for its database lock. In separate mode each run has its own session. Both modes use the same transaction sequences and warm one request per run before timing.

| Sessions | Concurrency | Requests | Errors | p50 ms | p95 ms | p99 ms | Successful requests/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| shared | 1 | 720 | 0 | 3.37 | 5.81 | 9.27 | 272.08 |
| shared | 4 | 720 | 0 | 8.88 | 11.09 | 17.97 | 426.42 |
| shared | 8 | 720 | 0 | 19.24 | 28.89 | 58.19 | 390.77 |
| separate | 1 | 720 | 0 | 3.72 | 5.40 | 7.86 | 255.83 |
| separate | 4 | 720 | 0 | 9.12 | 12.78 | 35.93 | 410.11 |
| separate | 8 | 720 | 0 | 20.74 | 33.58 | 54.72 | 354.79 |

Latency uses nearest-rank percentiles of successful HTTP responses and includes database persistence. Throughput divides successful requests by total timed wall time, including failed calls. Session creation, batch generation and warm-up are outside timed windows. This measures short bursts on a warm local service. It does not measure sustained capacity, production rate limits, provider wake-up or public-network latency.

From the repo root, start a temporary loopback API alongside the existing migrated database:

```sh
docker compose run -d --name fraud-benchmark-api -p 127.0.0.1:8001:8000 \
  -e FRAUD_REQUESTS_PER_MINUTE_IP=10000 \
  -e FRAUD_REQUESTS_PER_MINUTE_TOKEN=1000 \
  -e FRAUD_SESSIONS_PER_MINUTE_IP=100 api
cd backend
uv run python training/benchmark.py
docker rm -f fraud-benchmark-api
```

The temporary process uses higher rate limits so the test measures scoring capacity. Use a local database with migrations applied. This run creates temporary synthetic sessions. See [raw measurements](latency.json) for HTTP status and transport error counts.
