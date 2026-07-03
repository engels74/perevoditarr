"""Pure stats aggregation (P4-T1, FR-U8): daily folding, failure-taxonomy
split, duration sampling, coverage-trend counting."""

from datetime import date
from uuid import UUID

from perevoditarr.modules.intents.failure import FailureClass
from perevoditarr.modules.stats.aggregation import (
    RollupEvent,
    aggregate_daily,
    aggregate_language_daily,
    resolve_failure_class,
)

INSTANCE = UUID("11111111-1111-1111-1111-111111111111")
DAY = date(2026, 7, 1)


def _event(
    to_state: str,
    *,
    media_type: str = "episode",
    target_language: str = "da",
    day: date = DAY,
    failure_class: FailureClass | None = None,
    characters: int = 0,
    duration_seconds: int | None = None,
) -> RollupEvent:
    return RollupEvent(
        bazarr_instance_id=INSTANCE,
        day=day,
        media_type=media_type,
        to_state=to_state,
        target_language=target_language,
        failure_class=failure_class,
        characters=characters,
        duration_seconds=duration_seconds,
    )


def test_resolve_failure_class_reads_evidence() -> None:
    assert resolve_failure_class({"failure_class": "provider"}) == "provider"
    assert resolve_failure_class({"failure_class": "poison"}) == "poison"


def test_resolve_failure_class_defaults_transient() -> None:
    assert resolve_failure_class(None) == "transient"
    assert resolve_failure_class({"failure_class": "nonsense"}) == "transient"
    assert resolve_failure_class({}) == "transient"


def test_aggregate_daily_counts_outcomes() -> None:
    events = [
        _event("dispatched"),
        _event("dispatched"),
        _event("converged", characters=800, duration_seconds=120),
        _event("superseded"),
    ]
    buckets = aggregate_daily(events)
    counts = buckets[(INSTANCE, DAY, "episode")]
    assert counts.dispatched == 2
    assert counts.converged == 1
    assert counts.superseded == 1
    assert counts.converged_characters == 800
    assert counts.duration_seconds_total == 120
    assert counts.duration_samples == 1


def test_aggregate_daily_splits_failure_taxonomy() -> None:
    events = [
        _event("failed", failure_class="transient"),
        _event("failed", failure_class="environmental"),
        _event("failed", failure_class="provider"),
        _event("failed", failure_class="poison"),
        _event("failed", failure_class="provider"),
    ]
    counts = aggregate_daily(events)[(INSTANCE, DAY, "episode")]
    assert counts.failed == 5
    assert counts.failed_transient == 1
    assert counts.failed_environmental == 1
    assert counts.failed_provider == 2
    assert counts.failed_poison == 1


def test_aggregate_daily_separates_media_type_and_day() -> None:
    other_day = date(2026, 7, 2)
    events = [
        _event("converged", media_type="episode"),
        _event("converged", media_type="movie"),
        _event("converged", media_type="episode", day=other_day),
    ]
    buckets = aggregate_daily(events)
    assert buckets[(INSTANCE, DAY, "episode")].converged == 1
    assert buckets[(INSTANCE, DAY, "movie")].converged == 1
    assert buckets[(INSTANCE, other_day, "episode")].converged == 1


def test_converged_without_duration_is_not_sampled() -> None:
    counts = aggregate_daily([_event("converged", characters=800)])[
        (INSTANCE, DAY, "episode")
    ]
    assert counts.converged == 1
    assert counts.duration_samples == 0
    assert counts.duration_seconds_total == 0


def test_aggregate_language_daily_counts_only_convergences() -> None:
    events = [
        _event("converged", target_language="da"),
        _event("converged", target_language="da"),
        _event("converged", target_language="de"),
        _event("dispatched", target_language="da"),
        _event("failed", target_language="da", failure_class="provider"),
    ]
    language = aggregate_language_daily(events)
    assert language[(INSTANCE, DAY, "da")] == 2
    assert language[(INSTANCE, DAY, "de")] == 1
