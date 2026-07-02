"""Telemetry payload parsers (P3-T4): pure, tolerant, transport-free.

Turn raw Socket.IO / SignalR payloads into telemetry events. Parsing is
deliberately defensive — an unrecognized or malformed shape yields `None`
(dropped) rather than raising, because telemetry is cosmetic (§7.3) and upstream
event shapes are not a contract Perevoditarr depends on (§2.4). The exact event
names/keys are best-effort per researched upstream; unknown shapes degrade to a
generic resource-changed nudge, never an error.
"""

from typing import cast

from perevoditarr.modules.telemetry.events import (
    JobProgress,
    RequestProgress,
    ResourceChanged,
    TelemetryEvent,
)

# Bazarr Socket.IO resource types that are re-observe nudges (not job progress).
_BAZARR_RESOURCES = frozenset(
    {
        "series",
        "episode",
        "movie",
        "episode-wanted",
        "movie-wanted",
        "badges",
        "settings",
        "languages",
    }
)


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def parse_bazarr_event(raw: dict[str, object]) -> TelemetryEvent | None:
    """Bazarr emits `{type, action, payload}`. `task` carries job progress;
    other resource types are re-observe nudges."""
    resource = _as_str(raw.get("type"))
    if resource is None:
        return None
    action = _as_str(raw.get("action"))
    payload = raw.get("payload")
    if resource == "task":
        detail = _as_dict(payload)
        return JobProgress(
            label=_as_str(detail.get("name")) or action or "task",
            value=_as_int(detail.get("progress_value")) or 0,
            maximum=_as_int(detail.get("progress_max")) or 0,
            message=_as_str(detail.get("progress_message")),
        )
    if resource in _BAZARR_RESOURCES:
        return ResourceChanged(resource=resource, action=action, ref=_as_int(payload))
    return ResourceChanged(resource=resource, action=action)


def parse_lingarr_request(raw: dict[str, object]) -> RequestProgress | None:
    """TranslationRequestsHub: a request changed status (§6.5 granularity)."""
    request_id = _as_int(raw.get("id")) or _as_int(raw.get("requestId"))
    status = _as_str(raw.get("status"))
    if request_id is None and status is None:
        return None
    return RequestProgress(
        request_id=request_id,
        media_id=_as_int(raw.get("mediaId")),
        status=status,
    )


def parse_lingarr_progress(raw: dict[str, object]) -> RequestProgress | None:
    """JobProgressHub: line-level progress for a running translation."""
    value = _as_int(raw.get("value")) or _as_int(raw.get("progress"))
    maximum = _as_int(raw.get("maximum")) or _as_int(raw.get("total"))
    request_id = _as_int(raw.get("id")) or _as_int(raw.get("jobId"))
    if value is None and request_id is None:
        return None
    return RequestProgress(
        request_id=request_id,
        media_id=_as_int(raw.get("mediaId")),
        value=value,
        maximum=maximum,
    )
