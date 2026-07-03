"""Webhook trigger runtime (P5-T3): coalesced, fire-and-forget dispatch.

The ingestion endpoint must ack fast (Bazarr/Sonarr notifiers time out), so the
actual wanted-sync + discovery runs as a background task. A per-instance
coalescing window collapses bursts (a season import fires many notifications)
into one pass — and because that pass reuses the *idempotent* discovery
pipeline, webhook-sourced discovery can never duplicate polling-sourced intents
(FR-X4)."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from perevoditarr.core.logging import get_logger

_logger = get_logger()

type WebhookTrigger = Callable[[UUID], Awaitable[None]]


class WebhookRuntime:
    def __init__(
        self, trigger: WebhookTrigger | None = None, *, coalesce_seconds: float = 5.0
    ) -> None:
        self._trigger: WebhookTrigger | None = trigger
        self._coalesce: float = coalesce_seconds
        self._last: dict[UUID, float] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def set_trigger(self, trigger: WebhookTrigger) -> None:
        """Wire the real sync trigger once the gateway exists (app lifespan)."""
        self._trigger = trigger

    def schedule(self, instance_id: UUID) -> bool:
        """Queue a background trigger for the instance; returns False when the
        call was coalesced into a recent one."""
        now = time.monotonic()
        last = self._last.get(instance_id)
        if last is not None and now - last < self._coalesce:
            return False
        self._last[instance_id] = now
        task = asyncio.create_task(self._run(instance_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _run(self, instance_id: UUID) -> None:
        if self._trigger is None:
            return
        try:
            await self._trigger(instance_id)
        except Exception as error:
            _logger.warning("webhook-triggered sync failed", error=str(error))
