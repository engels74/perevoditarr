"""Litestar application factory.

Serves /api/v1, the OpenAPI schema at /schema (Scalar UI), the SSE event
stream, and — when a built SPA bundle is present (container image) — the
static SPA with an index.html fallback (ADR-0004).
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from importlib.metadata import version
from pathlib import Path

import msgspec
import structlog
from litestar import Litestar, MediaType, Request, Response, Router, get
from litestar.config.app import AppConfig
from litestar.config.csrf import CSRFConfig
from litestar.datastructures import State
from litestar.di import Provide
from litestar.exceptions import NotFoundException
from litestar.middleware import DefineMiddleware
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.response import File
from litestar.static_files import (
    create_static_files_router,  # pyright: ignore[reportUnknownVariableType]
)
from litestar.types import ExceptionHandlersMap
from litestar_granian import GranianPlugin

from perevoditarr.core.db import build_alchemy_config, build_sqlalchemy_plugin
from perevoditarr.core.errors import PerevoditarrError, domain_exception_handler
from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.core.logging import build_structlog_plugin, request_id_middleware
from perevoditarr.core.security import SecretBox, derive_key, resolve_secret_key
from perevoditarr.core.settings import AppSettings, load_settings
from perevoditarr.core.sse import SseBus, sse_events
from perevoditarr.modules.auth import (
    ApiKeyAwareCSRFMiddleware,
    AuthController,
    AuthRuntime,
    SessionAuthenticator,
    SetupController,
    build_jwt_auth,
    provide_auth_service,
    provide_provider_service,
    setup_gate_middleware,
)
from perevoditarr.modules.doctor import (
    DoctorController,
    DoctorService,
    provide_doctor_service,
)
from perevoditarr.modules.instances import (
    InstanceGateway,
    InstancesController,
    health_monitor_loop,
    provide_gateway,
    provide_instances_service,
)
from perevoditarr.modules.mirror import (
    MirrorController,
    library_sync_loop,
    provide_mirror_service,
    provide_mirror_sync_service,
    wanted_sync_loop,
)

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


@get("/health", exclude_from_auth=True)
async def health() -> HealthStatus:
    return HealthStatus(status="ok")


@get("/hello", exclude_from_auth=True)
async def hello() -> HelloMessage:
    return HelloMessage(
        app_name="Perevoditarr",
        message="Привет! The API and the SPA shell are talking.",
    )


class SystemAbout(msgspec.Struct, kw_only=True, rename="camel"):
    app_version: str
    environment: str
    database_dialect: str


@get("/system/about", operation_id="getSystemAbout")
async def system_about(app_settings: AppSettings) -> SystemAbout:
    return SystemAbout(
        app_version=version("perevoditarr"),
        environment=app_settings.env,
        database_dialect=app_settings.database_url.partition("://")[0],
    )


def _spa_dir(settings: AppSettings) -> Path | None:
    if settings.spa_dir is None:
        return None
    spa_dir = Path(settings.spa_dir)
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


@asynccontextmanager
async def _http_lifespan(app: Litestar) -> AsyncGenerator[None]:
    registry = HttpClientRegistry()
    app.state.http = registry
    try:
        yield
    finally:
        await registry.aclose()


def _singleton[T](value: T) -> Callable[[], T]:
    def provide() -> T:
        return value

    return provide


def _register_setup_gate(app_config: AppConfig) -> AppConfig:
    app_config.middleware.insert(0, setup_gate_middleware)
    return app_config


def provide_http(state: State) -> HttpClientRegistry:
    registry: object = state.get("http")
    if not isinstance(registry, HttpClientRegistry):
        raise RuntimeError("HTTP client registry is not initialized")
    return registry


def create_app(settings: AppSettings | None = None) -> Litestar:
    resolved = settings if settings is not None else load_settings()
    sse_bus = SseBus()
    secret_box = SecretBox(resolve_secret_key(resolved))
    alchemy_config = build_alchemy_config(resolved)
    auth_runtime = AuthRuntime(
        settings=resolved, secret_box=secret_box, alchemy_config=alchemy_config
    )
    jwt_auth = build_jwt_auth(resolved)
    csrf_config = CSRFConfig(
        secret=derive_key(resolve_secret_key(resolved), b"perevoditarr.csrf").hex(),
        cookie_name="csrftoken",
        header_name="x-csrftoken",
        cookie_httponly=False,  # the SPA reads it to echo the header
        exclude=[
            "^/api/v1/setup",
            "^/api/v1/auth/login$",
            "^/api/v1/auth/oidc",
            "^/schema",
        ],
    )

    @asynccontextmanager
    async def _background_loops_lifespan(app: Litestar) -> AsyncGenerator[None]:
        tasks: list[asyncio.Task[None]] = []
        gateway = provide_gateway(app.state)
        if resolved.health_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    health_monitor_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        sse_bus,
                        resolved.health_interval_seconds,
                    )
                )
            )
        if resolved.sync_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    library_sync_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        sse_bus,
                        resolved.sync_interval_seconds,
                    )
                )
            )
        if resolved.wanted_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    wanted_sync_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        sse_bus,
                        resolved.wanted_interval_seconds,
                    )
                )
            )
        if resolved.doctor_interval_seconds > 0:
            tasks.append(asyncio.create_task(_doctor_schedule_loop(gateway)))
        try:
            yield
        finally:
            for task in tasks:
                _ = task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

    async def _doctor_schedule_loop(gateway: InstanceGateway) -> None:
        while True:
            await asyncio.sleep(resolved.doctor_interval_seconds)
            try:
                async with alchemy_config.get_session() as session:
                    forward = auth_runtime.forward_auth
                    service = DoctorService(
                        session,
                        secret_box,
                        gateway,
                        sse_bus,
                        forward_auth_misconfigured=(
                            forward is not None
                            and forward.enabled
                            and not auth_runtime.trusted_networks
                        ),
                    )
                    _ = await service.run("scheduled")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                structlog.get_logger().warning(
                    "scheduled doctor run failed", error=str(error)
                )

    async def _load_auth_providers() -> None:
        try:
            await auth_runtime.refresh_providers()
        except Exception as error:
            structlog.get_logger().warning(
                "auth provider configs unavailable at startup", error=str(error)
            )

    api_v1 = Router(
        path="/api/v1",
        route_handlers=[
            health,
            hello,
            system_about,
            sse_events,
            SetupController,
            AuthController,
            InstancesController,
            MirrorController,
            DoctorController,
        ],
    )
    route_handlers: list[Router] = [api_v1]
    exception_handlers: ExceptionHandlersMap = {  # pyright: ignore[reportUnknownVariableType]
        PerevoditarrError: domain_exception_handler,
    }
    if (spa_dir := _spa_dir(resolved)) is not None:
        route_handlers.append(
            create_static_files_router(
                path="/",
                directories=[spa_dir],
                html_mode=True,
                opt={"exclude_from_auth": True, "exclude_from_csrf": True},
            )
        )
        exception_handlers[NotFoundException] = _spa_fallback(spa_dir / "index.html")

    return Litestar(
        route_handlers=route_handlers,
        plugins=[
            GranianPlugin(),
            build_sqlalchemy_plugin(alchemy_config),
            build_structlog_plugin(resolved),
        ],
        lifespan=[_http_lifespan, _background_loops_lifespan],
        # Ordering matters: the JWT middleware self-inserts at position 0
        # during its on_app_init, so the setup gate registers afterwards and
        # re-claims position 0 to run outermost (403 setup-required beats 401).
        on_app_init=[jwt_auth.on_app_init, _register_setup_gate],
        on_startup=[_load_auth_providers],
        middleware=[
            request_id_middleware,
            DefineMiddleware(ApiKeyAwareCSRFMiddleware, config=csrf_config),
        ],
        dependencies={
            "sse_bus": Provide(_singleton(sse_bus), sync_to_thread=False),
            "app_settings": Provide(_singleton(resolved), sync_to_thread=False),
            "auth_runtime": Provide(_singleton(auth_runtime), sync_to_thread=False),
            "session_auth": Provide(
                _singleton(SessionAuthenticator(jwt_auth)), sync_to_thread=False
            ),
            "http": Provide(provide_http, sync_to_thread=False),
            "auth_service": Provide(provide_auth_service),
            "provider_service": Provide(provide_provider_service),
            "gateway": Provide(provide_gateway, sync_to_thread=False),
            "instances_service": Provide(provide_instances_service),
            "mirror_service": Provide(provide_mirror_service),
            "mirror_sync_service": Provide(provide_mirror_sync_service),
            "doctor_service": Provide(provide_doctor_service),
        },
        openapi_config=OpenAPIConfig(
            title="Perevoditarr API",
            version=version("perevoditarr"),
            path="/schema",
            render_plugins=[ScalarRenderPlugin()],
        ),
        exception_handlers=exception_handlers,
        state=State(
            {"sse_bus": sse_bus, "settings": resolved, "auth_runtime": auth_runtime}
        ),
    )


app = create_app()
