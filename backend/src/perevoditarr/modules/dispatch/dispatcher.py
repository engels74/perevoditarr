"""Dispatcher (P3-T2, FR-Q1-Q3/Q6; §6.5, §7.2).

Turns eligible intents into Bazarr translate PATCHes under strict admission
control. Per pass, per instance (serialized by the instance lock registry —
ADR-0006):

1. Gate on explicit activation (safe-by-default) and the bounded dispatch
   window K, leaving headroom below Bazarr's `concurrent_jobs` (§7.2).
2. Backpressure: hold top-up when Bazarr's pending job queue is deep (§6.2).
3. For each eligible candidate in priority order, enforce the non-configurable
   §6.5 scheduling invariant (one in-flight per instance+series/movie+pair),
   consult the rails (caps/budget/pause/breaker/window), then run the
   pre-dispatch guard (FR-Q2): a fresh Bazarr read (target still wanted, source
   still present) plus "no matching active Lingarr request" — the checks that
   keep the §6.4 corruption trap unreachable.
4. Record `dispatched` with a convergence lease BEFORE sending the PATCH, so a
   crash between the two cannot double-dispatch (the lease expires and P3-T3
   re-verifies); then fire the single ecosystem write surface (§7.5).

Nothing here consumes telemetry (§7.3): admission is durable-evidence only.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import msgspec
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import PerevoditarrError
from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.dispatch.estimation import estimate_intent
from perevoditarr.modules.instances import (
    BazarrInstance,
    InstanceGateway,
    InstancesService,
)
from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.bazarr.schemas import SubtitleFile
from perevoditarr.modules.integrations.lingarr import TranslationRequestRecord
from perevoditarr.modules.intents import (
    BazarrMetadataCollector,
    Dispatched,
    Intent,
    IntentsService,
    IntentState,
    LingarrRequestCollector,
    decode_trace,
    encode_trace,
    lingarr_evidence_for_episode,
    lingarr_evidence_for_movie,
    subtitle_presence,
)
from perevoditarr.modules.intents.repository import backlog_stmt
from perevoditarr.modules.rails import RailBlocked, RailsService

_logger = get_logger()

# Upper bound on eligible rows one pass scans; the window fills long before this
# at any realistic K, and invariant-held candidates are cheap to skip.
CANDIDATE_SCAN = 500

type PairKey = tuple[str, int, str, str]
type MediaType = Literal["episode", "movie"]


class DispatchRunSummary(msgspec.Struct, kw_only=True):
    bazarr_instance_id: UUID
    dispatched: int = 0
    held_invariant: int = 0
    held_rail: int = 0
    guard_superseded: int = 0
    guard_active_lingarr: int = 0
    guard_source_missing: int = 0
    backpressure_held: bool = False
    window_full: bool = False
    inactive: bool = False
    lingarr_unverifiable: bool = False
    # The rail that stopped the pass, if any (pause | breaker | window | cap_* |
    # budget) — consumed by the cap-reached notification forwarder (P3-T5).
    rail_block: str | None = None


# Pre-dispatch guard outcomes (internal signals).


class _Dispatch(msgspec.Struct, frozen=True):
    source_path: str


class _Supersede(msgspec.Struct, frozen=True):
    detail: str


class _SkipActiveLingarr(msgspec.Struct, frozen=True):
    pass


class _SkipSourceMissing(msgspec.Struct, frozen=True):
    pass


type _GuardOutcome = _Dispatch | _Supersede | _SkipActiveLingarr | _SkipSourceMissing


def _media(row: Intent) -> MediaType:
    return "episode" if row.media_type == "episode" else "movie"


def _pair_key(row: Intent) -> PairKey:
    """§6.5 identity: series-level for episodes, movie-level for movies."""
    if row.media_type == "episode":
        # Ledger upsert guarantees sonarr_series_id for episodes; 0 is an
        # unreachable sentinel that keeps the key type total.
        return (
            "episode",
            row.sonarr_series_id or 0,
            row.source_language,
            row.target_language,
        )
    return ("movie", row.external_media_id, row.source_language, row.target_language)


def elect_source_path(
    subtitles: Sequence[SubtitleFile], source_language: str
) -> str | None:
    """Pick the source-language subtitle file to translate from, preferring the
    plain (non-forced, non-HI) track. Embedded tracks (no path) can't be sent
    to Bazarr's translate PATCH, so only file-backed subtitles qualify."""
    file_backed = [
        subtitle
        for subtitle in subtitles
        if subtitle.code2 == source_language and subtitle.path is not None
    ]
    if not file_backed:
        return None
    plain = [s for s in file_backed if not s.forced and not s.hi]
    chosen = plain[0] if plain else file_backed[0]
    return chosen.path


