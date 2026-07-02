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
from uuid import UUID

import msgspec
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
from litestar.types import ControllerRouterHandler, ExceptionHandlersMap
from litestar_granian import GranianPlugin

from perevoditarr.core.db import build_alchemy_config, build_sqlalchemy_plugin
from perevoditarr.core.errors import PerevoditarrError, domain_exception_handler
from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.core.locks import InstanceLockRegistry
from perevoditarr.core.logging import (
    build_structlog_plugin,
    get_logger,
    request_id_middleware,
)
from perevoditarr.core.metrics import metrics_endpoint
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
from perevoditarr.modules.dispatch import (
    DispatchController,
    provide_plan_preview_service,
)
from perevoditarr.modules.dispatch.scheduler import (
    dispatch_loop,
    run_dispatch,
    run_verification,
    verify_loop,
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
from perevoditarr.modules.intents import (
    IntentsController,
    QuarantineController,
    discovery_loop,
    provide_discovery_service,
    provide_intents_service,
    provide_passthrough_service,
    provide_quarantine_service,
    provide_timeline_service,
    reconcile_loop,
    run_discovery,
    run_reconciliation,
)
from perevoditarr.modules.mirror import (
    MirrorController,
    WantedSyncCompleted,
    library_sync_loop,
    provide_mirror_service,
    provide_mirror_sync_service,
    wanted_sync_loop,
)
from perevoditarr.modules.notifications import (
    NotificationCoalescer,
    NotificationMessage,
    NotificationsController,
    NotificationsService,
    provide_notifications_service,
)
from perevoditarr.modules.policy import PolicyController, provide_policy_service
from perevoditarr.modules.rails import RailsController, provide_rails_service
from perevoditarr.modules.stats import (
    StatsController,
    budget_reconcile_loop,
    provide_stats_service,
    run_budget_reconciliation,
    run_stats_rollup,
    stats_rollup_loop,
)
from perevoditarr.modules.telemetry import (
    TelemetryBridge,
    TelemetryController,
    TelemetryHealthRegistry,
    provide_telemetry_health_service,
    telemetry_loop,
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

    # One shared registry: the periodic loops and the wanted-sync hook must
    # never run discovery/reconciliation for the same instance concurrently
    # (the ledger upsert is SELECT-then-INSERT; interleaved passes race it).
    instance_locks = InstanceLockRegistry()
    # Process-singleton notification coalescer shared by the controller DI and
    # the background forwarders (P3-T5): per-(route, event) spam suppression.
    notification_coalescer = NotificationCoalescer()
    # Telemetry (P3-T4): process-singleton stream-health registry; the SSE
    # bridge + re-observation nudge are built inside the lifespan (they need the
    # resolved gateway).
    telemetry_health = TelemetryHealthRegistry()

    def _make_telemetry_bridge(gateway: InstanceGateway) -> TelemetryBridge:
        async def nudge(instance_id: UUID) -> None:
            # A telemetry resource change triggers immediate re-observation of
            # durable evidence — a nudge only, never a transition (§7.3).
            await run_reconciliation(
                alchemy_config,
                gateway,
                secret_box,
                sse_bus,
                instance_id=instance_id,
                locks=instance_locks,
            )
            await run_verification(
                alchemy_config,
                gateway,
                secret_box,
                sse_bus,
                max_attempts=resolved.dispatch_max_attempts,
                retry_base_seconds=resolved.dispatch_retry_base_seconds,
                retry_cap_seconds=resolved.dispatch_retry_cap_seconds,
                instance_id=instance_id,
                locks=instance_locks,
                notification_coalescer=notification_coalescer,
            )

        return TelemetryBridge(sse_bus, nudge)

    def _make_wanted_sync_hook(gateway: InstanceGateway) -> WantedSyncCompleted:
        # Wanted-sync completion ⇒ discovery, then reconciliation, for that
        # instance (P2-T3/P2-T4: the event nudge). Wired here so the mirror
        # module never imports intents; this is an explicit in-process seam,
        # not the SSE bus (§7.3: SSE is UI-only).
        async def hook(instance_id: UUID) -> None:
            await run_discovery(
                alchemy_config,
                gateway,
                secret_box,
                sse_bus,
                instance_id=instance_id,
                locks=instance_locks,
            )
            await run_reconciliation(
                alchemy_config,
                gateway,
                secret_box,
                sse_bus,
                instance_id=instance_id,
                locks=instance_locks,
            )
            # Verify first (frees slots by converging/failing in-flight intents),
            # then top-up (P3-T2/T3): newly-eligible intents get a dispatch pass
            # immediately, not only on the periodic loops.
            await run_verification(
                alchemy_config,
                gateway,
                secret_box,
                sse_bus,
                max_attempts=resolved.dispatch_max_attempts,
                retry_base_seconds=resolved.dispatch_retry_base_seconds,
                retry_cap_seconds=resolved.dispatch_retry_cap_seconds,
                instance_id=instance_id,
                locks=instance_locks,
                notification_coalescer=notification_coalescer,
            )
            await run_dispatch(
                alchemy_config,
                gateway,
                secret_box,
                sse_bus,
                lease_seconds=resolved.dispatch_lease_seconds,
                backpressure_pending=resolved.dispatch_backpressure_pending,
                instance_id=instance_id,
                locks=instance_locks,
                notification_coalescer=notification_coalescer,
            )

        return hook

    def provide_wanted_sync_hook(state: State) -> WantedSyncCompleted:
        return _make_wanted_sync_hook(provide_gateway(state))

    @asynccontextmanager
    async def _background_loops_lifespan(app: Litestar) -> AsyncGenerator[None]:
        tasks: list[asyncio.Task[None]] = []
        gateway = provide_gateway(app.state)
        # Startup re-observation (FR-R4): one full reconciliation pass before
        # the periodic loops take over — crash safety is re-observation, never
        # volatile state. Unreachable instances log and skip inside; anything
        # else must still never block boot.
        try:
            await run_reconciliation(
                alchemy_config,
                gateway,
                secret_box,
                sse_bus,
                actor="startup",
                locks=instance_locks,
            )
        except Exception as error:
            get_logger().warning("startup re-observation failed", error=str(error))
        # Startup re-verification (FR-R4): dispatched intents that converged or
        # failed while we were down are retroactively resolved from durable
        # evidence before any new dispatch — crash safety is re-observation.
        try:
            await run_verification(
                alchemy_config,
                gateway,
                secret_box,
                sse_bus,
                max_attempts=resolved.dispatch_max_attempts,
                retry_base_seconds=resolved.dispatch_retry_base_seconds,
                retry_cap_seconds=resolved.dispatch_retry_cap_seconds,
                locks=instance_locks,
                notification_coalescer=notification_coalescer,
            )
        except Exception as error:
            get_logger().warning("startup re-verification failed", error=str(error))
        # Startup budget reconciliation + stats rollup (P4-T1): refresh the
        # actuals snapshot and re-derive the dashboard counters from durable
        # evidence before the periodic loops take over. Best-effort — a stale
        # Lingarr or empty ledger must never block boot.
        try:
            _ = await run_budget_reconciliation(alchemy_config, gateway, secret_box)
        except Exception as error:
            get_logger().warning(
                "startup budget reconciliation failed", error=str(error)
            )
        try:
            _ = await run_stats_rollup(alchemy_config)
        except Exception as error:
            get_logger().warning("startup stats rollup failed", error=str(error))
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
                        _make_wanted_sync_hook(gateway),
                    )
                )
            )
        if resolved.discovery_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    discovery_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        sse_bus,
                        resolved.discovery_interval_seconds,
                        locks=instance_locks,
                    )
                )
            )
        if resolved.reconcile_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    reconcile_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        sse_bus,
                        resolved.reconcile_interval_seconds,
                        locks=instance_locks,
                    )
                )
            )
        if resolved.dispatch_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    dispatch_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        sse_bus,
                        resolved.dispatch_interval_seconds,
                        lease_seconds=resolved.dispatch_lease_seconds,
                        backpressure_pending=resolved.dispatch_backpressure_pending,
                        locks=instance_locks,
                        notification_coalescer=notification_coalescer,
                    )
                )
            )
        if resolved.verify_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    verify_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        sse_bus,
                        resolved.verify_interval_seconds,
                        max_attempts=resolved.dispatch_max_attempts,
                        retry_base_seconds=resolved.dispatch_retry_base_seconds,
                        retry_cap_seconds=resolved.dispatch_retry_cap_seconds,
                        locks=instance_locks,
                        notification_coalescer=notification_coalescer,
                    )
                )
            )
        if resolved.digest_interval_seconds > 0:
            tasks.append(asyncio.create_task(_digest_loop()))
        if resolved.doctor_interval_seconds > 0:
            tasks.append(asyncio.create_task(_doctor_schedule_loop(gateway)))
        if resolved.telemetry_poll_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    telemetry_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        _make_telemetry_bridge(gateway),
                        telemetry_health,
                        resolved.telemetry_poll_interval_seconds,
                    )
                )
            )
        if resolved.stats_rollup_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    stats_rollup_loop(
                        alchemy_config,
                        resolved.stats_rollup_interval_seconds,
                    )
                )
            )
        if resolved.budget_reconcile_interval_seconds > 0:
            tasks.append(
                asyncio.create_task(
                    budget_reconcile_loop(
                        alchemy_config,
                        gateway,
                        secret_box,
                        resolved.budget_reconcile_interval_seconds,
                    )
                )
            )
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
                        telemetry_health=telemetry_health,
                    )
                    result = await service.run("scheduled")
                    critical = [
                        finding
                        for finding in result.findings
                        if finding.severity == "critical"
                    ]
                    if critical:
                        notifications = NotificationsService(
                            session, secret_box, notification_coalescer
                        )
                        _ = await notifications.notify(
                            NotificationMessage(
                                event="doctor_critical",
                                title="Doctor found critical issues",
                                body=(
                                    f"{len(critical)} critical finding(s): "
                                    + "; ".join(f.message for f in critical[:3])
                                ),
                            )
                        )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                get_logger().warning("scheduled doctor run failed", error=str(error))

    async def _digest_loop() -> None:
        while True:
            await asyncio.sleep(resolved.digest_interval_seconds)
            try:
                async with alchemy_config.get_session() as session:
                    service = NotificationsService(
                        session, secret_box, notification_coalescer
                    )
                    _ = await service.send_digest()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                get_logger().warning("notification digest failed", error=str(error))

    async def _load_auth_providers() -> None:
        try:
            await auth_runtime.refresh_providers()
        except Exception as error:
            get_logger().warning(
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
            PolicyController,
            IntentsController,
            DispatchController,
            RailsController,
            QuarantineController,
            NotificationsController,
            TelemetryController,
            StatsController,
        ],
    )
    route_handlers: list[ControllerRouterHandler] = [api_v1, metrics_endpoint]
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
        # No endpoint accepts uploads; the largest legitimate body is a
        # policy-export JSON. A global cap keeps oversized payloads from
        # being buffered and decoded (defense in depth on top of the
        # msgspec max_length constraints).
        request_max_body_size=10 * 1024 * 1024,
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
            "policy_service": Provide(provide_policy_service),
            "intents_service": Provide(provide_intents_service),
            "discovery_service": Provide(provide_discovery_service),
            "plan_preview_service": Provide(provide_plan_preview_service),
            "rails_service": Provide(provide_rails_service),
            "quarantine_service": Provide(provide_quarantine_service),
            "notification_coalescer": Provide(
                _singleton(notification_coalescer), sync_to_thread=False
            ),
            "notifications_service": Provide(provide_notifications_service),
            "telemetry_health": Provide(
                _singleton(telemetry_health), sync_to_thread=False
            ),
            "telemetry_health_service": Provide(provide_telemetry_health_service),
            "wanted_sync_hook": Provide(provide_wanted_sync_hook, sync_to_thread=False),
            "stats_service": Provide(provide_stats_service),
            "timeline_service": Provide(provide_timeline_service),
            "passthrough_service": Provide(provide_passthrough_service),
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
