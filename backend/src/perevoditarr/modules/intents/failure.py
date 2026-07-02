"""Dispatched-intent verification & failure taxonomy (P3-T3, §7.4): pure logic.

`classify_dispatched` decides, from durable evidence only (§6.8), what becomes
of a dispatched intent: converged (subtitle present + our action-6 in the lease
window), superseded (present but not via our translation — FR-V3 keeps that out
of budget/stats), a classified failure, or still-waiting. Failures follow the
§7.4 taxonomy — transient (retry), environmental (park / needs-attention, no
retry burn), provider/systemic (retry + feed the breaker), poison (quarantine
after the attempt ceiling). Backoff is intent-level and exponential (FR-R5).

Imports nothing from sqlalchemy/litestar/httpx — unit-testable in isolation.
"""

from typing import Literal

import msgspec

type FailureClass = Literal["transient", "environmental", "provider", "poison"]

# Lingarr error messages that mean the input, not the provider, is at fault —
# retrying burns money without any chance of success (§7.4 environmental).
_ENVIRONMENTAL_MARKERS = (
    "not found",
    "no such file",
    "missing",
    "path",
    "does not exist",
    "unreadable",
    "empty subtitle",
)


class LingarrFailure(msgspec.Struct, frozen=True, kw_only=True):
    status: str  # Failed | Cancelled
    environmental: bool = False


class Converged(msgspec.Struct, frozen=True, kw_only=True, tag="converged"):
    pass


class SupersededOther(msgspec.Struct, frozen=True, kw_only=True, tag="superseded"):
    detail: str


class NeedsAttention(msgspec.Struct, frozen=True, kw_only=True, tag="needs_attention"):
    reason: str
    failure_class: FailureClass = "environmental"


class RetryScheduled(msgspec.Struct, frozen=True, kw_only=True, tag="retry"):
    reason: str
    failure_class: FailureClass


class Quarantine(msgspec.Struct, frozen=True, kw_only=True, tag="quarantine"):
    reason: str
    failure_class: FailureClass


class StillWaiting(msgspec.Struct, frozen=True, kw_only=True, tag="waiting"):
    pass


type DispatchedOutcome = (
    Converged
    | SupersededOther
    | NeedsAttention
    | RetryScheduled
    | Quarantine
    | StillWaiting
)


def is_environmental_message(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return any(marker in lowered for marker in _ENVIRONMENTAL_MARKERS)


def classify_dispatched(
    *,
    target_present: bool,
    translated_in_window: bool,
    lingarr_failure: LingarrFailure | None,
    lease_expired: bool,
    attempts: int,
    max_attempts: int,
) -> DispatchedOutcome:
    if target_present:
        if translated_in_window:
            return Converged()
        return SupersededOther(
            detail="target subtitle appeared by other means (not our translation)"
        )
    if lingarr_failure is not None:
        if lingarr_failure.environmental:
            return NeedsAttention(
                reason=f"environmental failure ({lingarr_failure.status}); parked"
            )
        if attempts >= max_attempts:
            return Quarantine(
                reason=(f"provider failure persisted across {attempts} attempts"),
                failure_class="provider",
            )
        return RetryScheduled(
            reason=f"provider failure ({lingarr_failure.status})",
            failure_class="provider",
        )
    if lease_expired:
        if attempts >= max_attempts:
            return Quarantine(
                reason=f"no convergence evidence across {attempts} attempts",
                failure_class="poison",
            )
        return RetryScheduled(
            reason="lease expired without convergence evidence",
            failure_class="transient",
        )
    return StillWaiting()


def retry_backoff_seconds(attempts: int, base_seconds: int, *, cap_seconds: int) -> int:
    """Exponential intent-level backoff (FR-R5): base·2^(attempts-1), capped.
    Attempts is 1-based (the first retry waits `base_seconds`). The exponent is
    clamped before shifting so a large attempt count can't overflow."""
    exponent = min(max(0, attempts - 1), 40)
    return min(base_seconds << exponent, cap_seconds)
