"""Optional same-origin demo packaging; the standalone API stays independent."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles


def create_app() -> Starlette:
    from fraud_api.main import app as api

    directory = Path(os.environ.get("FRAUD_DEMO_DIRECTORY", "/app/demo"))
    if not (directory / "index.html").is_file():
        raise RuntimeError("Built demo is missing; build the root deployment Dockerfile")

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with api.router.lifespan_context(api):
            yield

    return Starlette(
        lifespan=lifespan,
        routes=[
            Mount("/api", app=api),
            Mount("/", app=StaticFiles(directory=directory, html=True)),
        ],
    )
