"""Intent ledger repositories and tuned query builders (P2-T2).

The statement builders encode the ledger's hot paths: backlog by priority
(manual bumps first, FR-Q4), in-flight by instance, the §6.5
scheduling-invariant pair lookups, and history filtering. Services execute
them; nothing here commits.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from sqlalchemy import Select, select

from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.state_machine import (
    BACKLOG_STATES,
    IN_FLIGHT_STATES,
    IntentState,
)


class IntentRepository(SQLAlchemyAsyncRepository[Intent]):
    model_type: type[Intent] = Intent


class IntentEventRepository(SQLAlchemyAsyncRepository[IntentEvent]):
    model_type: type[IntentEvent] = IntentEvent


def _states(states: Sequence[IntentState]) -> list[str]:
    return [state.value for state in states]


def backlog_stmt(bazarr_instance_id: UUID | None = None) -> Select[tuple[Intent]]:
    """Backlog ordering: bumped intents first (newest bump wins), then score,
    then age, with the id as a total-order tiebreak — same-second creations
    must page and plan deterministically (P2-T5). `bumped_at IS NULL ASC` is
    portable across SQLite/Postgres."""
    stmt = (
        select(Intent)
        .where(Intent.state.in_(_states(sorted(BACKLOG_STATES))))
        .order_by(
            Intent.bumped_at.is_(None),
            Intent.bumped_at.desc(),
            Intent.priority.desc(),
            Intent.created_at.asc(),
            Intent.id.asc(),
        )
    )
    if bazarr_instance_id is not None:
        stmt = stmt.where(Intent.bazarr_instance_id == bazarr_instance_id)
    return stmt


def in_flight_stmt(bazarr_instance_id: UUID | None = None) -> Select[tuple[Intent]]:
    stmt = (
        select(Intent)
        .where(Intent.state.in_(_states(sorted(IN_FLIGHT_STATES))))
        .order_by(Intent.lease_expires_at.asc(), Intent.created_at.asc())
    )
    if bazarr_instance_id is not None:
        stmt = stmt.where(Intent.bazarr_instance_id == bazarr_instance_id)
    return stmt


def series_pair_in_flight_stmt(
    bazarr_instance_id: UUID,
    sonarr_series_id: int,
    source_language: str,
    target_language: str,
) -> Select[tuple[UUID]]:
    """§6.5: episodes of one show translating the same pair are
    indistinguishable inside Lingarr — at most one may be in flight."""
    return select(Intent.id).where(
        Intent.bazarr_instance_id == bazarr_instance_id,
        Intent.sonarr_series_id == sonarr_series_id,
        Intent.source_language == source_language,
        Intent.target_language == target_language,
        Intent.state.in_(_states(sorted(IN_FLIGHT_STATES))),
    )


def movie_pair_in_flight_stmt(
    bazarr_instance_id: UUID,
    radarr_id: int,
    source_language: str,
    target_language: str,
) -> Select[tuple[UUID]]:
    return select(Intent.id).where(
        Intent.bazarr_instance_id == bazarr_instance_id,
        Intent.media_type == "movie",
        Intent.external_media_id == radarr_id,
        Intent.source_language == source_language,
        Intent.target_language == target_language,
        Intent.state.in_(_states(sorted(IN_FLIGHT_STATES))),
    )


def history_stmt(
    *,
    states: Sequence[IntentState] | None = None,
    bazarr_instance_id: UUID | None = None,
    media_type: str | None = None,
    target_language: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> Select[tuple[Intent]]:
    stmt = select(Intent).order_by(Intent.created_at.desc(), Intent.id)
    if states:
        stmt = stmt.where(Intent.state.in_(_states(states)))
    if bazarr_instance_id is not None:
        stmt = stmt.where(Intent.bazarr_instance_id == bazarr_instance_id)
    if media_type is not None:
        stmt = stmt.where(Intent.media_type == media_type)
    if target_language is not None:
        stmt = stmt.where(Intent.target_language == target_language)
    if created_after is not None:
        stmt = stmt.where(Intent.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(Intent.created_at <= created_before)
    return stmt
