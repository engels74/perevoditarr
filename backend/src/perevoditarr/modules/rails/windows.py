"""Scheduling windows (P3-T1, §8.4): pure allow/deny of a moment.

A window restricts dispatch to certain weekdays and an intra-day time range in
a named timezone; when the end is at or before the start the window wraps past
midnight (e.g. 22:00-02:00), and the configured days gate the *start* day. No
windows configured ⇒ always open. Pure: `zoneinfo` + `datetime` only, so the
timezone/rollover behavior the plan calls out is unit-testable against a fixed
clock with no DB or HTTP.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import msgspec

_MINUTES_PER_DAY = 24 * 60


class SchedulingWindow(msgspec.Struct, frozen=True, kw_only=True):
    """One allowed dispatch window. `days` are `date.weekday()` values
    (0=Monday…6=Sunday); empty means every day. Times are `HH:MM` (00:00-24:00)
    in `timezone`."""

    days: tuple[int, ...] = ()
    start: str = "00:00"
    end: str = "24:00"
    timezone: str = "UTC"


def _parse_minutes(raw: str) -> int:
    hours_str, _, minutes_str = raw.partition(":")
    hours = int(hours_str)
    minutes = int(minutes_str) if minutes_str else 0
    total = hours * 60 + minutes
    if not 0 <= total <= _MINUTES_PER_DAY:
        raise ValueError(f"time {raw!r} out of range (00:00-24:00)")
    return total


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        # An unreadable tz name must not silently widen the window to "always
        # open"; fall back to UTC so evaluation stays deterministic.
        return ZoneInfo("UTC")


def _day_allowed(days: tuple[int, ...], weekday: int) -> bool:
    return not days or weekday in days


def window_matches(window: SchedulingWindow, moment: datetime) -> bool:
    local = moment.astimezone(_zone(window.timezone))
    start = _parse_minutes(window.start)
    end = _parse_minutes(window.end)
    minute_of_day = local.hour * 60 + local.minute
    if end > start:
        return (
            _day_allowed(window.days, local.weekday()) and start <= minute_of_day < end
        )
    # Wrapped window: the tail before `end` belongs to the previous day's
    # window, so it is gated by the previous day's weekday.
    if minute_of_day >= start:
        return _day_allowed(window.days, local.weekday())
    if minute_of_day < end:
        previous_weekday = (local - timedelta(days=1)).weekday()
        return _day_allowed(window.days, previous_weekday)
    return False


def window_open_at(windows: Sequence[SchedulingWindow], moment: datetime) -> bool:
    """True when `moment` falls inside any window (or none are configured)."""
    if not windows:
        return True
    return any(window_matches(window, moment) for window in windows)


def decode_windows(
    raw: list[dict[str, object]] | None,
) -> tuple[SchedulingWindow, ...]:
    """JSON column → typed windows. A malformed entry is dropped individually
    (a row written by another build stays usable), and decoding never raises."""
    if not raw:
        return ()
    windows: list[SchedulingWindow] = []
    for item in raw:
        try:
            window = msgspec.convert(item, type=SchedulingWindow)
            # Force-parse the times so a structurally-valid but out-of-range
            # entry is rejected here, not at evaluation time.
            _ = _parse_minutes(window.start)
            _ = _parse_minutes(window.end)
        except msgspec.ValidationError, ValueError:
            continue
        windows.append(window)
    return tuple(windows)


def encode_windows(windows: Sequence[SchedulingWindow]) -> list[dict[str, object]]:
    return msgspec.json.decode(
        msgspec.json.encode(list(windows)), type=list[dict[str, object]]
    )
