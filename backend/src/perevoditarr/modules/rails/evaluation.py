"""Rail admission evaluation (P3-T1, §8.4): pure, explained verdicts.

`evaluate_admission` answers "may one more intent dispatch on this instance
right now, and if not, why" from a plain snapshot — usage counts, breaker
state, pause flag, scheduling-window openness, and the candidate's estimated
size. Volume-cap/budget usage is *derived* by the service from the durable
dispatch audit trail (restart-safe by construction, FR-R4), never from a
volatile counter that a crash could desync.

The circuit-breaker transition logic lives here too so it is testable without a
DB: `breaker_after_failure` / `breaker_after_success` / `breaker_probe_due`
compute the next state, and the service persists it.

Deliberately imports nothing from sqlalchemy/litestar/httpx.
"""

from datetime import datetime, timedelta
from typing import Literal

import msgspec

# Rail posture defaults when the active preset leaves a breaker knob unset.
DEFAULT_BREAKER_FAILURE_THRESHOLD = 5
DEFAULT_BREAKER_PROBE_MINUTES = 15

type BreakerState = Literal["closed", "open", "half_open"]


class RailConfig(msgspec.Struct, frozen=True, kw_only=True):
    """Thresholds from the active preset's rail posture (§8.4). `None` caps mean
    "no ceiling"; the window K lives in the dispatcher, not here."""

    hourly_cap: int | None = None
    daily_cap: int | None = None
    weekly_cap: int | None = None
    budget_daily_characters: int | None = None
    breaker_failure_threshold: int = DEFAULT_BREAKER_FAILURE_THRESHOLD
    breaker_probe_minutes: int = DEFAULT_BREAKER_PROBE_MINUTES


class RailUsage(msgspec.Struct, frozen=True, kw_only=True):
    """Dispatch counts derived from the ledger over the rolling windows ending
    at the evaluation moment (restart-safe: re-derived, never accumulated)."""

    hour_dispatches: int = 0
    day_dispatches: int = 0
    week_dispatches: int = 0
    day_characters: int = 0


class BreakerSnapshot(msgspec.Struct, frozen=True, kw_only=True):
    state: BreakerState = "closed"
    consecutive_failures: int = 0
    opened_at: datetime | None = None
    last_probe_at: datetime | None = None


class RailAllowed(msgspec.Struct, frozen=True, kw_only=True, tag="allowed"):
    # True when a breaker probe slot is being consumed: the dispatcher should
    # treat the outcome as the half-open probe (success closes, failure re-trips).
    breaker_probe: bool = False


class RailBlocked(msgspec.Struct, frozen=True, kw_only=True, tag="blocked"):
    rail: str  # pause | breaker | window | cap_hourly | cap_daily | cap_weekly | budget
    detail: str
    resets_at: datetime | None = None


type RailVerdict = RailAllowed | RailBlocked


def breaker_probe_due(
    breaker: BreakerSnapshot, probe_minutes: int, *, now: datetime
) -> bool:
    """An open breaker admits a single probe once `probe_minutes` have elapsed
    since it opened (or since the last probe)."""
    if breaker.state != "open":
        return False
    since = breaker.last_probe_at or breaker.opened_at
    if since is None:
        return True
    return now - since >= timedelta(minutes=probe_minutes)


def evaluate_admission(
    config: RailConfig,
    usage: RailUsage,
    breaker: BreakerSnapshot,
    *,
    paused: bool,
    window_open: bool,
    candidate_characters: int,
    now: datetime,
) -> RailVerdict:
    """Check order mirrors rail fundamentality: an operator pause, then the
    breaker (systemic failure), then the scheduling window, then volume caps,
    then the character budget. The first block wins so the reason is the most
    fundamental one."""
    if paused:
        return RailBlocked(rail="pause", detail="dispatch is paused")

    if breaker.state == "half_open":
        # A probe is already in flight; hold further dispatch until its verified
        # outcome closes (success) or re-opens (failure) the breaker.
        return RailBlocked(
            rail="breaker",
            detail="probing recovery; holding further dispatch until the probe resolves",
        )

    breaker_probe = False
    if breaker.state == "open":
        if breaker_probe_due(breaker, config.breaker_probe_minutes, now=now):
            breaker_probe = True
        else:
            since = breaker.last_probe_at or breaker.opened_at
            resets_at = (
                since + timedelta(minutes=config.breaker_probe_minutes)
                if since is not None
                else None
            )
            return RailBlocked(
                rail="breaker",
                detail=(
                    f"circuit breaker open after {breaker.consecutive_failures}"
                    " consecutive failures; probing again shortly"
                ),
                resets_at=resets_at,
            )

    if not window_open:
        return RailBlocked(
            rail="window", detail="outside the configured scheduling window"
        )

    caps: tuple[tuple[str, int | None, int], ...] = (
        ("cap_hourly", config.hourly_cap, usage.hour_dispatches),
        ("cap_daily", config.daily_cap, usage.day_dispatches),
        ("cap_weekly", config.weekly_cap, usage.week_dispatches),
    )
    for rail_name, cap, used in caps:
        if cap is not None and used >= cap:
            period = rail_name.removeprefix("cap_")
            return RailBlocked(
                rail=rail_name, detail=f"{period} cap reached ({used}/{cap})"
            )

    budget = config.budget_daily_characters
    if budget is not None and usage.day_characters + candidate_characters > budget:
        return RailBlocked(
            rail="budget",
            detail=(
                f"daily character budget would be exceeded"
                f" ({usage.day_characters:,} + {candidate_characters:,} > {budget:,})"
            ),
        )

    return RailAllowed(breaker_probe=breaker_probe)


# --- breaker transitions -----------------------------------------------------


def breaker_after_failure(
    breaker: BreakerSnapshot, threshold: int, *, now: datetime
) -> BreakerSnapshot:
    """A failure increments the consecutive count; reaching the threshold (or a
    failed half-open probe) trips the breaker open and stamps the trip time."""
    failures = breaker.consecutive_failures + 1
    if breaker.state == "half_open" or failures >= threshold:
        return BreakerSnapshot(
            state="open",
            consecutive_failures=failures,
            opened_at=now,
            last_probe_at=None,
        )
    return BreakerSnapshot(
        state="closed",
        consecutive_failures=failures,
        opened_at=None,
        last_probe_at=None,
    )


def breaker_after_success() -> BreakerSnapshot:
    """Any success closes the breaker and clears the failure streak, regardless
    of prior state (a half-open probe that succeeds fully closes it)."""
    return BreakerSnapshot(state="closed")


def breaker_mark_probe(breaker: BreakerSnapshot, *, now: datetime) -> BreakerSnapshot:
    """Move an open breaker to half-open as a probe is admitted, stamping the
    probe time so a concurrent evaluation cannot admit a second probe."""
    return BreakerSnapshot(
        state="half_open",
        consecutive_failures=breaker.consecutive_failures,
        opened_at=breaker.opened_at,
        last_probe_at=now,
    )
