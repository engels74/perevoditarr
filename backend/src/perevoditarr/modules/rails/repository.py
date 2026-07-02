"""Rail usage queries (P3-T1): volume-cap/budget usage from the audit trail.

Usage is *counted* from `intent_event` dispatched-transition rows in the
rolling window, never accumulated in a mutable counter — so it is restart-safe
by construction (re-derived from durable evidence, FR-R4) and correct across
retries (each re-dispatch is a fresh Bazarr translate PATCH = real provider
spend, so it rightly counts against caps). Character budget usage sums the
conservative per-media heuristic over dispatched-in-window intents (estimating
high per the PRD risk table); actuals-based reconciliation joins in P4.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.modules.dispatch.estimation import (
    HEURISTIC_EPISODE_CHARACTERS,
    HEURISTIC_MOVIE_CHARACTERS,
)
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.state_machine import IntentState

_DISPATCHED = IntentState.DISPATCHED.value


async def dispatch_count_since(
    session: AsyncSession,
    since: datetime,
    *,
    bazarr_instance_id: UUID | None = None,
) -> int:
    """Count Bazarr translate dispatches recorded on/after `since` (global, or
    for one instance)."""
    stmt = (
        select(func.count())
        .select_from(IntentEvent)
        .join(Intent, IntentEvent.intent_id == Intent.id)
        .where(IntentEvent.to_state == _DISPATCHED, IntentEvent.created_at >= since)
    )
    if bazarr_instance_id is not None:
        stmt = stmt.where(Intent.bazarr_instance_id == bazarr_instance_id)
    return (await session.execute(stmt)).scalar_one()


async def dispatch_characters_since(
    session: AsyncSession,
    since: datetime,
    *,
    bazarr_instance_id: UUID | None = None,
) -> int:
    """Sum the conservative character estimate over intents dispatched on/after
    `since`, grouped by media type."""
    stmt = (
        select(Intent.media_type, func.count())
        .select_from(IntentEvent)
        .join(Intent, IntentEvent.intent_id == Intent.id)
        .where(IntentEvent.to_state == _DISPATCHED, IntentEvent.created_at >= since)
        .group_by(Intent.media_type)
    )
    if bazarr_instance_id is not None:
        stmt = stmt.where(Intent.bazarr_instance_id == bazarr_instance_id)
    total = 0
    for media_type, count in (await session.execute(stmt)).tuples():
        per_item = (
            HEURISTIC_EPISODE_CHARACTERS
            if media_type == "episode"
            else HEURISTIC_MOVIE_CHARACTERS
        )
        total += per_item * count
    return total


async def dispatch_counts_by_window(
    session: AsyncSession,
    windows: Sequence[tuple[str, datetime]],
    *,
    bazarr_instance_id: UUID | None = None,
) -> dict[str, int]:
    """One count per named window start (hour/day/week); a small fixed number of
    cheap counting queries per evaluation."""
    return {
        name: await dispatch_count_since(
            session, since, bazarr_instance_id=bazarr_instance_id
        )
        for name, since in windows
    }
