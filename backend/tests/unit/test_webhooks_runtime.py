"""Webhook trigger coalescing (P5-T3): bursts collapse to one background run."""

import asyncio
from uuid import UUID, uuid4

from perevoditarr.modules.webhooks.runtime import WebhookRuntime


async def test_coalesces_repeat_within_window() -> None:
    fired: list[UUID] = []

    async def trigger(instance_id: UUID) -> None:
        fired.append(instance_id)

    runtime = WebhookRuntime(trigger, coalesce_seconds=100.0)
    instance = uuid4()
    other = uuid4()

    assert runtime.schedule(instance) is True
    assert runtime.schedule(instance) is False  # coalesced into the first
    assert runtime.schedule(other) is True  # a different instance is independent

    # Let the scheduled background tasks run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert fired.count(instance) == 1
    assert fired.count(other) == 1


async def test_missing_trigger_is_safe() -> None:
    runtime = WebhookRuntime()  # no trigger wired yet
    assert runtime.schedule(uuid4()) is True
    await asyncio.sleep(0)  # _run returns immediately without a trigger
