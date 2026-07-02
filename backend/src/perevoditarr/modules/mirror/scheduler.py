"""Scheduled sync loops (P1-T5, FR-M2): incremental library + fast wanted."""

import asyncio

import structlog
from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances import InstanceGateway, InstancesService
from perevoditarr.modules.mirror.sync import MirrorSyncService

_logger = structlog.get_logger()


async def _sync_all(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    *,
    wanted_only: bool,
) -> None:
    async with alchemy.get_session() as session:
        instances = InstancesService(session, secret_box)
        sync = MirrorSyncService(session, instances, gateway, sse_bus)
        for instance in await instances.list_bazarr():
            if not instance.enabled:
                continue
            try:
                if wanted_only:
                    _ = await sync.sync_wanted(instance.id)
                else:
                    _ = await sync.sync_library(instance.id)
            except Exception as error:
                _logger.warning(
                    "scheduled sync failed",
                    instance=instance.name,
                    wanted_only=wanted_only,
                    error=str(error),
                )


async def library_sync_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    interval_seconds: int,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await _sync_all(alchemy, gateway, secret_box, sse_bus, wanted_only=False)


async def wanted_sync_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    interval_seconds: int,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await _sync_all(alchemy, gateway, secret_box, sse_bus, wanted_only=True)
