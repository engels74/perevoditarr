"""Scheduling-window unit tests (P3-T1): timezone handling and midnight
rollover — the two behaviors the plan calls out — plus per-day gating and
tolerant decoding."""

from datetime import UTC, datetime

from perevoditarr.modules.rails.windows import (
    SchedulingWindow,
    decode_windows,
    window_matches,
    window_open_at,
)

# 2026-01-05 is a Monday (weekday 0); the day-gating tests key off that.
MONDAY = datetime(2026, 1, 5, tzinfo=UTC)


def test_monday_anchor_is_correct() -> None:
    assert MONDAY.weekday() == 0


def test_no_windows_means_always_open() -> None:
    assert window_open_at((), datetime(2026, 1, 5, 3, 0, tzinfo=UTC)) is True


def test_simple_window_gates_by_hour() -> None:
    window = SchedulingWindow(start="09:00", end="17:00", timezone="UTC")
    assert window_matches(window, datetime(2026, 1, 5, 12, 0, tzinfo=UTC)) is True
    assert window_matches(window, datetime(2026, 1, 5, 8, 59, tzinfo=UTC)) is False
    # End is exclusive.
    assert window_matches(window, datetime(2026, 1, 5, 17, 0, tzinfo=UTC)) is False


def test_window_evaluated_in_its_timezone() -> None:
    window = SchedulingWindow(start="09:00", end="17:00", timezone="America/New_York")
    # July → EDT (UTC-4): 13:00 UTC = 09:00 local (open), 12:00 UTC = 08:00 (shut).
    assert window_matches(window, datetime(2026, 7, 6, 13, 0, tzinfo=UTC)) is True
    assert window_matches(window, datetime(2026, 7, 6, 12, 0, tzinfo=UTC)) is False


def test_midnight_rollover_window() -> None:
    window = SchedulingWindow(start="22:00", end="02:00", timezone="UTC")
    assert window_matches(window, datetime(2026, 1, 5, 23, 0, tzinfo=UTC)) is True
    assert window_matches(window, datetime(2026, 1, 6, 1, 0, tzinfo=UTC)) is True
    assert window_matches(window, datetime(2026, 1, 6, 3, 0, tzinfo=UTC)) is False
    assert window_matches(window, datetime(2026, 1, 5, 21, 0, tzinfo=UTC)) is False


def test_rollover_day_gate_uses_start_day() -> None:
    # Monday-only 22:00-02:00: the Tuesday-morning tail still belongs to Monday.
    window = SchedulingWindow(days=(0,), start="22:00", end="02:00", timezone="UTC")
    assert window_matches(window, datetime(2026, 1, 5, 23, 0, tzinfo=UTC)) is True
    assert window_matches(window, datetime(2026, 1, 6, 1, 0, tzinfo=UTC)) is True
    # Tuesday evening is not Monday's window.
    assert window_matches(window, datetime(2026, 1, 6, 23, 0, tzinfo=UTC)) is False
    # Wednesday morning's tail belongs to Tuesday, which is excluded.
    assert window_matches(window, datetime(2026, 1, 7, 1, 0, tzinfo=UTC)) is False


def test_day_gating_non_rollover() -> None:
    window = SchedulingWindow(days=(5, 6), start="00:00", end="24:00", timezone="UTC")
    # Saturday 2026-01-10, Sunday 01-11 in; Monday 01-05 out.
    assert window_matches(window, datetime(2026, 1, 10, 12, 0, tzinfo=UTC)) is True
    assert window_matches(window, datetime(2026, 1, 11, 12, 0, tzinfo=UTC)) is True
    assert window_matches(window, MONDAY) is False


def test_multiple_windows_union() -> None:
    windows = (
        SchedulingWindow(start="00:00", end="06:00"),
        SchedulingWindow(start="20:00", end="24:00"),
    )
    assert window_open_at(windows, datetime(2026, 1, 5, 3, 0, tzinfo=UTC)) is True
    assert window_open_at(windows, datetime(2026, 1, 5, 22, 0, tzinfo=UTC)) is True
    assert window_open_at(windows, datetime(2026, 1, 5, 12, 0, tzinfo=UTC)) is False


def test_decode_windows_tolerates_bad_entries() -> None:
    raw: list[dict[str, object]] = [
        {"days": [1], "start": "09:00", "end": "17:00", "timezone": "UTC"},
        {"start": "99:99"},  # out-of-range time → dropped
        {"days": "not-a-list"},  # wrong shape → dropped
    ]
    decoded = decode_windows(raw)
    assert len(decoded) == 1
    assert decoded[0].days == (1,)


def test_unknown_timezone_falls_back_to_utc_not_always_open() -> None:
    window = SchedulingWindow(start="09:00", end="17:00", timezone="Mars/Olympus")
    assert window_matches(window, datetime(2026, 1, 5, 12, 0, tzinfo=UTC)) is True
    assert window_matches(window, datetime(2026, 1, 5, 3, 0, tzinfo=UTC)) is False
