"""Deterministic simulator clock: tests advance time explicitly."""

from datetime import UTC, datetime, timedelta


class SimClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now: datetime = start or datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta
