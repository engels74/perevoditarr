"""Instance health checks + monitor loop (P1-T4, FR-I3).

Health snapshots are persisted (restart-safe) and pushed to the UI over the
SSE bus on topic `instances.health` — liveness only, never a state input.
"""

import asyncio
import time
from datetime import UTC, datetime

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

from perevoditarr.core.errors import PerevoditarrError
from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.instances.schemas import BazarrCapabilities, InstanceHealth
from perevoditarr.modules.instances.service import InstancesService
from perevoditarr.modules.integrations.bazarr import detect_capabilities

_logger = get_logger()


async def check_bazarr_health(
    gateway: InstanceGateway, url: str, api_key: str
) -> InstanceHealth:
    client = gateway.bazarr(url, api_key)
    started = time.monotonic()
    try:
        status = await client.system_status()
        pending = await client.jobs(status="pending")
    except PerevoditarrError as error:
        return InstanceHealth(
            status="unreachable",
            checked_at=datetime.now(UTC),
            detail=str(error),
        )
    return InstanceHealth(
        status="ok",
        latency_ms=(time.monotonic() - started) * 1000.0,
        checked_at=datetime.now(UTC),
        queue_depth=len(pending),
        version=status.bazarr_version,
    )


async def check_lingarr_health(
    gateway: InstanceGateway, url: str, api_key: str | None
) -> InstanceHealth:
    client = gateway.lingarr(url, api_key)
    started = time.monotonic()
    try:
        info = await client.version()
    except PerevoditarrError as error:
        return InstanceHealth(
            status="unreachable",
            checked_at=datetime.now(UTC),
            detail=str(error),
        )
    return InstanceHealth(
        status="ok",
        latency_ms=(time.monotonic() - started) * 1000.0,
        checked_at=datetime.now(UTC),
        version=info.current_version,
    )


async def run_health_sweep(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
) -> int:
    """Check every enabled instance once; persist + publish. Returns count."""
    checked = 0
    async with alchemy.get_session() as session:
        service = InstancesService(session, secret_box)
        for bazarr in await service.list_bazarr():
            if not bazarr.enabled:
                continue
            health = await check_bazarr_health(
                gateway, bazarr.url, service.bazarr_api_key(bazarr)
            )
            # version drift surfaces on the dashboard via the snapshot delta;
            # a version change re-probes the capability slots (PRD §6.6)
            capabilities: BazarrCapabilities | None = None
            if health.version is not None and health.version != bazarr.version:
                probe = detect_capabilities(health.version)
                capabilities = BazarrCapabilities(
                    translate_returns_job_id=probe.translate_returns_job_id,
                    lingarr_receives_episode_id=probe.lingarr_receives_episode_id,
                    probed_at=datetime.now(UTC),
                )
            await service.store_bazarr_snapshot(
                bazarr.id,
                health=health,
                capabilities=capabilities,
                version=health.version,
            )
            sse_bus.publish(
                "instances.health",
                {"kind": "bazarr", "id": str(bazarr.id), "status": health.status},
            )
            checked += 1
        for lingarr in await service.list_lingarr():
            if not lingarr.enabled:
                continue
            health = await check_lingarr_health(
                gateway, lingarr.url, service.lingarr_api_key(lingarr)
            )
            await service.store_lingarr_snapshot(
                lingarr.id, health=health, version=health.version
            )
            sse_bus.publish(
                "instances.health",
                {"kind": "lingarr", "id": str(lingarr.id), "status": health.status},
            )
            checked += 1
    return checked


async def health_monitor_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    interval_seconds: int,
) -> None:
    while True:
        try:
            _ = await run_health_sweep(alchemy, gateway, secret_box, sse_bus)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            _logger.warning("instance health sweep failed", error=str(error))
        await asyncio.sleep(interval_seconds)
