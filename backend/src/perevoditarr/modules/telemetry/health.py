"""Telemetry stream-health registry (P3-T4): process singleton.

Created in app assembly (like the SSE bus / lock registry, NFR-3 single
container). Consumers update per-(instance, stream) status; the SSE bridge and
the doctor read it for the UI's websocket-vs-polling indicator. Volatile by
design — health is liveness, not correctness.
"""

from uuid import UUID

from perevoditarr.modules.telemetry.events import StreamKind
from perevoditarr.modules.telemetry.lifecycle import StreamStatus


class TelemetryHealthRegistry:
    def __init__(self) -> None:
        self._status: dict[tuple[UUID, StreamKind], StreamStatus] = {}

    def set(self, instance_id: UUID, stream: StreamKind, status: StreamStatus) -> None:
        self._status[(instance_id, stream)] = status

    def get(self, instance_id: UUID, stream: StreamKind) -> StreamStatus | None:
        return self._status.get((instance_id, stream))

    def for_instance(self, instance_id: UUID) -> dict[StreamKind, StreamStatus]:
        return {
            stream: status
            for (owner, stream), status in self._status.items()
            if owner == instance_id
        }

    def snapshot(self) -> dict[tuple[UUID, StreamKind], StreamStatus]:
        return dict(self._status)
