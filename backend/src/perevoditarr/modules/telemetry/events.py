"""Telemetry event vocabulary (P3-T4, §7.3 / NFR-7).

TELEMETRY-ONLY. Everything in this module is the *liveness* plane: fuzzy,
ephemeral UI data. None of it is durable evidence and none of it may drive the
intent state machine (§7.3). That boundary is enforced structurally — the
correctness-plane modules (state machine, evidence, failure classifier,
dispatcher, verification) never import `perevoditarr.modules.telemetry`, and a
dedicated import test (`test_two_plane_separation`) asserts it. Correlation here
is deliberately fuzzy (job names, file paths, §6.5-granularity ids) because a
telemetry mismatch costs a cosmetic glitch, never a wrong transition.

Pure: imports only msgspec/typing.
"""

from typing import Literal

import msgspec

type StreamKind = Literal["bazarr_socketio", "lingarr_signalr", "polling"]


class JobProgress(msgspec.Struct, frozen=True, kw_only=True, tag="job_progress"):
    """A Bazarr task / Lingarr job progressing (fuzzy — matched by name/path)."""

    label: str
    value: int = 0
    maximum: int = 0
    message: str | None = None


class ResourceChanged(msgspec.Struct, frozen=True, kw_only=True, tag="resource"):
    """A Bazarr resource (series/episode/movie/wanted) changed — a nudge to
    re-observe, never itself evidence."""

    resource: str  # series | episode | movie | episode-wanted | movie-wanted | task
    action: str | None = None  # update | delete | ...
    ref: int | None = None  # the arr id when the payload carries one


class RequestProgress(
    msgspec.Struct, frozen=True, kw_only=True, tag="request_progress"
):
    """A Lingarr TranslationRequest changed status/progress (§6.5 granularity)."""

    request_id: int | None = None
    media_id: int | None = None
    status: str | None = None
    value: int | None = None
    maximum: int | None = None


class StreamHealth(msgspec.Struct, frozen=True, kw_only=True, tag="stream_health"):
    """A telemetry stream's connection state changed (drives the UI's
    websocket-vs-polling degradation indicator)."""

    stream: StreamKind
    state: str  # live | degraded | down | connecting
    detail: str | None = None


type TelemetryEvent = JobProgress | ResourceChanged | RequestProgress | StreamHealth
