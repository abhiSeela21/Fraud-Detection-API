import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from fraud_api.config import get_settings
from fraud_api.database import get_db
from fraud_api.errors import ApiError
from fraud_api.models import DemoSession

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])
COOKIE_NAME = "fraud_session"
bearer = HTTPBearer(auto_error=False)
Database = Annotated[Session, Depends(get_db)]


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["browser", "api"] = "browser"


class SessionResponse(BaseModel):
    expires_at: datetime
    token: str | None = None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_origin(request: Request) -> None:
    if request.headers.get("origin") != get_settings().frontend_origin:
        raise ApiError(403, "ORIGIN_REJECTED", "Request origin is not allowed")


@router.post("", response_model=SessionResponse, response_model_exclude_none=True, status_code=201)
def create_session(
    body: SessionRequest, request: Request, response: Response, db: Database
) -> SessionResponse:
    settings = get_settings()
    if body.mode == "browser":
        check_origin(request)
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expiry = now + timedelta(hours=settings.session_ttl_hours)
    db.add(DemoSession(token_hash=hash_token(token), created_at=now, expires_at=expiry))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    if body.mode == "browser":
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=settings.session_ttl_hours * 3600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
    return SessionResponse(expires_at=expiry, token=token if body.mode == "api" else None)


def require_session(
    request: Request,
    db: Database,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> DemoSession:
    token = credentials.credentials if credentials else request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 256:
        raise ApiError(401, "SESSION_REQUIRED", "A valid demo session is required")
    if credentials is None and request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
    session = db.scalar(select(DemoSession).where(DemoSession.token_hash == hash_token(token)))
    if session is None or session.expires_at <= datetime.now(UTC):
        raise ApiError(401, "SESSION_EXPIRED", "Session is invalid or expired")
    return session
