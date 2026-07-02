"""Telemetry connection lifecycle (P3-T4, NFR-7): pure state + backoff.

Each stream moves connecting → live, and on failure degrades to polling while it
retries with capped exponential backoff; a successful reconnect seamlessly
upgrades back to live. Kept pure so the degradation/backoff behavior is testable
without a real websocket.
"""

from datetime import datetime
from typing import Literal

import msgspec

type StreamState = Literal["connecting", "live", "degraded", "down"]


class StreamStatus(msgspec.Struct, frozen=True, kw_only=True):
    state: StreamState = "connecting"
    # Consecutive failed connect attempts (0 while live).
    failures: int = 0
    since: datetime | None = None
    detail: str | None = None

    @property
    def polling(self) -> bool:
        """Degraded/down streams are served by the polling fallback."""
        return self.state in ("degraded", "down")


def on_connected(*, now: datetime) -> StreamStatus:
    return StreamStatus(state="live", failures=0, since=now)


def on_failure(previous: StreamStatus, *, now: datetime, detail: str) -> StreamStatus:
    """A connect/read failure degrades the stream to polling and counts the
    attempt (so backoff grows). Never returns to `live` without a real connect."""
    failures = previous.failures + 1
    return StreamStatus(state="degraded", failures=failures, since=now, detail=detail)


def backoff_seconds(failures: int, *, base: float, cap: float) -> float:
    """Capped exponential reconnect backoff (base·2^(failures-1))."""
    if failures <= 0:
        return base
    exponent = min(failures - 1, 20)
    return min(base * float(1 << exponent), cap)
