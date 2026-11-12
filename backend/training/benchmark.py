"""Measure warm scoring HTTP requests against a dedicated local Compose API."""

import argparse
import json
import math
import os
import platform
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx

OUTPUT = Path(__file__).resolve().parents[2] / "docs/evaluation"
LANES = 8
REQUESTS_PER_LANE = 30
REPEATS = 3


def create_session(client):
    response = client.post("/v1/sessions", json={"mode": "api"})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['token']}"}


def prepare_workload(client, mode):
    shared = create_session(client) if mode == "shared" else None
    lanes = []
    for _ in range(LANES):
        headers = shared if shared is not None else create_session(client)
        batch = client.post(
            "/v1/simulations/batch",
            json={
                "run_id": str(uuid4()),
                "count": REQUESTS_PER_LANE + 1,
                "seed": 42,
                "profile": "commuter",
                "scenario": "mixed",
            },
            headers=headers,
        )
        batch.raise_for_status()
        events = batch.json()["transactions"]
        assert len(events) == REQUESTS_PER_LANE + 1
        warmup = client.post("/v1/transactions/score", json=events[0], headers=headers)
        warmup.raise_for_status()
        lanes.append((headers, events[1:]))
    return lanes


def measure(client, concurrency, lanes):
    def score_lane(lane):
        headers, events = lane
        results = []
        for event in events:
            started = time.perf_counter()
            try:
                response = client.post("/v1/transactions/score", json=event, headers=headers)
                status = str(response.status_code)
            except httpx.RequestError as exc:
                status = type(exc).__name__
            results.append((status, (time.perf_counter() - started) * 1000))
        return results

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = [result for lane in executor.map(score_lane, lanes) for result in lane]
    return results, time.perf_counter() - started


def summarize(mode, concurrency, trials):
    statuses = Counter(status for results, _ in trials for status, _ in results)
    latencies = sorted(ms for results, _ in trials for status, ms in results if status == "200")
    attempts = statuses.total()
    total_seconds = sum(seconds for _, seconds in trials)

    def percentile(fraction):
        return latencies[math.ceil(fraction * len(latencies)) - 1] if latencies else None

    return {
        "mode": mode,
        "concurrency": concurrency,
        "requests": attempts,
        "statuses": dict(sorted(statuses.items())),
        "error_rate": (attempts - len(latencies)) / attempts,
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "successful_requests_per_second": len(latencies) / total_seconds,
    }


def write_report(report):
    (OUTPUT / "latency.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Local scoring load test",
        "",
        f"Host: `{report['environment']['host']}` "
        f"({report['environment']['logical_cpus']} logical CPUs). "
        f"Client: Python {report['environment']['python_client']}. "
        "Server: one Uvicorn worker in Docker Compose with PostgreSQL 17, over localhost HTTP.",
        f"Model: `{report['model_version']}`.",
        "",
        "Each row pools three trials of 240 new scores. Eight independent seeded runs each submit "
        "30 transactions in event order. Concurrency is the maximum number of requests in flight. "
        "In shared mode the runs use one session and contend for its database lock. "
        "In separate mode each run has its own session. Both modes use the same transaction "
        "sequences and warm one request per run before timing.",
        "",
        "| Sessions | Concurrency | Requests | Errors | p50 ms | p95 ms | p99 ms | Successful requests/s |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["measurements"]:
        errors = row["requests"] - row["statuses"].get("200", 0)
        percentiles = " | ".join(
            f"{row[key]:.2f}" if row[key] is not None else "—"
            for key in ("p50_ms", "p95_ms", "p99_ms")
        )
        lines.append(
            f"| {row['mode']} | {row['concurrency']} | {row['requests']} | {errors} | "
            f"{percentiles} | {row['successful_requests_per_second']:.2f} |"
        )
    lines += [
        "",
        "Latency uses nearest-rank percentiles of successful HTTP responses and includes database "
        "persistence. Throughput divides successful requests by total timed wall time, including "
        "failed calls. Session creation, batch generation and warm-up are outside timed windows. "
        "This measures short bursts on a warm local service. It does not measure sustained capacity, "
        "production rate limits, provider wake-up or public-network latency.",
        "",
        "From the repo root, start a temporary loopback API alongside the existing migrated database:",
        "",
        "```sh",
        "docker compose run -d --name fraud-benchmark-api -p 127.0.0.1:8001:8000 \\",
        "  -e FRAUD_REQUESTS_PER_MINUTE_IP=10000 \\",
        "  -e FRAUD_REQUESTS_PER_MINUTE_TOKEN=1000 \\",
        "  -e FRAUD_SESSIONS_PER_MINUTE_IP=100 api",
        "cd backend",
        "uv run python training/benchmark.py",
        "docker rm -f fraud-benchmark-api",
        "```",
        "",
        "The temporary process uses higher rate limits so the test measures scoring capacity. "
        "Use a local database with migrations applied. This run creates temporary synthetic sessions. "
        "See [raw measurements](latency.json) for HTTP status and transport error counts.",
        "",
    ]
    (OUTPUT / "latency.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001, help="Port of the local benchmark API")
    args = parser.parse_args()
    measurements = []
    with httpx.Client(
        base_url=f"http://127.0.0.1:{args.port}", timeout=15, trust_env=False
    ) as client:
        health = client.get("/health")
        health.raise_for_status()
        for mode in ("shared", "separate"):
            for concurrency in (1, 4, 8):
                trials = [
                    measure(client, concurrency, prepare_workload(client, mode))
                    for _ in range(REPEATS)
                ]
                row = summarize(mode, concurrency, trials)
                measurements.append(row)
                print(json.dumps(row), flush=True)
    write_report(
        {
            "environment": {
                "host": platform.platform(),
                "logical_cpus": os.cpu_count(),
                "python_client": platform.python_version(),
            },
            "model_version": health.json()["model_version"],
            "measurements": measurements,
        }
    )
    if any(row["error_rate"] for row in measurements):
        raise SystemExit("Scoring errors occurred. See the status counts in latency.json.")


if __name__ == "__main__":
    main()
