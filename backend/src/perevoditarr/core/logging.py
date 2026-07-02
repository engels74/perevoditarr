"""structlog wiring: JSON renderer in prod, console in dev, request-id binding."""

from typing import cast
from uuid import uuid4

import structlog
from litestar.enums import ScopeType
from litestar.logging.config import (
    StructLoggingConfig,
    default_logger_factory,
    default_structlog_processors,
)
from litestar.plugins.structlog import StructlogConfig, StructlogPlugin
from litestar.types import ASGIApp, Message, Receive, Scope, Send
from structlog.typing import FilteringBoundLogger

from perevoditarr.core.settings import AppSettings

REQUEST_ID_HEADER = b"x-request-id"


def get_logger() -> FilteringBoundLogger:
    """Typed accessor for the app's structlog logger — use this, not structlog's.

    ``structlog.get_logger()`` returns ``Any`` (a lazy proxy bound at first
    use). Under this app's configuration the bound wrapper is structlog's
    default ``FilteringBoundLogger`` (litestar's ``StructLoggingConfig`` leaves
    ``wrapper_class`` unset), so this helper is the one sanctioned cast for
    that untyped boundary.
    """
    return cast("FilteringBoundLogger", structlog.get_logger())


def build_structlog_plugin(settings: AppSettings) -> StructlogPlugin:
    # prod: force JSON regardless of TTY; dev: console rendering.
    as_json = settings.env == "prod"
    logging_config = StructLoggingConfig(
        processors=default_structlog_processors(as_json=as_json),
        logger_factory=default_logger_factory(as_json=as_json),
        pretty_print_tty=not as_json,
    )
    return StructlogPlugin(
        config=StructlogConfig(structlog_logging_config=logging_config)
    )


def request_id_middleware(app: ASGIApp) -> ASGIApp:
    """Bind a per-request correlation id into structlog contextvars (P1-T1).

    Honors an inbound X-Request-ID (trusted reverse-proxy setups) and always
    echoes the id back on the response.
    """

    async def middleware(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != ScopeType.HTTP:
            await app(scope, receive, send)
            return
        inbound = dict(scope["headers"]).get(REQUEST_ID_HEADER, b"")
        request_id = inbound.decode("latin-1") or uuid4().hex
        structlog.contextvars.clear_contextvars()
        _ = structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await app(scope, receive, send_with_header)

    return middleware
