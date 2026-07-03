"""Pure statistics aggregation (P4-T1, FR-U8): zero I/O imports.

The rollup job normalizes durable `intent_event` rows into `RollupEvent`
records (resolving failure class, translated-volume estimate, and
dispatch->convergence latency), then this module folds them into per-day
buckets. Kept pure so the outcome-mix / failure-taxonomy / duration maths are
unit-testable without a database.
"""

from collections.abc import Iterable
from datetime import date
from uuid import UUID

import msgspec

from perevoditarr.modules.intents.failure import FailureClass

type DailyKey = tuple[UUID, date, str]
type LanguageKey = tuple[UUID, date, str]

# Failure-taxonomy buckets whose evidence resolves to an unknown/absent class
# are counted under "transient" (the safe, retry-eligible default).
_DEFAULT_FAILURE_CLASS: FailureClass = "transient"


class RollupEvent(msgspec.Struct, frozen=True, kw_only=True):
    """One normalized terminal/dispatched transition ready to be counted."""

    bazarr_instance_id: UUID
    day: date
    media_type: str  # episode | movie
    to_state: str  # dispatched | converged | superseded | failed
    target_language: str
    failure_class: FailureClass | None = None
    characters: int = 0  # converged translated-volume estimate
    duration_seconds: int | None = None


class DailyCounts(msgspec.Struct, kw_only=True):
    dispatched: int = 0
    converged: int = 0
    superseded: int = 0
    failed: int = 0
    failed_transient: int = 0
    failed_environmental: int = 0
    failed_provider: int = 0
    failed_poison: int = 0
    converged_characters: int = 0
    duration_seconds_total: int = 0
    duration_samples: int = 0


def resolve_failure_class(evidence: dict[str, object] | None) -> FailureClass:
    """Read the §7.4 class the verifier stamped onto a failed event's evidence
    (`{"kind": "failure", "failure_class": ...}`); default transient."""
    if evidence is None:
        return _DEFAULT_FAILURE_CLASS
    raw = evidence.get("failure_class")
    if raw in ("transient", "environmental", "provider", "poison"):
        return raw  # type: ignore[return-value]  # narrowed by the literal membership test
    return _DEFAULT_FAILURE_CLASS


def aggregate_daily(events: Iterable[RollupEvent]) -> dict[DailyKey, DailyCounts]:
    buckets: dict[DailyKey, DailyCounts] = {}
    for event in events:
        key: DailyKey = (event.bazarr_instance_id, event.day, event.media_type)
        counts = buckets.get(key)
        if counts is None:
            counts = DailyCounts()
            buckets[key] = counts
        _fold(counts, event)
    return buckets


def aggregate_language_daily(events: Iterable[RollupEvent]) -> dict[LanguageKey, int]:
    """Converged counts per (instance, day, target language) — the coverage
    trend series. Only convergences count toward coverage growth."""
    buckets: dict[LanguageKey, int] = {}
    for event in events:
        if event.to_state != "converged":
            continue
        key: LanguageKey = (event.bazarr_instance_id, event.day, event.target_language)
        buckets[key] = buckets.get(key, 0) + 1
    return buckets


def _fold(counts: DailyCounts, event: RollupEvent) -> None:
    match event.to_state:
        case "dispatched":
            counts.dispatched += 1
        case "converged":
            counts.converged += 1
            counts.converged_characters += event.characters
            if event.duration_seconds is not None:
                counts.duration_seconds_total += event.duration_seconds
                counts.duration_samples += 1
        case "superseded":
            counts.superseded += 1
        case "failed":
            counts.failed += 1
            failure_class = event.failure_class or _DEFAULT_FAILURE_CLASS
            match failure_class:
                case "transient":
                    counts.failed_transient += 1
                case "environmental":
                    counts.failed_environmental += 1
                case "provider":
                    counts.failed_provider += 1
                case "poison":
                    counts.failed_poison += 1
        case _:
            # Non-outcome transitions never reach the rollup query, but stay
            # defensive: an unexpected state is simply not counted.
            pass
