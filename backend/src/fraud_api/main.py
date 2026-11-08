from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from fraud_api.artifacts import verified_artifact
from fraud_api.config import get_settings
from fraud_api.database import get_engine
from fraud_api.errors import ApiError
from fraud_api.sessions import router
from fraud_api.simulation import router as simulation_router
from fraud_api.transactions import router as transaction_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        verified_artifact()
    except ApiError:
        pass  # Stay available for health diagnostics; scoring remains disabled.
    yield


app = FastAPI(
    lifespan=lifespan,
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
app.include_router(simulation_router)
app.include_router(transaction_router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Do not echo arbitrary submitted values (which might accidentally contain secrets).
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": details,
            }
        },
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health", tags=["operations"])
def health() -> JSONResponse:
    try:
        model = verified_artifact()
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1 FROM demo_sessions LIMIT 1"))
            connection.execute(text("SELECT 1 FROM transactions LIMIT 1"))
            connection.execute(text("SELECT 1 FROM alerts LIMIT 1"))
    except (ApiError, SQLAlchemyError):
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ready", "model_version": model.model_version})
