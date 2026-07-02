"""Mirror browse queries (P1-T5): indexed paths only, sized for NFR-2/NFR-4."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from perevoditarr.core.errors import NotFoundError
from perevoditarr.core.schemas import Page
from perevoditarr.modules.mirror.models import (
    Episode,
    Movie,
    Series,
    Subtitle,
    SyncRun,
    WantedSubtitle,
)
from perevoditarr.modules.mirror.schemas import (
    CoverageStat,
    EpisodeRead,
    FreshnessRead,
    MovieRead,
    SeriesRead,
    SubtitleRead,
    SyncRunRead,
    WantedRead,
)

STALE_AFTER = timedelta(hours=24)


def _subtitle_read(subtitle: Subtitle) -> SubtitleRead:
    return SubtitleRead(
        language=subtitle.language,
        forced=subtitle.forced,
        hi=subtitle.hi,
        is_embedded=subtitle.file_path is None,
    )


class MirrorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    # ------------------------------------------------------------- series

    async def series_page(
        self,
        *,
        instance_id: UUID | None = None,
        search: str | None = None,
        missing_language: str | None = None,
        monitored: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[SeriesRead]:
        statement: Select[tuple[Series]] = select(Series)
        if instance_id is not None:
            statement = statement.where(Series.bazarr_instance_id == instance_id)
        if search:
            pattern = f"%{search.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(Series.title).like(pattern),
                    Series.sort_title.like(pattern),
                )
            )
        if monitored is not None:
            statement = statement.where(Series.monitored == monitored)
        if missing_language:
            statement = statement.where(
                exists(
                    select(WantedSubtitle.id)
                    .join(Episode, WantedSubtitle.episode_id == Episode.id)
                    .where(
                        Episode.series_id == Series.id,
                        WantedSubtitle.language == missing_language,
                    )
                )
            )
        total = (
            await self.session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            or 0
        )
        rows = (
            await self.session.scalars(
                statement.order_by(Series.sort_title).limit(limit).offset(offset)
            )
        ).all()

        wanted_counts = await self._series_wanted_counts([s.id for s in rows])
        items = [
            SeriesRead(
                id=s.id,
                bazarr_instance_id=s.bazarr_instance_id,
                sonarr_series_id=s.sonarr_series_id,
                title=s.title,
                year=s.year,
                monitored=s.monitored,
                ended=s.ended,
                episode_count=s.episode_count,
                wanted_count=wanted_counts.get(s.id, 0),
            )
            for s in rows
        ]
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def _series_wanted_counts(self, series_ids: list[UUID]) -> dict[UUID, int]:
        if not series_ids:
            return {}
        result = await self.session.execute(
            select(Episode.series_id, func.count(WantedSubtitle.id))
            .join(WantedSubtitle, WantedSubtitle.episode_id == Episode.id)
            .where(Episode.series_id.in_(series_ids))
            .group_by(Episode.series_id)
        )
        return {series_id: int(count) for series_id, count in result.all()}

    async def series_episodes(
        self, series_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> Page[EpisodeRead]:
        series = await self.session.get(Series, series_id)
        if series is None:
            raise NotFoundError(f"series {series_id} not found")
        statement = (
            select(Episode)
            .where(Episode.series_id == series_id)
            .options(selectinload(Episode.subtitles))
            .order_by(Episode.season, Episode.episode)
        )
        total = (
            await self.session.scalar(
                select(func.count(Episode.id)).where(Episode.series_id == series_id)
            )
            or 0
        )
        rows = (await self.session.scalars(statement.limit(limit).offset(offset))).all()
        wanted = await self._wanted_by_episode([e.id for e in rows])
        items = [
            EpisodeRead(
                id=e.id,
                sonarr_series_id=e.sonarr_series_id,
                sonarr_episode_id=e.sonarr_episode_id,
                title=e.title,
                season=e.season,
                episode=e.episode,
                monitored=e.monitored,
                air_date=e.air_date,
                subtitles=[_subtitle_read(s) for s in e.subtitles],
                wanted=wanted.get(e.id, []),
            )
            for e in rows
        ]
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def _wanted_by_episode(
        self, episode_ids: list[UUID]
    ) -> dict[UUID, list[WantedRead]]:
        if not episode_ids:
            return {}
        rows = (
            await self.session.scalars(
                select(WantedSubtitle).where(WantedSubtitle.episode_id.in_(episode_ids))
            )
        ).all()
        grouped: dict[UUID, list[WantedRead]] = {}
        for row in rows:
            if row.episode_id is None:
                continue
            grouped.setdefault(row.episode_id, []).append(
                WantedRead(language=row.language, forced=row.forced, hi=row.hi)
            )
        return grouped

    # ------------------------------------------------------------- movies

    async def movies_page(
        self,
        *,
        instance_id: UUID | None = None,
        search: str | None = None,
        missing_language: str | None = None,
        monitored: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[MovieRead]:
        statement: Select[tuple[Movie]] = select(Movie).options(
            selectinload(Movie.subtitles)
        )
        if instance_id is not None:
            statement = statement.where(Movie.bazarr_instance_id == instance_id)
        if search:
            pattern = f"%{search.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(Movie.title).like(pattern),
                    Movie.sort_title.like(pattern),
                )
            )
        if monitored is not None:
            statement = statement.where(Movie.monitored == monitored)
        if missing_language:
            statement = statement.where(
                exists(
                    select(WantedSubtitle.id).where(
                        WantedSubtitle.movie_id == Movie.id,
                        WantedSubtitle.language == missing_language,
                    )
                )
            )
        total = (
            await self.session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            or 0
        )
        rows = (
            await self.session.scalars(
                statement.order_by(Movie.sort_title).limit(limit).offset(offset)
            )
        ).all()
        wanted = await self._wanted_by_movie([m.id for m in rows])
        items = [
            MovieRead(
                id=m.id,
                bazarr_instance_id=m.bazarr_instance_id,
                radarr_id=m.radarr_id,
                title=m.title,
                year=m.year,
                monitored=m.monitored,
                subtitles=[_subtitle_read(s) for s in m.subtitles],
                wanted=wanted.get(m.id, []),
            )
            for m in rows
        ]
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def _wanted_by_movie(
        self, movie_ids: list[UUID]
    ) -> dict[UUID, list[WantedRead]]:
        if not movie_ids:
            return {}
        rows = (
            await self.session.scalars(
                select(WantedSubtitle).where(WantedSubtitle.movie_id.in_(movie_ids))
            )
        ).all()
        grouped: dict[UUID, list[WantedRead]] = {}
        for row in rows:
            if row.movie_id is None:
                continue
            grouped.setdefault(row.movie_id, []).append(
                WantedRead(language=row.language, forced=row.forced, hi=row.hi)
            )
        return grouped

    # ---------------------------------------------------------- dashboard

    async def coverage(self, *, instance_id: UUID | None = None) -> list[CoverageStat]:
        def scoped[T: Select[tuple[str, int]]](statement: T) -> T:
            if instance_id is not None:
                return statement.where(  # pyright: ignore[reportReturnType]
                    Subtitle.bazarr_instance_id == instance_id
                )
            return statement

        episodes_q = scoped(
            select(Subtitle.language, func.count(func.distinct(Subtitle.episode_id)))
            .where(Subtitle.episode_id.is_not(None))
            .group_by(Subtitle.language)
        )
        movies_q = scoped(
            select(Subtitle.language, func.count(func.distinct(Subtitle.movie_id)))
            .where(Subtitle.movie_id.is_not(None))
            .group_by(Subtitle.language)
        )
        wanted_episodes_q = select(
            WantedSubtitle.language, func.count(WantedSubtitle.id)
        ).where(WantedSubtitle.episode_id.is_not(None))
        wanted_movies_q = select(
            WantedSubtitle.language, func.count(WantedSubtitle.id)
        ).where(WantedSubtitle.movie_id.is_not(None))
        if instance_id is not None:
            wanted_episodes_q = wanted_episodes_q.where(
                WantedSubtitle.bazarr_instance_id == instance_id
            )
            wanted_movies_q = wanted_movies_q.where(
                WantedSubtitle.bazarr_instance_id == instance_id
            )
        wanted_episodes_q = wanted_episodes_q.group_by(WantedSubtitle.language)
        wanted_movies_q = wanted_movies_q.group_by(WantedSubtitle.language)

        episode_counts = {
            row[0]: int(row[1])
            for row in (await self.session.execute(episodes_q)).all()
        }
        movie_counts = {
            row[0]: int(row[1]) for row in (await self.session.execute(movies_q)).all()
        }
        wanted_episode_counts = {
            row[0]: int(row[1])
            for row in (await self.session.execute(wanted_episodes_q)).all()
        }
        wanted_movie_counts = {
            row[0]: int(row[1])
            for row in (await self.session.execute(wanted_movies_q)).all()
        }
        languages = sorted(
            set(episode_counts)
            | set(movie_counts)
            | set(wanted_episode_counts)
            | set(wanted_movie_counts)
        )
        return [
            CoverageStat(
                language=language,
                episodes_with_subtitle=episode_counts.get(language, 0),
                movies_with_subtitle=movie_counts.get(language, 0),
                episodes_wanted=wanted_episode_counts.get(language, 0),
                movies_wanted=wanted_movie_counts.get(language, 0),
            )
            for language in languages
        ]

    async def sync_runs(
        self, *, instance_id: UUID | None = None, limit: int = 20, offset: int = 0
    ) -> Page[SyncRunRead]:
        statement: Select[tuple[SyncRun]] = select(SyncRun)
        if instance_id is not None:
            statement = statement.where(SyncRun.bazarr_instance_id == instance_id)
        total = (
            await self.session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            or 0
        )
        rows = (
            await self.session.scalars(
                statement.order_by(SyncRun.started_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        items = [
            SyncRunRead(
                id=r.id,
                bazarr_instance_id=r.bazarr_instance_id,
                kind=r.kind,
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                counters=r.counters,
                error=r.error,
            )
            for r in rows
        ]
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def freshness(self, instance_ids: list[UUID]) -> list[FreshnessRead]:
        """Mirror freshness per instance (FR-M4/FR-DR11)."""
        results: list[FreshnessRead] = []
        now = datetime.now(UTC)
        for instance_id in instance_ids:
            last_full = await self.session.scalar(
                select(func.max(SyncRun.finished_at)).where(
                    SyncRun.bazarr_instance_id == instance_id,
                    SyncRun.status == "completed",
                    SyncRun.kind.in_(["full", "incremental"]),
                )
            )
            last_wanted = await self.session.scalar(
                select(func.max(SyncRun.finished_at)).where(
                    SyncRun.bazarr_instance_id == instance_id,
                    SyncRun.status == "completed",
                    SyncRun.kind == "wanted",
                )
            )
            newest = max(
                (d for d in (last_full, last_wanted) if d is not None), default=None
            )
            stale = newest is None or (now - _aware(newest)) > STALE_AFTER
            results.append(
                FreshnessRead(
                    bazarr_instance_id=instance_id,
                    last_full_sync_at=last_full,
                    last_wanted_sync_at=last_wanted,
                    stale=stale,
                )
            )
        return results


def _aware(value: datetime) -> datetime:
    # SQLite loses tzinfo on DateTime columns; normalize for comparisons.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
