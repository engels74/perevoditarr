"""Rail admission + breaker unit tests (P3-T1): cap rollover, budget boundary,
block precedence, and the breaker lifecycle incl. the half-open probe race."""

from datetime import UTC, datetime, timedelta

from perevoditarr.modules.rails.evaluation import (
    BreakerSnapshot,
    RailAllowed,
    RailBlocked,
    RailConfig,
    RailUsage,
    RailVerdict,
    breaker_after_failure,
    breaker_after_success,
    breaker_mark_probe,
    breaker_probe_due,
    evaluate_admission,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
CLOSED = BreakerSnapshot()


def _allow(
    config: RailConfig,
    usage: RailUsage,
    *,
    paused: bool = False,
    window_open: bool = True,
    candidate_characters: int = 0,
) -> RailVerdict:
    return evaluate_admission(
        config,
        usage,
        CLOSED,
        paused=paused,
        window_open=window_open,
        candidate_characters=candidate_characters,
        now=NOW,
    )


def test_open_when_nothing_configured() -> None:
    verdict = _allow(RailConfig(), RailUsage())
    assert isinstance(verdict, RailAllowed)


def test_hourly_cap_blocks_at_limit() -> None:
    config = RailConfig(hourly_cap=2)
    assert isinstance(_allow(config, RailUsage(hour_dispatches=1)), RailAllowed)
    blocked = _allow(config, RailUsage(hour_dispatches=2))
    assert isinstance(blocked, RailBlocked)
    assert blocked.rail == "cap_hourly"


def test_daily_and_weekly_caps() -> None:
    daily = _allow(RailConfig(daily_cap=5), RailUsage(day_dispatches=5))
    assert isinstance(daily, RailBlocked)
    assert daily.rail == "cap_daily"
    weekly = _allow(RailConfig(weekly_cap=10), RailUsage(week_dispatches=10))
    assert isinstance(weekly, RailBlocked)
    assert weekly.rail == "cap_weekly"


def test_budget_boundary_is_inclusive() -> None:
    config = RailConfig(budget_daily_characters=1000)
    # 900 + 100 == 1000 is allowed; 900 + 101 exceeds.
    assert isinstance(
        _allow(config, RailUsage(day_characters=900), candidate_characters=100),
        RailAllowed,
    )
    blocked = _allow(config, RailUsage(day_characters=900), candidate_characters=101)
    assert isinstance(blocked, RailBlocked)
    assert blocked.rail == "budget"


def test_pause_beats_every_other_block() -> None:
    # Even with a full cap, the reason surfaced is the operator pause.
    config = RailConfig(hourly_cap=1)
    verdict = _allow(config, RailUsage(hour_dispatches=5), paused=True)
    assert isinstance(verdict, RailBlocked)
    assert verdict.rail == "pause"


def test_window_closed_blocks_before_caps() -> None:
    verdict = _allow(RailConfig(hourly_cap=1), RailUsage(), window_open=False)
    assert isinstance(verdict, RailBlocked)
    assert verdict.rail == "window"


def test_open_breaker_not_yet_due_blocks() -> None:
    breaker = BreakerSnapshot(
        state="open", consecutive_failures=5, opened_at=NOW - timedelta(minutes=5)
    )
    verdict = evaluate_admission(
        RailConfig(breaker_probe_minutes=15),
        RailUsage(),
        breaker,
        paused=False,
        window_open=True,
        candidate_characters=0,
        now=NOW,
    )
    assert isinstance(verdict, RailBlocked)
    assert verdict.rail == "breaker"
    opened = breaker.opened_at
    assert opened is not None
    assert verdict.resets_at == opened + timedelta(minutes=15)


def test_open_breaker_due_admits_a_probe() -> None:
    breaker = BreakerSnapshot(
        state="open", consecutive_failures=5, opened_at=NOW - timedelta(minutes=20)
    )
    verdict = evaluate_admission(
        RailConfig(breaker_probe_minutes=15),
        RailUsage(),
        breaker,
        paused=False,
        window_open=True,
        candidate_characters=0,
        now=NOW,
    )
    assert isinstance(verdict, RailAllowed)
    assert verdict.breaker_probe is True


def test_breaker_trips_at_threshold() -> None:
    breaker = BreakerSnapshot(state="closed", consecutive_failures=4)
    tripped = breaker_after_failure(breaker, threshold=5, now=NOW)
    assert tripped.state == "open"
    assert tripped.consecutive_failures == 5
    assert tripped.opened_at == NOW


def test_breaker_stays_closed_below_threshold() -> None:
    stepped = breaker_after_failure(CLOSED, threshold=5, now=NOW)
    assert stepped.state == "closed"
    assert stepped.consecutive_failures == 1


def test_half_open_failure_retrips() -> None:
    half = BreakerSnapshot(state="half_open", consecutive_failures=5)
    retripped = breaker_after_failure(half, threshold=5, now=NOW)
    assert retripped.state == "open"
    assert retripped.opened_at == NOW


def test_success_closes_breaker() -> None:
    assert breaker_after_success().state == "closed"
    assert breaker_after_success().consecutive_failures == 0


def test_probe_marking_prevents_a_second_concurrent_probe() -> None:
    open_breaker = BreakerSnapshot(
        state="open", consecutive_failures=5, opened_at=NOW - timedelta(minutes=30)
    )
    assert breaker_probe_due(open_breaker, 15, now=NOW) is True
    # One evaluator admits the probe and marks it; the breaker is now half-open
    # with last_probe_at stamped, so a racing evaluator sees no due probe.
    half = breaker_mark_probe(open_breaker, now=NOW)
    assert half.state == "half_open"
    assert half.last_probe_at == NOW
    assert breaker_probe_due(half, 15, now=NOW) is False
