from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from fraud_api.artifacts import verified_artifact
from fraud_api.config import get_settings
from fraud_api.database import get_engine
from fraud_api.errors import ApiError, ErrorEnvelope
from fraud_api.guardrails import GuardrailsMiddleware, limiter
from fraud_api.sessions import router
from fraud_api.simulation import router as simulation_router
from fraud_api.transactions import router as transaction_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    limiter.clear()
    try:
        verified_artifact()
    except ApiError:
        pass  # Stay available for health diagnostics; scoring remains disabled.
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Fraud Detection API",
    version="0.1.0",
    responses={
        status: {"model": ErrorEnvelope, "description": description}
        for status, description in {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            409: "Conflict",
            413: "Content Too Large",
            422: "Unprocessable Content",
            429: "Too Many Requests",
            500: "Internal Server Error",
            503: "Service Unavailable",
        }.items()
    },
    description=(
        "Score synthetic transactions using rules and a lightweight classifier. "
        "This demo does not process real payments. Service implementation is in progress."
    ),
)

app.add_middleware(GuardrailsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID", "Retry-After"],
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


class HealthResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    model_version: str | None = None


@app.get(
    "/health",
    tags=["operations"],
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
)
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


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": "Request is not supported"}},
        headers=exc.headers,
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "DATABASE_UNAVAILABLE",
                "message": "Database is temporarily unavailable",
            }
        },
        headers={"Retry-After": "5"},
    )
