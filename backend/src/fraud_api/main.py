from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from fraud_api.config import get_settings
from fraud_api.errors import ApiError
from fraud_api.sessions import router

app = FastAPI(
    title="Fraud Detection API",
    version="0.1.0",
    description=(
        "Score synthetic transactions using rules and a lightweight classifier. "
        "This demo does not process real payments. Service implementation is in progress."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health", status_code=503, tags=["operations"])
def health() -> dict[str, str]:
    # Remain unready until database and verified model checks are implemented.
    return {"status": "unavailable", "code": "SERVICE_INITIALIZING"}
