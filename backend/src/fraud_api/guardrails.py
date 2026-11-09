"""Bounded single-process admission, trusted proxies, and safe request logging."""

import hashlib
import json
import logging
import math
from collections import OrderedDict
from http.cookies import CookieError, SimpleCookie
from ipaddress import ip_address, ip_network
from threading import Lock
from time import monotonic, perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fraud_api.config import get_settings

logger = logging.getLogger("fraud_api.requests")


class WindowLimiter:
    def __init__(self) -> None:
        self.entries: OrderedDict[str, tuple[int, int]] = OrderedDict()
        self.lock = Lock()

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()

    def admit(self, budgets: list[tuple[str, int]], maximum: int, now: float) -> int:
        epoch = int(now // 60)
        retry = max(1, math.ceil((epoch + 1) * 60 - now))
        with self.lock:
            while self.entries and next(iter(self.entries.values()))[0] < epoch:
                self.entries.popitem(last=False)
            if len(self.entries) + sum(key not in self.entries for key, _ in budgets) > maximum:
                return retry
            if any(self.entries.get(key, (epoch, 0))[1] >= cap for key, cap in budgets):
                return retry
            for key, _ in budgets:
                self.entries[key] = (epoch, self.entries.get(key, (epoch, 0))[1] + 1)
            return 0


limiter = WindowLimiter()


def client_ip(peer: str, forwarded: str | None, trusted: list[str]) -> str:
    try:
        address = ip_address(peer)
        networks = [ip_network(value) for value in trusted]
        if (
            not any(address in network for network in networks)
            or not forwarded
            or len(forwarded) > 1024
        ):
            return str(address)
        chain = [ip_address(value.strip()) for value in forwarded.split(",")]
        for hop in reversed(chain):
            if not any(address in network for network in networks):
                break
            address = hop
        return str(address)
    except ValueError:
        return peer


def token_identity(headers: Headers) -> str | None:
    parts = headers.get("authorization", "").split()
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None
    if token is None:
        raw = headers.get("cookie", "")
        if len(raw) <= 8192:
            cookies: SimpleCookie = SimpleCookie()
            try:
                cookies.load(raw)
                item = cookies.get("fraud_session")
                token = item.value if item else None
            except CookieError:
                pass
    if token and len(token) <= 256:
        return hashlib.sha256(token.encode()).hexdigest()
    return None


async def reject(send: Send, status: int, code: str, message: str, retry: int = 0) -> None:
    headers = [(b"content-type", b"application/json")]
    if retry:
        headers.append((b"retry-after", str(retry).encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send(
        {
            "type": "http.response.body",
            "body": json.dumps(
                {
                    "error": {"code": code, "message": message},
                }
            ).encode(),
        }
    )


class GuardrailsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        started = perf_counter()
        status = 500
        response_started = False

        async def safe_send(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        try:
            if scope["path"].startswith("/v1/") and scope["method"] != "OPTIONS":
                settings = get_settings()
                headers = Headers(scope=scope)
                peer = scope.get("client")
                identity = client_ip(
                    peer[0] if peer else "unknown",
                    headers.get("x-forwarded-for"),
                    settings.trusted_proxy_cidrs,
                )
                ip_hash = hashlib.sha256(identity.encode()).hexdigest()
                budgets = [(f"ip:{ip_hash}", settings.requests_per_minute_ip)]
                if scope["path"] == "/v1/sessions":
                    budgets.append((f"session:{ip_hash}", settings.sessions_per_minute_ip))
                token = token_identity(headers)
                if token:
                    budgets.append((f"token:{token}", settings.requests_per_minute_token))
                retry = limiter.admit(budgets, settings.rate_limit_max_keys, monotonic())
                if retry:
                    await reject(
                        safe_send, 429, "RATE_LIMITED", "Request limit reached; retry later", retry
                    )
                    return
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > settings.max_request_bytes:
                        await reject(
                            safe_send, 413, "REQUEST_TOO_LARGE", "Request body exceeds demo limit"
                        )
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
                consumed = False

                async def replay() -> Message:
                    nonlocal consumed
                    if consumed:
                        return await receive()
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}

                await self.app(scope, replay, safe_send)
            else:
                await self.app(scope, receive, safe_send)
        except Exception:
            if response_started:
                raise
            await reject(safe_send, 500, "INTERNAL_ERROR", "Request could not be completed")
        finally:
            route = scope.get("route")
            method = (
                scope["method"]
                if scope["method"] in {"GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS"}
                else "OTHER"
            )
            logger.info(
                json.dumps(
                    {
                        "event": "request_complete",
                        "request_id": request_id,
                        "method": method,
                        "route": getattr(route, "path", "unmatched"),
                        "status": status,
                        "duration_ms": round((perf_counter() - started) * 1000, 2),
                    }
                )
            )
