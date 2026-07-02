"""Dispatch triggers (P3-T2): the top-up loop + on-demand runner.

The loop reacts to slot frees (an intent converged/failed) and rail unblocks by
re-running the bounded-window pass; per-instance passes are serialized by the
shared lock registry so the §6.5 admission check and the `dispatched`
transition never interleave with discovery/reconciliation for that instance
(ADR-0006). Per-instance failures never cascade — the next pass re-observes.
"""

import asyncio
from uuid import UUID

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

from perevoditarr.core.locks import InstanceLockRegistry
from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.dispatch.dispatcher import DispatcherService
from perevoditarr.modules.dispatch.verification import (
    VerificationService,
    VerifyRunSummary,
)
from perevoditarr.modules.instances import InstanceGateway, InstancesService
from perevoditarr.modules.notifications import (
    NotificationCoalescer,
    NotificationMessage,
    NotificationsService,
)

_logger = get_logger()


async def _forward_verification_notifications(
    notifications: NotificationsService, summary: VerifyRunSummary, instance_name: str
) -> None:
    for transition in summary.breaker_transitions:
        if transition.tripped:
            _ = await notifications.notify(
                NotificationMessage(
                    event="breaker_tripped",
                    title=f"Circuit breaker tripped: {instance_name}",
                    body=(
                        f"Dispatch to {instance_name} is paused after "
                        f"{transition.consecutive_failures} consecutive provider "
                        "failures. It will probe for recovery shortly."
                    ),
                )
            )
        elif transition.closed:
            _ = await notifications.notify(
                NotificationMessage(
                    event="breaker_closed",
                    title=f"Circuit breaker recovered: {instance_name}",
                    body=f"Dispatch to {instance_name} has resumed.",
                )
            )
    if summary.quarantined > 0:
        _ = await notifications.notify(
            NotificationMessage(
                event="quarantine_added",
                title=f"Intents quarantined: {instance_name}",
                body=(
                    f"{summary.quarantined} intent(s) on {instance_name} were "
                    "quarantined after repeated failure and need attention."
                ),
            )
        )


async def run_dispatch(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    *,
    lease_seconds: int,
    backpressure_pending: int,
    instance_id: UUID | None = None,
    locks: InstanceLockRegistry | None = None,
    notification_coalescer: NotificationCoalescer | None = None,
) -> None:
    """One bounded dispatch pass for one instance (event nudge) or all enabled
    instances (top-up loop). A pass halted by a volume cap forwards a coalesced
    cap-reached notification when a coalescer is supplied (P3-T5)."""
    registry = locks if locks is not None else InstanceLockRegistry()
    async with alchemy.get_session() as session:
        instances = InstancesService(session, secret_box)
        dispatcher = DispatcherService(
            session,
            secret_box,
            gateway,
            sse_bus,
            lease_seconds=lease_seconds,
            backpressure_pending=backpressure_pending,
        )
        notifications = (
            NotificationsService(session, secret_box, notification_coalescer)
            if notification_coalescer is not None
            else None
        )
        targets = [
            (row.id, row.name)
            for row in await instances.list_bazarr()
            if row.enabled and (instance_id is None or row.id == instance_id)
        ]
        for target_id, target_name in targets:
            try:
                async with registry.lock_for(target_id):
                    instance = await instances.get_bazarr(target_id)
                    summary = await dispatcher.run_for_instance(instance)
                if (
                    notifications is not None
                    and summary.rail_block is not None
                    and summary.rail_block.startswith("cap")
                ):
                    _ = await notifications.notify(
                        NotificationMessage(
                            event="cap_reached",
                            title=f"Volume cap reached: {target_name}",
                            body=(
                                f"Dispatch to {target_name} is holding: "
                                f"{summary.rail_block.removeprefix('cap_')} "
                                "volume cap reached."
                            ),
                        )
                    )
            except Exception as error:
                await session.rollback()
                _logger.warning(
                    "dispatch run failed", instance=target_name, error=str(error)
                )


async def dispatch_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    interval_seconds: int,
    *,
    lease_seconds: int,
    backpressure_pending: int,
    locks: InstanceLockRegistry | None = None,
    notification_coalescer: NotificationCoalescer | None = None,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await run_dispatch(
            alchemy,
            gateway,
            secret_box,
            sse_bus,
            lease_seconds=lease_seconds,
            backpressure_pending=backpressure_pending,
            locks=locks,
            notification_coalescer=notification_coalescer,
        )


async def run_verification(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    *,
    max_attempts: int,
    retry_base_seconds: int,
    retry_cap_seconds: int,
    instance_id: UUID | None = None,
    locks: InstanceLockRegistry | None = None,
    notification_coalescer: NotificationCoalescer | None = None,
) -> None:
    """Verify dispatched intents (convergence/failure/retry) for one instance or
    all enabled instances. Shares the lock registry with dispatch/discovery so a
    convergence never races a re-dispatch of the same intent (FR-R4). Breaker/
    quarantine outcomes are forwarded to notifications when a coalescer is
    supplied (P3-T5)."""
    registry = locks if locks is not None else InstanceLockRegistry()
    async with alchemy.get_session() as session:
        instances = InstancesService(session, secret_box)
        verification = VerificationService(
            session,
            secret_box,
            gateway,
            sse_bus,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_cap_seconds=retry_cap_seconds,
        )
        notifications = (
            NotificationsService(session, secret_box, notification_coalescer)
            if notification_coalescer is not None
            else None
        )
        targets = [
            (row.id, row.name)
            for row in await instances.list_bazarr()
            if row.enabled and (instance_id is None or row.id == instance_id)
        ]
        for target_id, target_name in targets:
            try:
                async with registry.lock_for(target_id):
                    instance = await instances.get_bazarr(target_id)
                    summary = await verification.run_for_instance(instance)
                if notifications is not None:
                    await _forward_verification_notifications(
                        notifications, summary, target_name
                    )
            except Exception as error:
                await session.rollback()
                _logger.warning(
                    "verification run failed", instance=target_name, error=str(error)
                )


async def verify_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    interval_seconds: int,
    *,
    max_attempts: int,
    retry_base_seconds: int,
    retry_cap_seconds: int,
    locks: InstanceLockRegistry | None = None,
    notification_coalescer: NotificationCoalescer | None = None,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await run_verification(
            alchemy,
            gateway,
            secret_box,
            sse_bus,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_cap_seconds=retry_cap_seconds,
            locks=locks,
            notification_coalescer=notification_coalescer,
        )
