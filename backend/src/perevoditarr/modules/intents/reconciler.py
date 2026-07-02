"""Reconciler in Observe mode (P2-T4, FR-R2/R3/R4 foundations).

Re-observes the world from durable evidence only (§6.8): fresh Bazarr
metadata decides whether a backlog intent's target subtitle now exists, and
Bazarr history (action 6) annotates *how* it appeared. Nothing dispatched
exists in Phase 2, so Observe mode is total — the only transition this loop
performs is backlog → superseded. Phase 3 slots convergence/failure
classification for dispatched intents into `run_for_instance` alongside the
backlog pass.

Crash safety (FR-R4) is re-observation, never volatile state: the app runs
one full pass at startup before the periodic loop takes over.
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import msgspec
from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.locks import InstanceLockRegistry
from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances import (
    BazarrInstance,
    InstanceGateway,
    InstancesService,
)
from perevoditarr.modules.intents.collectors import (
    BazarrHistoryCollector,
    BazarrMetadataCollector,
)
from perevoditarr.modules.intents.evidence import (
    HistoryEvidence,
    NoChange,
    SubtitlePresence,
    Supersede,
    classify_backlog,
    history_evidence,
    subtitle_presence,
)
from perevoditarr.modules.intents.models import Intent
from perevoditarr.modules.intents.service import IntentsService
from perevoditarr.modules.intents.state_machine import BACKLOG_STATES, IntentState
from perevoditarr.modules.intents.trace import (
    EvidenceObserved,
    decode_trace,
    encode_trace,
)

_logger = get_logger()

RECONCILE_BATCH = 500


class ReconcileRunSummary(msgspec.Struct, kw_only=True):
    bazarr_instance_id: UUID
    examined: int = 0
    superseded_via_translation: int = 0
    superseded_other: int = 0
    unchanged: int = 0


def _aware(value: datetime) -> datetime:
    # SQLite round-trips may drop tzinfo; all stored datetimes are UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json(value: msgspec.Struct) -> dict[str, object]:
    return msgspec.json.decode(msgspec.json.encode(value), type=dict[str, object])


class ReconcilerService:
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        gateway: InstanceGateway,
        sse_bus: SseBus,
    ) -> None:
        self.session: AsyncSession = session
        self.gateway: InstanceGateway = gateway
        self.sse_bus: SseBus = sse_bus
        self.instances: InstancesService = InstancesService(session, secret_box)
        self.intents: IntentsService = IntentsService(session)

    async def run_for_instance(
        self, instance: BazarrInstance, *, actor: str = "reconciler"
    ) -> ReconcileRunSummary:
        client = self.gateway.bazarr(
            instance.url, self.instances.bazarr_api_key(instance)
        )
        metadata = BazarrMetadataCollector(client)
        history = BazarrHistoryCollector(client)
        summary = ReconcileRunSummary(bazarr_instance_id=instance.id)

        last_id: UUID | None = None
        while True:
            stmt = (
                select(Intent)
                .where(
                    Intent.bazarr_instance_id == instance.id,
                    Intent.state.in_(sorted(s.value for s in BACKLOG_STATES)),
                )
                .order_by(Intent.id)
                .limit(RECONCILE_BATCH)
            )
            if last_id is not None:
                stmt = stmt.where(Intent.id > last_id)
            rows = (await self.session.scalars(stmt)).all()
            if not rows:
                break
            last_id = rows[-1].id
            await self._reconcile_batch(rows, metadata, history, summary, actor)
            if len(rows) < RECONCILE_BATCH:
                break

        self.sse_bus.publish(
            "intents.reconciled",
            {
                "instanceId": str(instance.id),
                "examined": summary.examined,
                "supersededViaTranslation": summary.superseded_via_translation,
                "supersededOther": summary.superseded_other,
                "unchanged": summary.unchanged,
            },
        )
        return summary

    async def _reconcile_batch(
        self,
        rows: Sequence[Intent],
        metadata: BazarrMetadataCollector,
        history: BazarrHistoryCollector,
        summary: ReconcileRunSummary,
        actor: str,
    ) -> None:
        episode_series = sorted(
            {
                row.sonarr_series_id
                for row in rows
                if row.media_type == "episode" and row.sonarr_series_id is not None
            }
        )
        movie_ids = sorted(
            {row.external_media_id for row in rows if row.media_type == "movie"}
        )
        episode_subtitles = (
            await metadata.episode_subtitles(episode_series) if episode_series else {}
        )
        movie_subtitles = await metadata.movie_subtitles(movie_ids) if movie_ids else {}

        for row in rows:
            summary.examined += 1
            subtitles = (
                episode_subtitles.get(row.external_media_id, ())
                if row.media_type == "episode"
                else movie_subtitles.get(row.external_media_id, ())
            )
            presence = subtitle_presence(
                subtitles,
                language=row.target_language,
                forced=row.forced,
                hi=row.hi,
            )
            if not presence.file_backed:
                summary.unchanged += 1
                continue
            # History corroboration only for actual appearances: bounded by
            # supersessions per pass, not backlog size.
            evidence = await self._history_for(row, history)
            outcome = classify_backlog(presence, evidence)
            match outcome:
                case Supersede(via_translation=via_translation, detail=detail):
                    await self._supersede(
                        row, presence, evidence, detail=detail, actor=actor
                    )
                    if via_translation:
                        summary.superseded_via_translation += 1
                    else:
                        summary.superseded_other += 1
                case NoChange():
                    summary.unchanged += 1

    async def _history_for(
        self, row: Intent, history: BazarrHistoryCollector
    ) -> HistoryEvidence:
        items = (
            await history.episode_history(row.external_media_id)
            if row.media_type == "episode"
            else await history.movie_history(row.external_media_id)
        )
        return history_evidence(
            items,
            language=row.target_language,
            forced=row.forced,
            hi=row.hi,
            since=_aware(row.created_at),
        )

    async def _supersede(
        self,
        row: Intent,
        presence: SubtitlePresence,
        history: HistoryEvidence,
        *,
        detail: str,
        actor: str,
    ) -> None:
        steps = (
            *decode_trace(row.decision_trace),
            EvidenceObserved(kind="bazarr_metadata", detail=detail),
        )
        row.decision_trace = encode_trace(steps)
        _ = await self.intents.transition(
            row,
            IntentState.SUPERSEDED,
            actor=actor,
            reason=f"superseded: {detail}",
            evidence={
                "kind": "reconciliation",
                "metadata": _json(presence),
                "history": _json(history),
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )


async def run_reconciliation(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    *,
    instance_id: UUID | None = None,
    actor: str = "reconciler",
    locks: InstanceLockRegistry | None = None,
) -> None:
    """Run one reconciliation pass for one instance (event nudge) or all
    enabled instances (scheduled loop / startup re-observation). Per-instance
    failures — an unreachable Bazarr included — never cascade; the next pass
    simply re-observes (no in-place retries, §6.3). The app passes its shared
    lock registry so passes for the same instance never interleave."""
    registry = locks if locks is not None else InstanceLockRegistry()
    async with alchemy.get_session() as session:
        instances = InstancesService(session, secret_box)
        reconciler = ReconcilerService(session, secret_box, gateway, sse_bus)
        # Plain-data snapshot: a mid-pass rollback expires every ORM row
        # loaded so far, so neither the loop nor the log handler may touch
        # attributes of rows fetched before the failure.
        targets = [
            (row.id, row.name)
            for row in await instances.list_bazarr()
            if row.enabled and (instance_id is None or row.id == instance_id)
        ]
        for target_id, target_name in targets:
            try:
                async with registry.lock_for(target_id):
                    instance = await instances.get_bazarr(target_id)
                    _ = await reconciler.run_for_instance(instance, actor=actor)
            except Exception as error:
                # Roll back so a DB-level failure on this instance cannot
                # poison the session for the remaining instances in the pass.
                await session.rollback()
                _logger.warning(
                    "reconciliation run failed",
                    instance=target_name,
                    error=str(error),
                )


async def reconcile_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    sse_bus: SseBus,
    interval_seconds: int,
    locks: InstanceLockRegistry | None = None,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await run_reconciliation(alchemy, gateway, secret_box, sse_bus, locks=locks)