def headroom_window(k: int, concurrent_jobs: int | None) -> int:
    """Bounded window that never fills more than `concurrent_jobs - 1` of
    Bazarr's slots, so its syncs/searches keep making progress (§7.2)."""
    if concurrent_jobs is None:
        return k
    return max(1, min(k, concurrent_jobs - 1))


class DispatcherService:
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        gateway: InstanceGateway,
        sse_bus: SseBus,
        *,
        lease_seconds: int,
        backpressure_pending: int,
    ) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box
        self.gateway: InstanceGateway = gateway
        self.sse_bus: SseBus = sse_bus
        self.lease_seconds: int = lease_seconds
        self.backpressure_pending: int = backpressure_pending
        self.instances: InstancesService = InstancesService(session, secret_box)
        self.intents: IntentsService = IntentsService(session)
        self.rails: RailsService = RailsService(session, secret_box, gateway, sse_bus)

    async def run_for_instance(
        self, instance: BazarrInstance, *, now: datetime | None = None
    ) -> DispatchRunSummary:
        moment = now if now is not None else datetime.now(UTC)
        summary = DispatchRunSummary(bazarr_instance_id=instance.id)
        if not await self.rails.is_dispatch_active(instance.id):
            summary.inactive = True
            return summary

        client = self.gateway.bazarr(
            instance.url, self.instances.bazarr_api_key(instance)
        )
        concurrent_jobs = await self._concurrent_jobs(client)
        window = headroom_window(
            await self.rails.effective_window_k(instance.id), concurrent_jobs
        )
        available = window - await self.intents.count_in_flight(instance.id)
        if available <= 0:
            summary.window_full = True
            return summary
        if len(await client.jobs(status="pending")) >= self.backpressure_pending:
            summary.backpressure_held = True
            return summary

        lingarr_records = await self._lingarr_records(instance)
        if lingarr_records is None:
            summary.lingarr_unverifiable = True  # can't clear the §6.4 guard
            return summary

        pair_keys = {
            _pair_key(row) for row in await self.intents.in_flight_rows(instance.id)
        }
        metadata = BazarrMetadataCollector(client)
        rows = (
            await self.session.scalars(
                backlog_stmt(instance.id)
                .where(Intent.state == IntentState.ELIGIBLE.value)
                .limit(CANDIDATE_SCAN)
            )
        ).all()

        for row in rows:
            if summary.dispatched >= available:
                break
            key = _pair_key(row)
            if key in pair_keys:
                summary.held_invariant += 1
                continue
            estimate = estimate_intent(_media(row), None)
            verdict = await self.rails.evaluate(
                instance.id, candidate_characters=estimate.characters, now=moment
            )
            if isinstance(verdict, RailBlocked):
                # Rails are instance-wide (pause/breaker/window/caps/budget): once
                # blocked, no lower-priority candidate can pass this pass.
                summary.held_rail += 1
                summary.rail_block = verdict.rail
                break
            outcome = await self._guard(row, metadata, lingarr_records)
            match outcome:
                case _Supersede(detail=detail):
                    await self._supersede(row, detail, moment)
                    summary.guard_superseded += 1
                case _SkipActiveLingarr():
                    summary.guard_active_lingarr += 1
                case _SkipSourceMissing():
                    summary.guard_source_missing += 1
                case _Dispatch(source_path=source_path):
                    pair_keys.add(key)  # hold the pair for the rest of this pass
                    if await self._dispatch(client, instance, row, source_path, moment):
                        summary.dispatched += 1
                        if verdict.breaker_probe:
                            # Consume the half-open probe slot so the next
                            # candidate this pass evaluates against a half_open
                            # breaker and holds (§8.4: one concurrent probe).
                            # Gated on a real dispatch: a superseded/skipped
                            # candidate never sends the PATCH, and half_open has
                            # no time-based recovery, so marking it earlier would
                            # strand the breaker with no probe in flight.
                            await self.rails.mark_probe(instance.id, now=moment)
                    else:
                        # Bazarr rejected the PATCH: back off the whole pass.
                        break

        self.sse_bus.publish(
            "dispatch.pass",
            {
                "instanceId": str(instance.id),
                "dispatched": summary.dispatched,
                "heldInvariant": summary.held_invariant,
                "heldRail": summary.held_rail,
                "supersededByGuard": summary.guard_superseded,
            },
        )
        return summary

    # ------------------------------------------------------------ guard

    async def _guard(
        self,
        row: Intent,
        metadata: BazarrMetadataCollector,
        lingarr_records: Sequence[TranslationRequestRecord],
    ) -> _GuardOutcome:
        subtitles = await self._fresh_subtitles(row, metadata)
        presence = subtitle_presence(
            subtitles, language=row.target_language, forced=row.forced, hi=row.hi
        )
        if presence.file_backed:
            # Target appeared between discovery and now — no longer wanted (§6.8).
            return _Supersede(
                detail="target subtitle already present (no longer wanted)"
            )
        source_path = elect_source_path(subtitles, row.source_language)
        if source_path is None:
            return _SkipSourceMissing()
        if self._active_lingarr_match(row, lingarr_records):
            # An active Lingarr request at §6.5 granularity: dispatching now would
            # trip the §6.4 dedup trap. Hold and re-check next pass.
            return _SkipActiveLingarr()
        return _Dispatch(source_path=source_path)

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

    def _active_lingarr_match(
        self, row: Intent, records: Sequence[TranslationRequestRecord]
    ) -> bool:
        if row.media_type == "episode":
            evidence = lingarr_evidence_for_episode(
                records,
                display_title=row.display_title,
                source_language=row.source_language,
                target_language=row.target_language,
            )
        else:
            evidence = lingarr_evidence_for_movie(
                records,
                radarr_id=row.external_media_id,
                display_title=row.display_title,
                source_language=row.source_language,
                target_language=row.target_language,
            )
        return evidence.any_active

    # ------------------------------------------------------------ actions

    async def _dispatch(
        self,
        client: BazarrClient,
        instance: BazarrInstance,
        row: Intent,
        source_path: str,
        now: datetime,
    ) -> bool:
        """Record `dispatched` with a lease first (crash-safe: no double-dispatch
        window), then fire the translate PATCH. A PATCH failure re-classes the
        intent as a transient failure for P3-T3's retry pipeline."""
        lease = now + timedelta(seconds=self.lease_seconds)
        row.decision_trace = encode_trace(
            (*decode_trace(row.decision_trace), Dispatched())
        )
        _ = await self.intents.transition(
            row,
            IntentState.DISPATCHED,
            actor="dispatcher",
            reason="dispatched: translate PATCH sent to Bazarr",
            evidence={
                "kind": "dispatch",
                "source_language": row.source_language,
                "target_language": row.target_language,
                "dispatched_at": now.isoformat(),
            },
            lease_expires_at=lease,
        )
        try:
            await client.translate(
                language=row.target_language,
                subtitle_path=source_path,
                media_type=row.media_type,
                media_id=row.external_media_id,
                forced=row.forced,
                hi=row.hi,
            )
        except PerevoditarrError as error:
            _ = await self.intents.transition(
                row,
                IntentState.FAILED,
                actor="dispatcher",
                reason=f"dispatch failed at Bazarr: {error}",
                evidence={"kind": "dispatch_failed", "failure_class": "transient"},
            )
            _logger.warning(
                "translate PATCH failed",
                instance=instance.name,
                intent=str(row.id),
                error=str(error),
            )
            return False
        self.sse_bus.publish(
            "intents.dispatched",
            {
                "intentId": str(row.id),
                "instanceId": str(instance.id),
                "mediaType": row.media_type,
                "targetLanguage": row.target_language,
                "leaseExpiresAt": lease.isoformat(),
            },
        )
        return True

    async def _supersede(self, row: Intent, detail: str, now: datetime) -> None:
        _ = await self.intents.transition(
            row,
            IntentState.SUPERSEDED,
            actor="dispatcher",
            reason=f"superseded pre-dispatch: {detail}",
            evidence={"kind": "pre_dispatch_guard", "observed_at": now.isoformat()},
        )

    # ------------------------------------------------------------ upstream reads

    async def _concurrent_jobs(self, client: BazarrClient) -> int | None:
        settings = await client.system_settings()
        if settings.general is None:
            return None
        return settings.general.concurrent_jobs

    async def _lingarr_records(
        self, instance: BazarrInstance
    ) -> tuple[TranslationRequestRecord, ...] | None:
        """Recent Lingarr requests for the §6.4 guard. `None` signals "linked but
        unverifiable" (Lingarr unreachable) — the caller holds the pass rather
        than dispatch blind. No link ⇒ empty (the ledger invariant still guards
        Perevoditarr-originated traffic; the doctor flags the missing link)."""
        if instance.lingarr_instance_id is None:
            return ()
        lingarr = await self.instances.get_lingarr(instance.lingarr_instance_id)
        collector = LingarrRequestCollector(
            self.gateway.lingarr(lingarr.url, self.instances.lingarr_api_key(lingarr))
        )
        try:
            return await collector.recent_requests()
        except PerevoditarrError:
            return None
