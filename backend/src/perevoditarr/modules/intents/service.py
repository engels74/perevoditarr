"""Intent ledger service (P2-T2): idempotent upsert, evented transitions,
tuned reads.

The transition helper is the *only* way this module changes an intent's
state, and it always writes the paired `intent_event` in the same session —
state changes without audit rows are unrepresentable through the public API
(FR-R1/FR-V1). Transitions take explicit durable-evidence snapshots as plain
data; nothing here listens to telemetry (PRD §7.3).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

import msgspec
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from perevoditarr.core.errors import DomainValidationError, NotFoundError
from perevoditarr.core.schemas import Page
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.repository import (
    IntentRepository,
    backlog_stmt,
    history_stmt,
    in_flight_stmt,
    movie_pair_in_flight_stmt,
    series_pair_in_flight_stmt,
)
from perevoditarr.modules.intents.schemas import (
    IntentDetail,
    IntentEventRead,
    IntentRead,
)
from perevoditarr.modules.intents.state_machine import (
    IN_FLIGHT_STATES,
    TERMINAL_STATES,
    IntentState,
    assert_manual_transition,
    assert_transition,
)
from perevoditarr.modules.intents.trace import (
    TraceStep,
    decode_trace,
    encode_trace,
    render_human,
    render_step,
)

type IntentMediaType = Literal["episode", "movie"]


class IntentSeed(msgspec.Struct, kw_only=True, frozen=True):
    """Discovery's upsert input (P2-T3 calls in with these) — plain data."""

    bazarr_instance_id: UUID
    media_type: IntentMediaType
    external_media_id: int  # sonarr_episode_id | radarr_id
    sonarr_series_id: int | None = None
    season: int | None = None
    episode_number: int | None = None
    display_title: str
    source_language: str
    target_language: str
    forced: bool = False
    hi: bool = False
    priority: int = 0
    trace: tuple[TraceStep, ...] = ()


