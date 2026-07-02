"""Telemetry API DTOs (P3-T4): per-stream health for the UI status bar."""

from datetime import datetime
from uuid import UUID

from perevoditarr.core.schemas import ApiStruct
from perevoditarr.modules.telemetry.events import StreamKind
from perevoditarr.modules.telemetry.lifecycle import StreamStatus


class StreamHealthDto(ApiStruct):
    stream: StreamKind
    state: str  # live | degraded | down | connecting
    # True when the UI should show the "polling" (not websocket) indicator.
    polling: bool
    failures: int
    detail: str | None
    since: datetime | None


class InstanceTelemetryDto(ApiStruct):
    bazarr_instance_id: UUID
    instance_name: str
    streams: list[StreamHealthDto]


class TelemetryHealthResponse(ApiStruct):
    generated_at: datetime
    instances: list[InstanceTelemetryDto]


def stream_dto(stream: StreamKind, status: StreamStatus | None) -> StreamHealthDto:
    if status is None:
        # No socket has connected yet → the polling fallback is serving.
        return StreamHealthDto(
            stream=stream,
            state="down",
            polling=True,
            failures=0,
            detail="no live stream; polling",
            since=None,
        )
    return StreamHealthDto(
        stream=stream,
        state=status.state,
        polling=status.polling,
        failures=status.failures,
        detail=status.detail,
        since=status.since,
    )
