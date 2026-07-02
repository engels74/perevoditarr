"""Verification & failure handling (P3-T3, FR-R2-R5, §7.4).

The dispatched-intent counterpart to the dispatcher, and the reason it lives in
the dispatch (orchestration) layer rather than the reconciler: it feeds the
rails circuit breaker, and rails already depends on the intent ledger — housing
this in intents would cycle. Per pass, per instance (serialized by the same lock
registry), for every dispatched intent it gathers durable evidence only (§6.8):

* subtitle present + our action-6 within the lease window ⇒ `converged`;
* subtitle present without our action-6 ⇒ `superseded` (appeared by other means;
  kept out of budget/stats, FR-V3);
* a Failed/Cancelled Lingarr request ⇒ immediate classified failure (fast-path);
* lease expiry without evidence ⇒ verify then classify (§7.4 taxonomy).

Failures route to retry-eligible (intent-level exponential backoff), needs-
attention (environmental, no retry burn), the breaker (provider/systemic), or
quarantine (poison after the attempt ceiling). A second pass promotes
retry-eligible intents back to eligible once their backoff elapses. Crash
safety (FR-R4) is inherent: everything is re-derived from durable state, so a
restart retroactively converges/fails in-flight intents with no volatile state
to lose.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import msgspec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import PerevoditarrError
from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances import (
    BazarrInstance,
    InstanceGateway,
    InstancesService,
)
from perevoditarr.modules.integrations.bazarr.schemas import SubtitleFile
from perevoditarr.modules.integrations.lingarr import TranslationRequestRecord
from perevoditarr.modules.intents import (
    BazarrHistoryCollector,
    BazarrMetadataCollector,
    Converged,
    EvidenceObserved,
    HistoryEvidence,
    Intent,
    IntentsService,
    IntentState,
    LingarrFailure,
    LingarrRequestCollector,
    NeedsAttention,
    Quarantine,
    RetryScheduled,
    StillWaiting,
    SupersededOther,
    classify_dispatched,
    decode_trace,
    encode_trace,
    history_evidence,
    is_environmental_message,
    matching_lingarr_records_episode,
    matching_lingarr_records_movie,
    retry_backoff_seconds,
    subtitle_presence,
)
from perevoditarr.modules.rails import BreakerTransition, RailsService

_logger = get_logger()

_LINGARR_FAILURE_STATUSES = frozenset({"Failed", "Cancelled"})


class VerifyRunSummary(msgspec.Struct, kw_only=True):
    bazarr_instance_id: UUID
    examined: int = 0
    converged: int = 0
    superseded: int = 0
    needs_attention: int = 0
    retry_scheduled: int = 0
    quarantined: int = 0
    still_waiting: int = 0
    retries_promoted: int = 0
    breaker_transitions: list[BreakerTransition] = msgspec.field(default_factory=list)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class VerificationService:
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        gateway: InstanceGateway,
        sse_bus: SseBus,
        *,
        max_attempts: int,
        retry_base_seconds: int,
        retry_cap_seconds: int,
    ) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box
        self.gateway: InstanceGateway = gateway
        self.sse_bus: SseBus = sse_bus
        self.max_attempts: int = max_attempts
        self.retry_base_seconds: int = retry_base_seconds
        self.retry_cap_seconds: int = retry_cap_seconds
        self.instances: InstancesService = InstancesService(session, secret_box)
        self.intents: IntentsService = IntentsService(session)
        self.rails: RailsService = RailsService(session, secret_box, gateway, sse_bus)

    async def run_for_instance(
        self, instance: BazarrInstance, *, now: datetime | None = None
    ) -> VerifyRunSummary:
        moment = now if now is not None else datetime.now(UTC)
        summary = VerifyRunSummary(bazarr_instance_id=instance.id)
        client = self.gateway.bazarr(
            instance.url, self.instances.bazarr_api_key(instance)
        )
        metadata = BazarrMetadataCollector(client)
        history = BazarrHistoryCollector(client)
        lingarr_records = await self._lingarr_records(instance)

        for row in await self.intents.in_flight_rows(instance.id):
            summary.examined += 1
            await self._verify_one(
                instance, row, metadata, history, lingarr_records, summary, moment
            )

        await self._promote_retries(instance.id, summary, moment)
        self.sse_bus.publish(
            "intents.verified",
            {
                "instanceId": str(instance.id),
                "converged": summary.converged,
                "superseded": summary.superseded,
                "retryScheduled": summary.retry_scheduled,
                "needsAttention": summary.needs_attention,
                "quarantined": summary.quarantined,
                "retriesPromoted": summary.retries_promoted,
            },
        )
        return summary

    async def _verify_one(
        self,
        instance: BazarrInstance,
        row: Intent,
        metadata: BazarrMetadataCollector,
        history: BazarrHistoryCollector,
        lingarr_records: tuple[TranslationRequestRecord, ...],
        summary: VerifyRunSummary,
        now: datetime,
    ) -> None:
        subtitles = await self._fresh_subtitles(row, metadata)
        presence = subtitle_presence(
            subtitles, language=row.target_language, forced=row.forced, hi=row.hi
        )
        translated_in_window = False
        if presence.file_backed:
            translated_in_window = (await self._history(row, history)).translated
        lease_expired = row.lease_expires_at is not None and now >= _aware(
            row.lease_expires_at
        )
        attempts = await self.intents.count_dispatches(row.id)
        outcome = classify_dispatched(
            target_present=presence.file_backed,
            translated_in_window=translated_in_window,
            lingarr_failure=self._lingarr_failure(row, lingarr_records),
            lease_expired=lease_expired,
            attempts=attempts,
            max_attempts=self.max_attempts,
        )
        match outcome:
            case Converged():
                await self._converge(row, now)
                summary.converged += 1
                await self._feed_breaker(instance.id, success=True, summary=summary)
            case SupersededOther(detail=detail):
                await self._supersede(row, detail, now)
                summary.superseded += 1
            case NeedsAttention(reason=reason):
                await self._fail(row, reason, failure_class="environmental")
                summary.needs_attention += 1
            case RetryScheduled(reason=reason, failure_class=failure_class):
                await self._fail(row, reason, failure_class=failure_class)
                _ = await self.intents.transition(
                    row,
                    IntentState.RETRY_ELIGIBLE,
                    actor="verification",
                    reason=f"retry scheduled (attempt {attempts + 1})",
                )
                summary.retry_scheduled += 1
                if failure_class == "provider":
                    await self._feed_breaker(
                        instance.id, success=False, summary=summary
                    )
            case Quarantine(reason=reason, failure_class=failure_class):
                await self._fail(row, reason, failure_class=failure_class)
                _ = await self.intents.transition(
                    row,
                    IntentState.QUARANTINED,
                    actor="verification",
                    reason=f"quarantined: {reason}",
                )
                summary.quarantined += 1
                if failure_class == "provider":
                    await self._feed_breaker(
                        instance.id, success=False, summary=summary
                    )
            case StillWaiting():
                summary.still_waiting += 1

    # ------------------------------------------------------------ transitions

    async def _converge(self, row: Intent, now: datetime) -> None:
        row.decision_trace = encode_trace(
            (
                *decode_trace(row.decision_trace),
                EvidenceObserved(
                    kind="bazarr_history",
                    detail="converged: subtitle present + translation action-6 in lease",
                ),
            )
        )
        _ = await self.intents.transition(
            row,
            IntentState.CONVERGED,
            actor="verification",
            reason="converged: translated subtitle present within lease",
            evidence={"kind": "convergence", "observed_at": now.isoformat()},
        )

    async def _supersede(self, row: Intent, detail: str, now: datetime) -> None:
        _ = await self.intents.transition(
            row,
            IntentState.SUPERSEDED,
            actor="verification",
            reason=f"superseded: {detail}",
            evidence={"kind": "supersession", "observed_at": now.isoformat()},
        )

    async def _fail(self, row: Intent, reason: str, *, failure_class: str) -> None:
        _ = await self.intents.transition(
            row,
            IntentState.FAILED,
            actor="verification",
            reason=reason,
            evidence={"kind": "failure", "failure_class": failure_class},
        )

    async def _feed_breaker(
        self, instance_id: UUID, *, success: bool, summary: VerifyRunSummary
    ) -> None:
        transition = await self.rails.record_dispatch_result(
            instance_id, success=success
        )
        if transition.from_state != transition.to_state:
            summary.breaker_transitions.append(transition)

    async def _promote_retries(
        self, instance_id: UUID, summary: VerifyRunSummary, now: datetime
    ) -> None:
        rows = (
            await self.session.scalars(
                select(Intent).where(
                    Intent.bazarr_instance_id == instance_id,
                    Intent.state == IntentState.RETRY_ELIGIBLE.value,
                )
            )
        ).all()
        for row in rows:
            attempts = await self.intents.count_dispatches(row.id)
            backoff = retry_backoff_seconds(
                attempts, self.retry_base_seconds, cap_seconds=self.retry_cap_seconds
            )
            since = _aware(row.updated_at)
            if now - since < timedelta(seconds=backoff):
                continue
            _ = await self.intents.transition(
                row,
                IntentState.ELIGIBLE,
                actor="verification",
                reason=f"retry backoff elapsed ({backoff}s); re-eligible",
            )
            summary.retries_promoted += 1

    # ------------------------------------------------------------ evidence

    async def _fresh_subtitles(
        self, row: Intent, metadata: BazarrMetadataCollector
    ) -> tuple[SubtitleFile, ...]:
        if row.media_type == "episode":
            series_id = row.sonarr_series_id
            if series_id is None:
                return ()
            by_episode = await metadata.episode_subtitles([series_id])
            return by_episode.get(row.external_media_id, ())
        by_movie = await metadata.movie_subtitles([row.external_media_id])
        return by_movie.get(row.external_media_id, ())

    async def _history(
        self, row: Intent, history: BazarrHistoryCollector
    ) -> HistoryEvidence:
        items = (
            await history.episode_history(row.external_media_id)
            if row.media_type == "episode"
            else await history.movie_history(row.external_media_id)
        )
        # `updated_at` is stamped when the intent last became `dispatched`, so it
        # is the start of the lease window: an action-6 after it is *our* work.
        return history_evidence(
            items,
            language=row.target_language,
            forced=row.forced,
            hi=row.hi,
            since=_aware(row.updated_at),
        )

    def _lingarr_failure(
        self, row: Intent, records: tuple[TranslationRequestRecord, ...]
    ) -> LingarrFailure | None:
        matched = (
            matching_lingarr_records_episode(
                records,
                display_title=row.display_title,
                source_language=row.source_language,
                target_language=row.target_language,
            )
            if row.media_type == "episode"
            else matching_lingarr_records_movie(
                records,
                radarr_id=row.external_media_id,
                display_title=row.display_title,
                source_language=row.source_language,
                target_language=row.target_language,
            )
        )
        for record in matched:
            status = record.status or ""
            if status in _LINGARR_FAILURE_STATUSES:
                return LingarrFailure(
                    status=status,
                    environmental=is_environmental_message(record.error_message),
                )
        return None

    async def _lingarr_records(
        self, instance: BazarrInstance
    ) -> tuple[TranslationRequestRecord, ...]:
        """Recent Lingarr requests for the failure fast-path. Unlike the
        dispatcher's guard, verification degrades gracefully on an unreachable
        Lingarr (empty ⇒ classify from Bazarr evidence alone; the next pass
        re-observes) — it never dispatches, so there is no §6.4 risk to guard."""
        if instance.lingarr_instance_id is None:
            return ()
        lingarr = await self.instances.get_lingarr(instance.lingarr_instance_id)
        collector = LingarrRequestCollector(
            self.gateway.lingarr(lingarr.url, self.instances.lingarr_api_key(lingarr))
        )
        try:
            return await collector.recent_requests()
        except PerevoditarrError:
            return ()