def intent_read(row: Intent) -> IntentRead:
    return IntentRead(
        id=row.id,
        bazarr_instance_id=row.bazarr_instance_id,
        media_type=row.media_type,
        external_media_id=row.external_media_id,
        sonarr_series_id=row.sonarr_series_id,
        season=row.season,
        episode_number=row.episode_number,
        display_title=row.display_title,
        source_language=row.source_language,
        target_language=row.target_language,
        forced=row.forced,
        hi=row.hi,
        state=row.state,
        lease_expires_at=row.lease_expires_at,
        priority=row.priority,
        bumped_at=row.bumped_at,
        trace_rendered=render_human(decode_trace(row.decision_trace)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def event_read(row: IntentEvent) -> IntentEventRead:
    return IntentEventRead(
        id=row.id,
        actor=row.actor,
        from_state=row.from_state,
        to_state=row.to_state,
        reason=row.reason,
        evidence=row.evidence,
        created_at=row.created_at,
    )


class IntentsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session
        self.intents: IntentRepository = IntentRepository(session=session)

    # ------------------------------------------------------------ writes

    async def upsert(
        self,
        seed: IntentSeed,
        *,
        actor: str = "discovery",
        existing_row: Intent | None = None,
        skip_lookup: bool = False,
        commit: bool = True,
    ) -> tuple[Intent, bool]:
        """Get-or-create by natural key. Re-discovery refreshes mutable fields
        (priority inputs, source election, trace) on non-terminal intents and
        never duplicates; terminal intents are returned untouched (whether a
        re-appearing want re-opens them is discovery's call, P2-T3).

        Discovery batch-loads existing rows once per batch and passes them via
        `existing_row` with `skip_lookup=True` (no per-item SELECT at 100k
        scale) and `commit=False` (one commit per batch). Direct callers keep
        the lookup-and-commit default."""
        if seed.media_type == "episode" and seed.sonarr_series_id is None:
            raise DomainValidationError("episode intents require sonarr_series_id")
        row = existing_row
        if row is None and not skip_lookup:
            row = (
                await self.session.scalars(
                    select(Intent).where(
                        Intent.bazarr_instance_id == seed.bazarr_instance_id,
                        Intent.media_type == seed.media_type,
                        Intent.external_media_id == seed.external_media_id,
                        Intent.target_language == seed.target_language,
                        Intent.forced == seed.forced,
                        Intent.hi == seed.hi,
                    )
                )
            ).first()
        if row is None:
            row = Intent(
                bazarr_instance_id=seed.bazarr_instance_id,
                media_type=seed.media_type,
                external_media_id=seed.external_media_id,
                sonarr_series_id=seed.sonarr_series_id,
                season=seed.season,
                episode_number=seed.episode_number,
                display_title=seed.display_title,
                source_language=seed.source_language,
                target_language=seed.target_language,
                forced=seed.forced,
                hi=seed.hi,
                state=IntentState.DISCOVERED.value,
                priority=seed.priority,
                decision_trace=encode_trace(seed.trace) if seed.trace else None,
            )
            self.session.add(row)
            await self.session.flush()  # id needed for the creation event
            self.session.add(
                IntentEvent(
                    intent_id=row.id,
                    actor=actor,
                    from_state=None,
                    to_state=IntentState.DISCOVERED.value,
                    reason="intent discovered",
                    evidence=None,
                )
            )
            if commit:
                await self.session.commit()
            return row, True
        if IntentState(row.state) not in TERMINAL_STATES:
            row.sonarr_series_id = seed.sonarr_series_id
            row.season = seed.season
            row.episode_number = seed.episode_number
            row.display_title = seed.display_title
            row.source_language = seed.source_language
            row.priority = seed.priority
            if seed.trace:
                row.decision_trace = encode_trace(seed.trace)
            if commit:
                await self.session.commit()
        return row, False

    async def transition(
        self,
        intent: Intent,
        to_state: IntentState,
        *,
        actor: str,
        reason: str,
        evidence: dict[str, object] | None = None,
        lease_expires_at: datetime | None = None,
        commit: bool = True,
    ) -> Intent:
        """The single state-mutation path: validates against the transition
        table and writes the audit event atomically with the state change.
        `commit=False` lets discovery batch several transitions into one
        commit; the event still rides the same session/transaction."""
        from_state = IntentState(intent.state)
        assert_transition(from_state, to_state)
        intent.state = to_state.value
        if lease_expires_at is not None:
            intent.lease_expires_at = lease_expires_at
        if to_state in TERMINAL_STATES:
            intent.lease_expires_at = None
        self.session.add(
            IntentEvent(
                intent_id=intent.id,
                actor=actor,
                from_state=from_state.value,
                to_state=to_state.value,
                reason=reason,
                evidence=evidence,
            )
        )
        if commit:
            await self.session.commit()
        return intent

    async def manual_transition(
        self,
        intent: Intent,
        to_state: IntentState,
        *,
        actor: str,
        reason: str,
        commit: bool = True,
    ) -> Intent:
        """Operator-driven quarantine actions (FR-R6): retry (→ eligible) or
        release/exclude (→ superseded). Validated against MANUAL_TRANSITIONS so
        automated processes can never take these edges."""
        from_state = IntentState(intent.state)
        assert_manual_transition(from_state, to_state)
        intent.state = to_state.value
        if to_state in TERMINAL_STATES:
            intent.lease_expires_at = None
        self.session.add(
            IntentEvent(
                intent_id=intent.id,
                actor=actor,
                from_state=from_state.value,
                to_state=to_state.value,
                reason=reason,
                evidence=None,
            )
        )
        if commit:
            await self.session.commit()
        return intent

    async def count_dispatches(self, intent_id: UUID) -> int:
        """How many times this intent has been dispatched (event-derived) — the
        attempt count the retry/quarantine policy keys on (restart-safe)."""
        stmt = (
            select(func.count())
            .select_from(IntentEvent)
            .where(
                IntentEvent.intent_id == intent_id,
                IntentEvent.to_state == IntentState.DISPATCHED.value,
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    # ------------------------------------------------------------ reads

    async def get(self, intent_id: UUID) -> Intent:
        row = await self.intents.get_one_or_none(id=intent_id)
        if row is None:
            raise NotFoundError(f"intent {intent_id} not found")
        return row

    async def detail(self, intent_id: UUID) -> IntentDetail:
        row = (
            await self.session.scalars(
                select(Intent)
                .where(Intent.id == intent_id)
                .options(selectinload(Intent.events))
            )
        ).first()
        if row is None:
            raise NotFoundError(f"intent {intent_id} not found")
        steps = decode_trace(row.decision_trace)
        return IntentDetail(
            intent=intent_read(row),
            trace_steps=[render_step(step) for step in steps],
            events=[event_read(event) for event in row.events],
        )

    async def backlog(
        self,
        *,
        bazarr_instance_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[IntentRead]:
        return await self._page(backlog_stmt(bazarr_instance_id), limit, offset)

    async def in_flight(
        self,
        *,
        bazarr_instance_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[IntentRead]:
        return await self._page(in_flight_stmt(bazarr_instance_id), limit, offset)

    async def history(
        self,
        *,
        states: Sequence[IntentState] | None = None,
        bazarr_instance_id: UUID | None = None,
        media_type: IntentMediaType | None = None,
        target_language: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[IntentRead]:
        stmt = history_stmt(
            states=states,
            bazarr_instance_id=bazarr_instance_id,
            media_type=media_type,
            target_language=target_language,
            created_after=created_after,
            created_before=created_before,
        )
        return await self._page(stmt, limit, offset)

    async def count_in_flight(self, bazarr_instance_id: UUID) -> int:
        """Live dispatched-intent count for one instance (dispatch-window fill)."""
        stmt = (
            select(func.count())
            .select_from(Intent)
            .where(
                Intent.bazarr_instance_id == bazarr_instance_id,
                Intent.state.in_(sorted(s.value for s in IN_FLIGHT_STATES)),
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def in_flight_rows(self, bazarr_instance_id: UUID) -> Sequence[Intent]:
        """Raw dispatched intents for one instance — the dispatcher builds the
        §6.5 in-flight pair index from these."""
        return (
            await self.session.scalars(
                select(Intent).where(
                    Intent.bazarr_instance_id == bazarr_instance_id,
                    Intent.state.in_(sorted(s.value for s in IN_FLIGHT_STATES)),
                )
            )
        ).all()

    async def has_in_flight_series_pair(
        self,
        bazarr_instance_id: UUID,
        sonarr_series_id: int,
        source_language: str,
        target_language: str,
    ) -> bool:
        """§6.5 invariant probe: any dispatched episode of this show on this
        source→target pair?"""
        stmt = series_pair_in_flight_stmt(
            bazarr_instance_id, sonarr_series_id, source_language, target_language
        )
        return (await self.session.scalars(stmt.limit(1))).first() is not None

    async def has_in_flight_movie_pair(
        self,
        bazarr_instance_id: UUID,
        radarr_id: int,
        source_language: str,
        target_language: str,
    ) -> bool:
        stmt = movie_pair_in_flight_stmt(
            bazarr_instance_id, radarr_id, source_language, target_language
        )
        return (await self.session.scalars(stmt.limit(1))).first() is not None

    async def _page(
        self, stmt: Select[tuple[Intent]], limit: int, offset: int
    ) -> Page[IntentRead]:
        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.order_by(None).subquery())
            )
        ).scalar_one()
        rows = (await self.session.scalars(stmt.limit(limit).offset(offset))).all()
        return Page(
            items=[intent_read(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
