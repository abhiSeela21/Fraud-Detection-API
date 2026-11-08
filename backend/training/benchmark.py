"""Small HTTP scoring load; run after Docker Compose starts and migrations apply."""

import json
import os
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    url = "http://localhost:8000"
    measurements = []
    with httpx.Client(base_url=url, timeout=30) as client:
        health = client.get("/health")
        health.raise_for_status()
        for concurrency in [1, 4]:
            session = client.post("/v1/sessions", json={"mode": "api"})
            session.raise_for_status()
            headers = {"Authorization": f"Bearer {session.json()['token']}"}
            run_id = str(uuid4())
            events = []
            for offset in [0, 50]:
                batch = client.post(
                    "/v1/simulations/batch",
                    json={
                        "run_id": run_id,
                        "offset": offset,
                        "count": 50,
                        "seed": 42,
                    },
                    headers=headers,
                )
                batch.raise_for_status()
                events.extend(batch.json()["transactions"])

            def score(event, headers=headers):
                start = time.perf_counter()
                result = client.post("/v1/transactions/score", json=event, headers=headers)
                elapsed = (time.perf_counter() - start) * 1000
                result.raise_for_status()
                return elapsed

            # One untimed request warms HTTP/pool paths; no fabricated cold-start claim.
            score(events[0])
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                values = list(executor.map(score, events[1:]))
            duration = time.perf_counter() - start
            ordered = sorted(values)
            measurements.append(
                {
                    "concurrency": concurrency,
                    "requests": len(values),
                    "p50_ms": statistics.median(values),
                    "p95_ms": ordered[int(0.95 * (len(values) - 1))],
                    "p99_ms": ordered[int(0.99 * (len(values) - 1))],
                    "max_ms": max(values),
                    "requests_per_second": len(values) / duration,
                }
            )
    report = {
        "environment": {
            "host": platform.platform(),
            "architecture": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "python_client": platform.python_version(),
            "server": "Docker Compose API Python 3.12 + PostgreSQL 17; localhost HTTP",
        },
        "model_version": health.json()["model_version"],
        "measurements": measurements,
        "limitations": "Warm local HTTP latency including database persistence; each load uses one session, so writes serialize. Concurrent arrival can change available history. No Render/network/cold-start claim. Synthetic results only.",
    }
    output = Path(__file__).resolve().parents[2] / "docs/evaluation"
    (output / "latency.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Local API latency",
        "",
        report["limitations"],
        "",
        "Reproduce from backend: `uv run python training/benchmark.py` after `docker compose up --build -d` and migrations.",
        "",
        f"Environment: `{report['environment']}`. Model: `{report['model_version']}`.",
        "",
        "Each load uses 99 scored requests after one warm-up, a separate session, seed 42, and a mixed commuter simulation. Errors fail the benchmark. Session creation and batch generation are excluded from timed calls. Percentiles use nearest lower ordered samples; only 99 samples makes tail estimates noisy.",
        "",
        "| Concurrency | Requests | p50 ms | p95 ms | p99 ms | Max ms | Requests/s |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in measurements:
        lines.append(
            f"| {row['concurrency']} | {row['requests']} | {row['p50_ms']:.2f} | {row['p95_ms']:.2f} | {row['p99_ms']:.2f} | {row['max_ms']:.2f} | {row['requests_per_second']:.2f} |"
        )
    lines += [
        "",
        "Cold process startup, provider wake-up and public-network latency were not measured. These local measurements do not predict public free-tier availability or throughput.",
        "",
    ]
    (output / "latency.md").write_text("\n".join(lines))
    print(json.dumps(measurements, indent=2))


if __name__ == "__main__":
    main()
