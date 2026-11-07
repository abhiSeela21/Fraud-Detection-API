from fastapi import FastAPI

app = FastAPI(
    title="Fraud Detection API",
    version="0.1.0",
    description=(
        "Score synthetic transactions using rules and a lightweight classifier. "
        "This demo does not process real payments. Service implementation is in progress."
    ),
)


@app.get("/health", status_code=503, tags=["operations"])
def health() -> dict[str, str]:
    # Remain unready until database and verified model checks are implemented.
    return {"status": "unavailable", "code": "SERVICE_INITIALIZING"}
