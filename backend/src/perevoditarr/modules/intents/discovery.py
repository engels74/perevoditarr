"""Discovery engine (P2-T3, FR-P1): wanted mirror joined with policy → ledger.

Batched, keyset-paged reads (no per-item queries at 100k scale); the pure
rule layer (`discovery_rules`) makes every decision; only `Planned` outcomes
are upserted. Withdrawal supersedes backlog intents whose want vanished — and
only when a completed wanted pass exists, so a never-synced or crashed pass
can never fabricate withdrawals (FR-R4 spirit). Nothing here dispatches or
writes toward the ecosystem: Observe mode is total in Phase 2.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, time
from typing import Literal
from uuid import UUID

import msgspec
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances import InstanceGateway
from perevoditarr.modules.intents.discovery_rules import (
    CandidateDecision,
    ExistingSubtitle,
    NotPlanned,
    Planned,
    WantedCandidate,
    explain_candidate,
    recency_anchor,
)
from perevoditarr.modules.intents.models import Intent
from perevoditarr.modules.intents.service import IntentSeed, IntentsService
from perevoditarr.modules.intents.state_machine import TERMINAL_STATES, IntentState
from perevoditarr.modules.intents.trace import (
    PriorityAssigned,
    TraceStep,
    Withdrawn,
    decode_trace,
    encode_trace,
)
from perevoditarr.modules.mirror import (
    Episode,
    Movie,
    Series,
    Subtitle,
    SyncRun,
    WantedSubtitle,
)
from perevoditarr.modules.policy import (
    CascadeInput,
    EffectivePolicy,
    EpisodeRef,
    ExclusionRule,
    MovieRef,
    PolicyService,
    ScoreBreakdown,
    ScoreFacts,
    resolve_effective_policy,
    score_intent,
)

_logger = get_logger()

WANTED_BATCH = 500
WITHDRAW_BATCH = 500

# Withdrawal scope: backlog + failed. Dispatched intents are the reconciler's
# to supersede (P2-T4) — wanted disappearance there is convergence evidence.
_WITHDRAWABLE_STATES = (
    IntentState.DISCOVERED.value,
    IntentState.ELIGIBLE.value,
    IntentState.RETRY_ELIGIBLE.value,
    IntentState.FAILED.value,
)


class DiscoveryRunSummary(msgspec.Struct, kw_only=True):
    bazarr_instance_id: UUID
    evaluated: int = 0
    planned: int = 0
    created: int = 0
    refreshed: int = 0
    advanced_to_eligible: int = 0
    withdrawn: int = 0
    reappeared_terminal: int = 0
    not_planned: dict[str, int] = msgspec.field(default_factory=dict)


def _aware(value: datetime) -> datetime:
    # SQLite round-trips may drop tzinfo; all stored datetimes are UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _tags(raw: list[str] | None) -> tuple[str, ...]:
    return tuple(raw) if raw else ()


def _episode_candidate(
    instance_id: UUID,
    wanted: WantedSubtitle,
    episode: Episode,
    series: Series,
    existing: tuple[ExistingSubtitle, ...],
) -> WantedCandidate:
    item = EpisodeRef(
        bazarr_instance_id=instance_id,
        sonarr_series_id=episode.sonarr_series_id,
        sonarr_episode_id=episode.sonarr_episode_id,
        tags=_tags(series.tags),
        # Both levels gate: an unmonitored series is unmonitored for policy
        # purposes even if the episode flag lags.
        monitored=episode.monitored and series.monitored,
    )
    air_date = (
        datetime.combine(episode.air_date, time.min, tzinfo=UTC)
        if episode.air_date is not None
        else None
    )
    return WantedCandidate(
        item=item,
        display_title=series.title,
        language=wanted.language,
        forced=wanted.forced,
        hi=wanted.hi,
        season=episode.season,
        episode_number=episode.episode,
        wanted_first_seen_at=_aware(wanted.first_seen_at),
        air_date=air_date,
        series_ended=series.ended,
        existing_subtitles=existing,
    )


def _movie_candidate(
    instance_id: UUID,
    wanted: WantedSubtitle,
    movie: Movie,
    existing: tuple[ExistingSubtitle, ...],
) -> WantedCandidate:
    item = MovieRef(
        bazarr_instance_id=instance_id,
        radarr_id=movie.radarr_id,
        tags=_tags(movie.tags),
        monitored=movie.monitored,
    )
    return WantedCandidate(
        item=item,
        display_title=movie.title,
        language=wanted.language,
        forced=wanted.forced,
        hi=wanted.hi,
        wanted_first_seen_at=_aware(wanted.first_seen_at),
        existing_subtitles=existing,
    )


class DiscoveryService:
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        gateway: InstanceGateway,
        sse_bus: SseBus,
    ) -> None:
        self.session: AsyncSession = session
        self.sse_bus: SseBus = sse_bus
        self.policy: PolicyService = PolicyService(session, secret_box, gateway)
        self.intents: IntentsService = IntentsService(session)

    async def run_for_instance(
        self, instance_id: UUID, *, now: datetime | None = None
    ) -> DiscoveryRunSummary:
        moment = now if now is not None else datetime.now(UTC)
        cascade = await self.policy.cascade_input(instance_id)
        exclusions = await self.policy.exclusion_rules(instance_id)
        summary = DiscoveryRunSummary(bazarr_instance_id=instance_id)

        await self._discover_episodes(instance_id, cascade, exclusions, moment, summary)
        await self._discover_movies(instance_id, cascade, exclusions, moment, summary)
        await self._withdraw_vanished(instance_id, summary)

        self.sse_bus.publish(
            "intents.discovered",
            {
                "instanceId": str(instance_id),
                "evaluated": summary.evaluated,
                "planned": summary.planned,
                "created": summary.created,
                "refreshed": summary.refreshed,
                "advancedToEligible": summary.advanced_to_eligible,
                "withdrawn": summary.withdrawn,
                "reappearedTerminal": summary.reappeared_terminal,
                "notPlanned": summary.not_planned,
            },
        )
        return summary

    async def explain_wanted(
        self,
        instance_id: UUID,
        *,
        media_type: Literal["episode", "movie"],
        external_media_id: int,
        language: str,
        forced: bool,
        hi: bool,
        now: datetime | None = None,
    ) -> CandidateDecision | None:
        """Run one wanted item through the exact discovery rule chain.

        Returns None when Bazarr does not currently want that subtitle — a
        distinct outcome the explainer surfaces as "not wanted" (FR-U4/T6).
        """
        moment = now if now is not None else datetime.now(UTC)
        candidate = await self._load_candidate(
            instance_id,
            media_type=media_type,
            external_media_id=external_media_id,
            language=language,
            forced=forced,
            hi=hi,
        )
        if candidate is None:
            return None
        cascade = await self.policy.cascade_input(instance_id)
        exclusions = await self.policy.exclusion_rules(instance_id)
        policy = _policy_for(candidate, cascade)
        return explain_candidate(candidate, policy, exclusions, now=moment)

    async def _load_candidate(
        self,
        instance_id: UUID,
        *,
        media_type: Literal["episode", "movie"],
        external_media_id: int,
        language: str,
        forced: bool,
        hi: bool,
    ) -> WantedCandidate | None:
        if media_type == "episode":
            episode_stmt = (
                select(WantedSubtitle, Episode, Series)
                .join(Episode, WantedSubtitle.episode_id == Episode.id)
                .join(Series, Episode.series_id == Series.id)
                .where(
                    WantedSubtitle.bazarr_instance_id == instance_id,
                    Episode.sonarr_episode_id == external_media_id,
                    WantedSubtitle.language == language,
                    WantedSubtitle.forced == forced,
                    WantedSubtitle.hi == hi,
                )
            )
            episode_row = (await self.session.execute(episode_stmt)).tuples().first()
            if episode_row is None:
                return None
            wanted, episode, series = episode_row
            subtitles = await self._subtitles_by_episode([episode.id])
            return _episode_candidate(
                instance_id, wanted, episode, series, subtitles.get(episode.id, ())
            )
        movie_stmt = (
            select(WantedSubtitle, Movie)
            .join(Movie, WantedSubtitle.movie_id == Movie.id)
            .where(
                WantedSubtitle.bazarr_instance_id == instance_id,
                Movie.radarr_id == external_media_id,
                WantedSubtitle.language == language,
                WantedSubtitle.forced == forced,
                WantedSubtitle.hi == hi,
            )
        )
        movie_row = (await self.session.execute(movie_stmt)).tuples().first()
        if movie_row is None:
            return None
        wanted, movie = movie_row
        subtitles = await self._subtitles_by_movie([movie.id])
        return _movie_candidate(instance_id, wanted, movie, subtitles.get(movie.id, ()))

    # ------------------------------------------------------------ candidates

    async def _discover_episodes(
        self,
        instance_id: UUID,
        cascade: CascadeInput,
        exclusions: tuple[ExclusionRule, ...],
        now: datetime,
        summary: DiscoveryRunSummary,
    ) -> None:
        last_id: UUID | None = None
        while True:
            stmt = (
                select(WantedSubtitle, Episode, Series)
                .join(Episode, WantedSubtitle.episode_id == Episode.id)
                .join(Series, Episode.series_id == Series.id)
                .where(
                    WantedSubtitle.bazarr_instance_id == instance_id,
                    WantedSubtitle.episode_id.is_not(None),
                )
                .order_by(WantedSubtitle.id)
                .limit(WANTED_BATCH)
            )
            if last_id is not None:
                stmt = stmt.where(WantedSubtitle.id > last_id)
            rows = (await self.session.execute(stmt)).tuples().all()
            if not rows:
                return
            last_id = rows[-1][0].id
            subtitles = await self._subtitles_by_episode(
                [episode.id for _, episode, _ in rows]
            )
            batch: list[tuple[WantedCandidate, WantedSubtitle]] = []
            for wanted, episode, series in rows:
                batch.append(
                    (
                        _episode_candidate(
                            instance_id,
                            wanted,
                            episode,
                            series,
                            subtitles.get(episode.id, ()),
                        ),
                        wanted,
                    )
                )
            await self._evaluate_batch(batch, cascade, exclusions, now, summary)
            if len(rows) < WANTED_BATCH:
                return

    async def _discover_movies(
        self,
        instance_id: UUID,
        cascade: CascadeInput,
        exclusions: tuple[ExclusionRule, ...],
        now: datetime,
        summary: DiscoveryRunSummary,
    ) -> None:
        last_id: UUID | None = None
        while True:
            stmt = (
                select(WantedSubtitle, Movie)
                .join(Movie, WantedSubtitle.movie_id == Movie.id)
                .where(
                    WantedSubtitle.bazarr_instance_id == instance_id,
                    WantedSubtitle.movie_id.is_not(None),
                )
                .order_by(WantedSubtitle.id)
                .limit(WANTED_BATCH)
            )
            if last_id is not None:
                stmt = stmt.where(WantedSubtitle.id > last_id)
            rows = (await self.session.execute(stmt)).tuples().all()
            if not rows:
                return
            last_id = rows[-1][0].id
            subtitles = await self._subtitles_by_movie([movie.id for _, movie in rows])
            batch: list[tuple[WantedCandidate, WantedSubtitle]] = []
            for wanted, movie in rows:
                batch.append(
                    (
                        _movie_candidate(
                            instance_id, wanted, movie, subtitles.get(movie.id, ())
                        ),
                        wanted,
                    )
                )
            await self._evaluate_batch(batch, cascade, exclusions, now, summary)
            if len(rows) < WANTED_BATCH:
                return

    async def _subtitles_by_episode(
        self, episode_ids: list[UUID]
    ) -> dict[UUID, tuple[ExistingSubtitle, ...]]:
        if not episode_ids:
            return {}
        rows = (
            await self.session.scalars(
                select(Subtitle).where(Subtitle.episode_id.in_(episode_ids))
            )
        ).all()
        grouped: dict[UUID, list[ExistingSubtitle]] = {}
        for row in rows:
            if row.episode_id is None:
                continue
            grouped.setdefault(row.episode_id, []).append(
                ExistingSubtitle(
                    language=row.language,
                    forced=row.forced,
                    hi=row.hi,
                    embedded=row.file_path is None,
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    async def _subtitles_by_movie(
        self, movie_ids: list[UUID]
    ) -> dict[UUID, tuple[ExistingSubtitle, ...]]:
        if not movie_ids:
            return {}
        rows = (
            await self.session.scalars(
                select(Subtitle).where(Subtitle.movie_id.in_(movie_ids))
            )
        ).all()
        grouped: dict[UUID, list[ExistingSubtitle]] = {}
        for row in rows:
            if row.movie_id is None:
                continue
            grouped.setdefault(row.movie_id, []).append(
                ExistingSubtitle(
                    language=row.language,
                    forced=row.forced,
                    hi=row.hi,
                    embedded=row.file_path is None,
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    # ------------------------------------------------------------ evaluation

    async def _evaluate_batch(
        self,
        batch: list[tuple[WantedCandidate, WantedSubtitle]],
        cascade: CascadeInput,
        exclusions: tuple[ExclusionRule, ...],
        now: datetime,
        summary: DiscoveryRunSummary,
    ) -> None:
        planned: list[
            tuple[WantedCandidate, WantedSubtitle, Planned, EffectivePolicy]
        ] = []
        for candidate, wanted in batch:
            summary.evaluated += 1
            policy = _policy_for(candidate, cascade)
            decision = explain_candidate(candidate, policy, exclusions, now=now)
            match decision:
                case Planned():
                    summary.planned += 1
                    planned.append((candidate, wanted, decision, policy))
                case NotPlanned(reason=reason):
                    summary.not_planned[reason] = summary.not_planned.get(reason, 0) + 1
        if not planned:
            return
        existing = await self._existing_by_identity(planned)
        # All writes for the batch ride one transaction/commit (no per-item
        # commits at 100k scale). Locals merge into the summary only after the
        # commit succeeds so counts never overstate persisted work.
        created = 0
        refreshed = 0
        advanced = 0
        reappeared = 0
        try:
            for candidate, wanted, decision, policy in planned:
                identity = _identity(candidate)
                row = existing.get(identity)
                if row is not None and IntentState(row.state) in TERMINAL_STATES:
                    # A want re-appearing for a terminal intent is a new desire
                    # epoch; re-opening is deferred to Phase 3 (FR-R6) —
                    # surfaced here so it is never silent.
                    reappeared += 1
                    continue
                breakdown = score_intent(
                    _score_facts(candidate), policy.priority_weights.value, now=now
                )
                if (
                    row is not None
                    and IntentState(row.state) is not IntentState.DISCOVERED
                    and row.source_language == decision.source_language
                ):
                    # Steady state: already eligible (or beyond) with the same
                    # election — the rule chain remains the decision of record,
                    # but the score (and its trace step) refreshes so backlog
                    # order and FR-V1 explanation never drift apart as recency
                    # decays or weights change between runs. Bookkeeping only:
                    # no audit event.
                    if row.priority != breakdown.total:
                        row.priority = breakdown.total
                        row.decision_trace = encode_trace(
                            _with_priority_step(
                                decode_trace(row.decision_trace), breakdown, policy
                            )
                        )
                    continue
                seed = _seed(candidate, decision, breakdown, policy)
                intent, was_created = await self.intents.upsert(
                    seed, existing_row=row, skip_lookup=True, commit=False
                )
                if was_created:
                    created += 1
                else:
                    refreshed += 1
                if IntentState(intent.state) is IntentState.DISCOVERED:
                    _ = await self.intents.transition(
                        intent,
                        IntentState.ELIGIBLE,
                        actor="discovery",
                        reason="eligible: source elected, grace passed, no skip",
                        evidence={
                            "kind": "discovery",
                            "wanted_last_seen_at": _aware(
                                wanted.last_seen_at
                            ).isoformat(),
                            "source_language": decision.source_language,
                        },
                        commit=False,
                    )
                    advanced += 1
            await self.session.commit()
        except IntegrityError as error:
            # Natural-key race with a writer outside this process (in-process
            # passes are serialized by the instance lock registry). Drop this
            # batch's writes; re-discovery is idempotent and the next pass
            # re-creates them against the winner's rows.
            await self.session.rollback()
            _logger.warning(
                "discovery batch hit a natural-key conflict; deferred to next pass",
                error=str(error),
            )
            return
        summary.created += created
        summary.refreshed += refreshed
        summary.advanced_to_eligible += advanced
        summary.reappeared_terminal += reappeared

    async def _existing_by_identity(
        self,
        planned: list[tuple[WantedCandidate, WantedSubtitle, Planned, EffectivePolicy]],
    ) -> dict[tuple[str, int, str, bool, bool], Intent]:
        first = planned[0][0]
        instance_id = first.item.bazarr_instance_id
        episode_ids = [
            candidate.item.sonarr_episode_id
            for candidate, _, _, _ in planned
            if isinstance(candidate.item, EpisodeRef)
        ]
        movie_ids = [
            candidate.item.radarr_id
            for candidate, _, _, _ in planned
            if isinstance(candidate.item, MovieRef)
        ]
        rows: list[Intent] = []
        if episode_ids:
            rows.extend(
                (
                    await self.session.scalars(
                        select(Intent).where(
                            Intent.bazarr_instance_id == instance_id,
                            Intent.media_type == "episode",
                            Intent.external_media_id.in_(episode_ids),
                        )
                    )
                ).all()
            )
        if movie_ids:
            rows.extend(
                (
                    await self.session.scalars(
                        select(Intent).where(
                            Intent.bazarr_instance_id == instance_id,
                            Intent.media_type == "movie",
                            Intent.external_media_id.in_(movie_ids),
                        )
                    )
                ).all()
            )
        return {
            (
                row.media_type,
                row.external_media_id,
                row.target_language,
                row.forced,
                row.hi,
            ): row
            for row in rows
        }

    # ------------------------------------------------------------ withdrawal

    async def _withdraw_vanished(
        self, instance_id: UUID, summary: DiscoveryRunSummary
    ) -> None:
        completed_pass = (
            await self.session.scalars(
                select(SyncRun)
                .where(
                    SyncRun.bazarr_instance_id == instance_id,
                    SyncRun.kind == "wanted",
                    SyncRun.status == "completed",
                )
                .order_by(SyncRun.finished_at.desc())
                .limit(1)
            )
        ).first()
        if completed_pass is None:
            # Never fabricate withdrawals from an empty/partial wanted table.
            return
        last_id: UUID | None = None
        while True:
            stmt = (
                select(Intent)
                .where(
                    Intent.bazarr_instance_id == instance_id,
                    Intent.state.in_(_WITHDRAWABLE_STATES),
                )
                .order_by(Intent.id)
                .limit(WITHDRAW_BATCH)
            )
            if last_id is not None:
                stmt = stmt.where(Intent.id > last_id)
            rows = (await self.session.scalars(stmt)).all()
            if not rows:
                return
            last_id = rows[-1].id
            still_wanted = await self._wanted_identities(instance_id, rows)
            for row in rows:
                key = (
                    row.media_type,
                    row.external_media_id,
                    row.target_language,
                    row.forced,
                    row.hi,
                )
                if key in still_wanted:
                    continue
                reason = "withdrawn: no longer wanted by Bazarr"
                steps = (*decode_trace(row.decision_trace), Withdrawn(reason=reason))
                row.decision_trace = encode_trace(steps)
                _ = await self.intents.transition(
                    row,
                    IntentState.SUPERSEDED,
                    actor="discovery",
                    reason=reason,
                    evidence={
                        "kind": "wanted_disappearance",
                        "wanted_pass_finished_at": (
                            _aware(completed_pass.finished_at).isoformat()
                            if completed_pass.finished_at is not None
                            else None
                        ),
                    },
                )
                summary.withdrawn += 1
            if len(rows) < WITHDRAW_BATCH:
                return

    async def _wanted_identities(
        self, instance_id: UUID, intents: Sequence[Intent]
    ) -> set[tuple[str, int, str, bool, bool]]:
        episode_ids = [
            row.external_media_id for row in intents if row.media_type == "episode"
        ]
        movie_ids = [
            row.external_media_id for row in intents if row.media_type == "movie"
        ]
        identities: set[tuple[str, int, str, bool, bool]] = set()
        if episode_ids:
            rows = (
                await self.session.execute(
                    select(
                        Episode.sonarr_episode_id,
                        WantedSubtitle.language,
                        WantedSubtitle.forced,
                        WantedSubtitle.hi,
                    )
                    .join(Episode, WantedSubtitle.episode_id == Episode.id)
                    .where(
                        WantedSubtitle.bazarr_instance_id == instance_id,
                        Episode.sonarr_episode_id.in_(episode_ids),
                    )
                )
            ).tuples()
            identities.update(
                ("episode", episode_id, language, forced, hi)
                for episode_id, language, forced, hi in rows
            )
        if movie_ids:
            rows = (
                await self.session.execute(
                    select(
                        Movie.radarr_id,
                        WantedSubtitle.language,
                        WantedSubtitle.forced,
                        WantedSubtitle.hi,
                    )
                    .join(Movie, WantedSubtitle.movie_id == Movie.id)
                    .where(
                        WantedSubtitle.bazarr_instance_id == instance_id,
                        Movie.radarr_id.in_(movie_ids),
                    )
                )
            ).tuples()
            identities.update(
                ("movie", radarr_id, language, forced, hi)
                for radarr_id, language, forced, hi in rows
            )
        return identities


def _policy_for(candidate: WantedCandidate, cascade: CascadeInput) -> EffectivePolicy:
    return resolve_effective_policy(candidate.item, cascade)


def _identity(candidate: WantedCandidate) -> tuple[str, int, str, bool, bool]:
    if isinstance(candidate.item, EpisodeRef):
        return (
            "episode",
            candidate.item.sonarr_episode_id,
            candidate.language,
            candidate.forced,
            candidate.hi,
        )
    return (
        "movie",
        candidate.item.radarr_id,
        candidate.language,
        candidate.forced,
        candidate.hi,
    )


def _score_facts(candidate: WantedCandidate) -> ScoreFacts:
    return ScoreFacts(
        media_type="episode" if isinstance(candidate.item, EpisodeRef) else "movie",
        monitored=candidate.item.monitored,
        recency_anchor=recency_anchor(candidate),
        series_ended=candidate.series_ended,
    )


def _priority_step(
    breakdown: ScoreBreakdown, policy: EffectivePolicy
) -> PriorityAssigned:
    return PriorityAssigned(
        score=breakdown.total,
        components=breakdown.components,
        weights_layer=policy.priority_weights.provenance.layer,
    )


def _with_priority_step(
    steps: tuple[TraceStep, ...], breakdown: ScoreBreakdown, policy: EffectivePolicy
) -> tuple[TraceStep, ...]:
    kept = tuple(step for step in steps if not isinstance(step, PriorityAssigned))
    return (*kept, _priority_step(breakdown, policy))


def _seed(
    candidate: WantedCandidate,
    decision: Planned,
    breakdown: ScoreBreakdown,
    policy: EffectivePolicy,
) -> IntentSeed:
    trace: tuple[TraceStep, ...] = (
        *decision.trace,
        _priority_step(breakdown, policy),
    )
    if isinstance(candidate.item, EpisodeRef):
        return IntentSeed(
            bazarr_instance_id=candidate.item.bazarr_instance_id,
            media_type="episode",
            external_media_id=candidate.item.sonarr_episode_id,
            sonarr_series_id=candidate.item.sonarr_series_id,
            season=candidate.season,
            episode_number=candidate.episode_number,
            display_title=candidate.display_title,
            source_language=decision.source_language,
            target_language=candidate.language,
            forced=candidate.forced,
            hi=candidate.hi,
            priority=breakdown.total,
            trace=trace,
        )
    return IntentSeed(
        bazarr_instance_id=candidate.item.bazarr_instance_id,
        media_type="movie",
        external_media_id=candidate.item.radarr_id,
        display_title=candidate.display_title,
        source_language=decision.source_language,
        target_language=candidate.language,
        forced=candidate.forced,
        hi=candidate.hi,
        priority=breakdown.total,
        trace=trace,
    )
