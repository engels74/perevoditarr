"""Telemetry → UI bridge + reconciler nudge seam (P3-T4, §7.3).

Publishes telemetry events to the UI SSE plane under `telemetry.*`, and — for
resource-changed events — fires a *nudge* (event-triggered re-observation). The
nudge is the ONLY influence telemetry has on the correctness plane, and it is
strictly a nudge: it asks the reconciler/verifier to re-observe durable evidence
now instead of waiting for the next periodic pass. It never carries the
telemetry payload into a transition (§7.3). The nudge target is an injected
callback, so this module never imports intents/dispatch — the two-plane boundary
holds by construction.

Nudges are throttled per instance so an event storm cannot hammer the DB.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import msgspec

from perevoditarr.core.sse import SseBus
from perevoditarr.modules.telemetry.events import (
    JobProgress,
    RequestProgress,
    ResourceChanged,
    StreamHealth,
    TelemetryEvent,
)

type NudgeCallback = Callable[[UUID], Awaitable[None]]

_TOPICS: dict[type[TelemetryEvent], str] = {
    JobProgress: "telemetry.jobs",
    ResourceChanged: "telemetry.resource",
    RequestProgress: "telemetry.requests",
    StreamHealth: "telemetry.health",
}


def _payload(instance_id: UUID, event: TelemetryEvent) -> dict[str, object]:
    encoded = msgspec.json.decode(msgspec.json.encode(event), type=dict[str, object])
    encoded["instanceId"] = str(instance_id)
    return encoded


class TelemetryBridge:
    def __init__(
        self,
        sse_bus: SseBus,
        nudge: NudgeCallback | None = None,
        *,
        nudge_min_interval_seconds: float = 5.0,
    ) -> None:
        self.sse_bus: SseBus = sse_bus
        self.nudge: NudgeCallback | None = nudge
        self.nudge_min_interval_seconds: float = nudge_min_interval_seconds
        self._last_nudge: dict[UUID, datetime] = {}

    async def emit(
        self, instance_id: UUID, event: TelemetryEvent, *, now: datetime | None = None
    ) -> None:
        moment = now if now is not None else datetime.now(UTC)
        topic = _TOPICS[type(event)]
        self.sse_bus.publish(topic, _payload(instance_id, event))
        # Only a resource change is worth re-observing; progress/health are UI-only.
        if (
            isinstance(event, ResourceChanged)
            and self.nudge is not None
            and self._should_nudge(instance_id, moment)
        ):
            await self.nudge(instance_id)

    def _should_nudge(self, instance_id: UUID, now: datetime) -> bool:
        last = self._last_nudge.get(instance_id)
        if (
            last is not None
            and (now - last).total_seconds() < self.nudge_min_interval_seconds
        ):
            return False
        self._last_nudge[instance_id] = now
        return True
