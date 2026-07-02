"""Telemetry unit tests (P3-T4): payload parsing, connection lifecycle/backoff,
and the SSE bridge + throttled re-observation nudge."""

from datetime import UTC, datetime, timedelta
from typing import override
from uuid import uuid4

from perevoditarr.core.sse import SseBus
from perevoditarr.modules.telemetry.bridge import TelemetryBridge
from perevoditarr.modules.telemetry.events import (
    JobProgress,
    RequestProgress,
    ResourceChanged,
)
from perevoditarr.modules.telemetry.lifecycle import (
    StreamStatus,
    backoff_seconds,
    on_connected,
    on_failure,
)
from perevoditarr.modules.telemetry.parsing import (
    parse_bazarr_event,
    parse_lingarr_progress,
    parse_lingarr_request,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


class RecordingBus(SseBus):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, object]] = []

    @override
    def publish(self, topic: str, data: object) -> None:
        self.events.append((topic, data))
        super().publish(topic, data)


# --- parsing -----------------------------------------------------------------


def test_parse_bazarr_task_is_job_progress() -> None:
    event = parse_bazarr_event(
        {
            "type": "task",
            "action": "update",
            "payload": {
                "name": "Translating EN to DA",
                "progress_value": 340,
                "progress_max": 812,
                "progress_message": "line 340/812",
            },
        }
    )
    assert isinstance(event, JobProgress)
    assert event.value == 340
    assert event.maximum == 812


def test_parse_bazarr_resource_is_nudge() -> None:
    event = parse_bazarr_event({"type": "episode", "action": "update", "payload": 7})
    assert isinstance(event, ResourceChanged)
    assert event.resource == "episode"
    assert event.ref == 7


def test_parse_bazarr_unknown_type_is_generic_resource() -> None:
    assert isinstance(parse_bazarr_event({"type": "wat"}), ResourceChanged)
    assert parse_bazarr_event({}) is None


def test_parse_lingarr_request_and_progress() -> None:
    request = parse_lingarr_request({"id": 12, "mediaId": 3, "status": "InProgress"})
    assert isinstance(request, RequestProgress)
    assert request.request_id == 12
    assert request.status == "InProgress"
    progress = parse_lingarr_progress({"jobId": 12, "value": 5, "total": 10})
    assert isinstance(progress, RequestProgress)
    assert progress.value == 5
    assert progress.maximum == 10
    assert parse_lingarr_request({}) is None


# --- lifecycle ---------------------------------------------------------------


def test_connect_and_failure_transitions() -> None:
    live = on_connected(now=NOW)
    assert live.state == "live"
    assert not live.polling
    degraded = on_failure(live, now=NOW, detail="proxy blocked upgrade")
    assert degraded.state == "degraded"
    assert degraded.polling
    assert degraded.failures == 1
    assert on_failure(degraded, now=NOW, detail="again").failures == 2


def test_backoff_is_capped_and_exponential() -> None:
    assert backoff_seconds(1, base=2.0, cap=120.0) == 2.0
    assert backoff_seconds(2, base=2.0, cap=120.0) == 4.0
    assert backoff_seconds(3, base=2.0, cap=120.0) == 8.0
    assert backoff_seconds(50, base=2.0, cap=120.0) == 120.0


def test_default_status_starts_polling_until_connected() -> None:
    assert StreamStatus().polling is False  # connecting is not yet degraded
    assert StreamStatus(state="down").polling is True


# --- bridge ------------------------------------------------------------------


async def test_bridge_publishes_and_nudges_on_resource_change() -> None:
    bus = RecordingBus()
    nudged: list[object] = []

    async def nudge(instance_id: object) -> None:
        nudged.append(instance_id)

    bridge = TelemetryBridge(bus, nudge, nudge_min_interval_seconds=60.0)
    instance_id = uuid4()

    await bridge.emit(instance_id, ResourceChanged(resource="episode", ref=5), now=NOW)
    assert any(topic == "telemetry.resource" for topic, _ in bus.events)
    assert nudged == [instance_id]

    # Progress publishes but never nudges.
    await bridge.emit(instance_id, JobProgress(label="x"), now=NOW)
    assert any(topic == "telemetry.jobs" for topic, _ in bus.events)
    assert len(nudged) == 1

    # A second resource change within the window is coalesced (no extra nudge).
    await bridge.emit(
        instance_id,
        ResourceChanged(resource="movie"),
        now=NOW + timedelta(seconds=5),
    )
    assert len(nudged) == 1

    # After the window it nudges again.
    await bridge.emit(
        instance_id,
        ResourceChanged(resource="movie"),
        now=NOW + timedelta(seconds=120),
    )
    assert len(nudged) == 2
