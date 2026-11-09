"""Run the synthetic API journey without printing or saving the session token."""

import argparse
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        response = client.post("/v1/sessions", json={"mode": "api"})
        response.raise_for_status()
        headers = {"Authorization": f"Bearer {response.json()['token']}"}
        response = client.post(
            "/v1/simulations/batch",
            headers=headers,
            json={
                "run_id": str(uuid4()),
                "seed": 42,
                "count": 20,
                "scenario": "mixed",
            },
        )
        response.raise_for_status()
        transactions = response.json()["transactions"]
        results = []
        for transaction in transactions:
            response = client.post("/v1/transactions/score", headers=headers, json=transaction)
            response.raise_for_status()
            results.append(response.json())
        retry = client.post("/v1/transactions/score", headers=headers, json=transactions[0])
        retry.raise_for_status()
        assert retry.json() == results[0], "Idempotent retry changed the stored result"
        alerts = client.get("/v1/alerts", headers=headers)
        alerts.raise_for_status()
        items = alerts.json()["items"]
        if items:
            identifier = items[0]["score"]["alert_id"]
            feedback = client.patch(
                f"/v1/alerts/{identifier}/feedback", headers=headers, json={"label": "fraud"}
            )
            feedback.raise_for_status()
        print(
            f"Scored {len(results)} synthetic transactions; found {len(items)} alerts; "
            "idempotent retry verified."
        )
        print("Feedback saved on one simulated alert." if items else "No alerts in this run.")


if __name__ == "__main__":
    main()
