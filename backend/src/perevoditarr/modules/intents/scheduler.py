"""Discovery triggers (P2-T3, FR-P1): scheduled loop + on-demand runner.

The wanted-sync completion trigger is wired in app assembly: the mirror
module exposes an `on_wanted_sync_complete` callback seam (it never imports
intents), and `run_discovery` is what the app plugs into it.
"""

import asyncio
from uuid import UUID

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

from perevoditarr.core.locks import InstanceLockRegistry
from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances import InstanceGateway, InstancesService
from perevoditarr.modules.intents.discovery import DiscoveryService

_logger = get_logger()


async def run_discovery(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    *,
    instance_id: UUID | None = None,
    locks: InstanceLockRegistry | None = None,
) -> None:
    """Run discovery for one instance (sync-completion trigger) or all
    enabled instances (scheduled loop); per-instance failures never cascade.

    The app passes its shared lock registry so a periodic pass and a
    sync-completion nudge for the same instance never interleave; direct
    callers (tests) may omit it."""
    registry = locks if locks is not None else InstanceLockRegistry()
    async with alchemy.get_session() as session:
        instances = InstancesService(session, secret_box)
        discovery = DiscoveryService(session, secret_box, gateway, sse_bus)
        # Plain-data snapshot: a mid-pass rollback expires every ORM row
        # loaded so far, so neither the loop nor the log handler may touch
        # attributes of rows fetched before the failure.
        targets = [
            (row.id, row.name)
            for row in await instances.list_bazarr()
            if row.enabled and (instance_id is None or row.id == instance_id)
        ]
        for target_id, target_name in targets:
            try:
                async with registry.lock_for(target_id):
                    _ = await discovery.run_for_instance(target_id)
            except Exception as error:
                # Roll back so a DB-level failure on this instance cannot
                # poison the session for the remaining instances in the pass.
                await session.rollback()
                _logger.warning(
                    "discovery run failed", instance=target_name, error=str(error)
                )


async def discovery_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    interval_seconds: int,
    locks: InstanceLockRegistry | None = None,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await run_discovery(alchemy, gateway, secret_box, sse_bus, locks=locks)
