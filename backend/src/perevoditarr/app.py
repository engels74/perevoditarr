"""Litestar application factory.

Serves /api/v1, the OpenAPI schema at /schema, and — when a built SPA bundle is
present (container image) — the static SPA with an index.html fallback (ADR-0004).
"""

import os
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import msgspec
from litestar import Litestar, MediaType, Request, Response, Router, get
from litestar.datastructures import State
from litestar.exceptions import NotFoundException
from litestar.openapi import OpenAPIConfig
from litestar.response import File
from litestar.static_files import (
    create_static_files_router,  # pyright: ignore[reportUnknownVariableType]
)
from litestar.types import ExceptionHandlersMap
from litestar_granian import GranianPlugin

SPA_DIR_ENV = "PEREVODITARR_SPA_DIR"

type _FallbackResponse = Response[dict[str, int | str]] | File
type _FallbackHandler = Callable[
    [Request[object, object, State], NotFoundException], _FallbackResponse
]


class HealthStatus(msgspec.Struct, kw_only=True):
    status: str


class HelloMessage(msgspec.Struct, kw_only=True, rename="camel"):
    app_name: str
    message: str


@get("/health")
async def health() -> HealthStatus:
    return HealthStatus(status="ok")


@get("/hello")
async def hello() -> HelloMessage:
    return HelloMessage(
        app_name="Perevoditarr",
        message="Привет! The API and the SPA shell are talking.",
    )


api_v1 = Router(path="/api/v1", route_handlers=[health, hello])


def _spa_dir() -> Path | None:
    raw = os.environ.get(SPA_DIR_ENV)
    if raw is None:
        return None
    spa_dir = Path(raw)
    return spa_dir if (spa_dir / "index.html").is_file() else None


def _spa_fallback(index: Path) -> _FallbackHandler:
    # Unknown non-API paths get the SPA shell (client-side routing); API/schema
    # paths keep their JSON 404.
    def handle(
        request: Request[object, object, State], _: NotFoundException
    ) -> _FallbackResponse:
        if request.url.path.startswith(("/api/", "/schema")):
            return Response(
                {"status_code": 404, "detail": "Not Found"},
                status_code=404,
                media_type=MediaType.JSON,
            )
        return File(index, media_type=MediaType.HTML, content_disposition_type="inline")

    return handle


def create_app() -> Litestar:
    route_handlers: list[Router] = [api_v1]
    exception_handlers: ExceptionHandlersMap = {}  # pyright: ignore[reportUnknownVariableType]
    if (spa_dir := _spa_dir()) is not None:
        route_handlers.append(
            create_static_files_router(path="/", directories=[spa_dir], html_mode=True)
        )
        exception_handlers[NotFoundException] = _spa_fallback(spa_dir / "index.html")
    return Litestar(
        route_handlers=route_handlers,
        plugins=[GranianPlugin()],
        openapi_config=OpenAPIConfig(
            title="Perevoditarr API",
            version=version("perevoditarr"),
            path="/schema",
        ),
        exception_handlers=exception_handlers,
    )


app = create_app()
