"""Stats rollup job (P4-T1, FR-U8): re-derive the daily counters from the
durable `intent_event` audit trail.

Recomputed idempotently over a trailing window (default: the last two UTC days,
to absorb late-arriving convergences without a full rescan). Because every count
is re-derived from durable evidence, the rollup is crash-safe (FR-R4) and never
double-counts across a restart. Dialect-portable: the JSON `evidence` column is
read row-by-row in Python, never with a dialect-specific JSON-path query
(NFR-2).
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.logging import get_logger
from perevoditarr.modules.dispatch.estimation import RollingActuals, estimate_intent
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.state_machine import IntentState
from perevoditarr.modules.stats.aggregation import (
    RollupEvent,
    aggregate_daily,
    aggregate_language_daily,
    resolve_failure_class,
)
from perevoditarr.modules.stats.models import StatsDaily, StatsLanguageDaily
from perevoditarr.modules.stats.reconciliation import effective_actuals

_logger = get_logger()

_OUTCOME_STATES: tuple[str, ...] = (
    IntentState.DISPATCHED.value,
    IntentState.CONVERGED.value,
    IntentState.SUPERSEDED.value,
    IntentState.FAILED.value,
)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def run_stats_rollup(
    alchemy: SQLAlchemyAsyncConfig, *, days: int = 2, now: datetime | None = None
) -> int:
    """Recompute the daily rollup for the trailing `days` UTC days. Returns the
    number of `stats_daily` rows written."""
    moment = (now if now is not None else datetime.now(UTC)).astimezone(UTC)
    start_day = moment.date() - timedelta(days=max(0, days - 1))
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=UTC)
    async with alchemy.get_session() as session:
        return await _rollup_window(session, start_day=start_day, since=window_start)


async def run_stats_backfill(alchemy: SQLAlchemyAsyncConfig) -> int:
    """One-time historical backfill for upgrades that already have an
    `intent_event` audit trail but no rollup rows yet.

    The periodic rollup only recomputes a trailing two-day window, so on the
    first boot after this feature ships every outcome older than that window
    would stay invisible to the dashboard's 7/30/90-day ranges until enough
    real time passed. While `stats_daily` is still empty, recompute every UTC
    day from the earliest recorded outcome event forward so the full history is
    materialised once. A no-op as soon as any rollup row exists — the
    trailing-window job then keeps it current. Returns the number of
    `stats_daily` rows written."""
    async with alchemy.get_session() as session:
        already_rolled = await session.scalar(select(StatsDaily.id).limit(1))
        if already_rolled is not None:
            return 0
        earliest = await session.scalar(
            select(func.min(IntentEvent.created_at)).where(
                IntentEvent.to_state.in_(_OUTCOME_STATES)
            )
        )
        if earliest is None:
            return 0
        start_day = _utc(earliest).date()
        window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=UTC)
        return await _rollup_window(session, start_day=start_day, since=window_start)


async def _rollup_window(
    session: AsyncSession, *, start_day: date, since: datetime
) -> int:
    rows = (
        (
            await session.execute(
                select(
                    IntentEvent.intent_id,
                    IntentEvent.to_state,
                    IntentEvent.evidence,
                    IntentEvent.created_at,
                    Intent.bazarr_instance_id,
                    Intent.media_type,
                    Intent.target_language,
                )
                .join(Intent, IntentEvent.intent_id == Intent.id)
                .where(
                    IntentEvent.created_at >= since,
                    IntentEvent.to_state.in_(_OUTCOME_STATES),
                )
            )
        )
        .tuples()
        .all()
    )

    converged_ids = [
        intent_id
        for intent_id, to_state, _evidence, _created, _iid, _mt, _tl in rows
        if to_state == IntentState.CONVERGED.value
    ]
    dispatched_at = await _dispatched_times(session, converged_ids)
    actuals = await _actuals_by_instance(session, {row[4] for row in rows})

    events: list[RollupEvent] = []
    for (
        intent_id,
        to_state,
        evidence,
        created_at,
        instance_id,
        media_type,
        target_language,
    ) in rows:
        created = _utc(created_at)
        characters = 0
        duration: int | None = None
        if to_state == IntentState.CONVERGED.value:
            estimate = estimate_intent(
                "episode" if media_type == "episode" else "movie",
                actuals.get(instance_id),
            )
            characters = estimate.characters
            duration = _duration(dispatched_at.get(intent_id, ()), created)
        events.append(
            RollupEvent(
                bazarr_instance_id=instance_id,
                day=created.date(),
                media_type=media_type,
                to_state=to_state,
                target_language=target_language,
                failure_class=(
                    resolve_failure_class(evidence)
                    if to_state == IntentState.FAILED.value
                    else None
                ),
                characters=characters,
                duration_seconds=duration,
            )
        )

    daily = aggregate_daily(events)
    language = aggregate_language_daily(events)

    # Fully replace the recomputed window (day >= start_day) so a re-run is
    # idempotent and reflects supersessions/late convergences exactly.
    _ = await session.execute(delete(StatsDaily).where(StatsDaily.day >= start_day))
    _ = await session.execute(
        delete(StatsLanguageDaily).where(StatsLanguageDaily.day >= start_day)
    )
    for (instance_id, day, media_type), counts in daily.items():
        session.add(
            StatsDaily(
                bazarr_instance_id=instance_id,
                day=day,
                media_type=media_type,
                dispatched=counts.dispatched,
                converged=counts.converged,
                superseded=counts.superseded,
                failed=counts.failed,
                failed_transient=counts.failed_transient,
                failed_environmental=counts.failed_environmental,
                failed_provider=counts.failed_provider,
                failed_poison=counts.failed_poison,
                converged_characters=counts.converged_characters,
                duration_seconds_total=counts.duration_seconds_total,
                duration_samples=counts.duration_samples,
            )
        )
    for (instance_id, day, language_code), converged in language.items():
        session.add(
            StatsLanguageDaily(
                bazarr_instance_id=instance_id,
                day=day,
                target_language=language_code,
                converged=converged,
            )
        )
    await session.commit()
    return len(daily)


async def _dispatched_times(
    session: AsyncSession, intent_ids: list[UUID]
) -> dict[UUID, tuple[datetime, ...]]:
    if not intent_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(IntentEvent.intent_id, IntentEvent.created_at).where(
                    IntentEvent.intent_id.in_(intent_ids),
                    IntentEvent.to_state == IntentState.DISPATCHED.value,
                )
            )
        )
        .tuples()
        .all()
    )
    by_intent: dict[UUID, list[datetime]] = {}
    for intent_id, created_at in rows:
        by_intent.setdefault(intent_id, []).append(_utc(created_at))
    return {key: tuple(sorted(values)) for key, values in by_intent.items()}


def _duration(dispatched: tuple[datetime, ...], converged_at: datetime) -> int | None:
    """Latency from the latest dispatch preceding this convergence (retries
    pick the most recent dispatch, matching real provider spend)."""
    prior = [moment for moment in dispatched if moment <= converged_at]
    if not prior:
        return None
    return max(0, int((converged_at - max(prior)).total_seconds()))


async def _actuals_by_instance(
    session: AsyncSession, instance_ids: set[UUID]
) -> dict[UUID, RollingActuals | None]:
    return {
        instance_id: await effective_actuals(session, bazarr_instance_id=instance_id)
        for instance_id in instance_ids
    }


async def stats_rollup_loop(
    alchemy: SQLAlchemyAsyncConfig, interval_seconds: int, *, days: int = 2
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            _ = await run_stats_rollup(alchemy, days=days)
        except Exception as error:
            _logger.warning("stats rollup loop iteration failed", error=str(error))
