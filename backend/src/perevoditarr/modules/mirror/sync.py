"""Mirror sync engine (P1-T5, FR-M1/M2).

Idempotent, batched, dialect-portable upserts (PostgreSQL
on_conflict_do_update with the SQLite dialect's equivalent as the portable
fallback — NFR-2). Wanted sync is its own fast loop; withdrawal is decided by
last_seen_at only after a fully completed pass, so a crashed sync never
fabricates disappearances.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CursorResult, Table, delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.logging import get_logger
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances import InstanceGateway, InstancesService
from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.bazarr.schemas import EpisodeItem, MovieItem
from perevoditarr.modules.mirror.models import (
    Episode,
    Movie,
    Series,
    Subtitle,
    SyncRun,
    WantedSubtitle,
)

_logger = get_logger()

SERIES_PAGE_SIZE = 250
MOVIES_PAGE_SIZE = 250
WANTED_PAGE_SIZE = 500
EPISODES_SERIES_BATCH = 25


def _year(raw: str | None) -> int | None:
    if raw is None or not raw.strip().isdigit():
        return None
    return int(raw.strip())


def _sort_title(title: str | None) -> str:
    text = (title or "").lower()
    for prefix in ("the ", "a ", "an "):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


async def _upsert(
    session: AsyncSession,
    table: Table,
    rows: list[dict[str, object]],
    *,
    index_elements: list[str],
    update_columns: list[str],
) -> None:
    if not rows:
        return
    dialect = session.get_bind().dialect.name
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
    statement = insert_fn(table).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=index_elements,
        set_={col: statement.excluded[col] for col in update_columns},
    )
    _ = await session.execute(statement)


class MirrorSyncService:
    def __init__(
        self,
        session: AsyncSession,
        instances: InstancesService,
        gateway: InstanceGateway,
        sse_bus: SseBus,
    ) -> None:
        self.session: AsyncSession = session
        self.instances: InstancesService = instances
        self.gateway: InstanceGateway = gateway
        self.sse_bus: SseBus = sse_bus

    async def _client(self, instance_id: UUID) -> BazarrClient:
        instance = await self.instances.get_bazarr(instance_id)
        return self.gateway.bazarr(
            instance.url, self.instances.bazarr_api_key(instance)
        )

    # ------------------------------------------------------------ library

    async def sync_library(self, instance_id: UUID, *, full: bool = False) -> SyncRun:
        """Sync series/episodes/subtitles/movies. `full` also removes rows
        that disappeared upstream."""
        run = await self._start_run(instance_id, "full" if full else "incremental")
        counters: dict[str, int] = {
            "series": 0,
            "episodes": 0,
            "subtitles": 0,
            "movies": 0,
        }
        try:
            client = await self._client(instance_id)
            seen_series: set[int] = set()
            start = 0
            while True:
                page = await client.series(start=start, length=SERIES_PAGE_SIZE)
                if not page.data:
                    break
                series_rows: list[dict[str, object]] = []
                for item in page.data:
                    seen_series.add(item.sonarr_series_id)
                    series_rows.append(
                        {
                            "bazarr_instance_id": instance_id,
                            "sonarr_series_id": item.sonarr_series_id,
                            "title": item.title or "",
                            "sort_title": _sort_title(item.title),
                            "year": _year(item.year),
                            "monitored": item.monitored,
                            "ended": item.ended,
                            "profile_id": item.profile_id,
                            "tags": item.tags,
                            "episode_count": item.episode_file_count or 0,
                            "updated_at": datetime.now(UTC),
                        }
                    )
                await _upsert(
                    self.session,
                    Series.__table__,  # pyright: ignore[reportArgumentType]
                    series_rows,
                    index_elements=["bazarr_instance_id", "sonarr_series_id"],
                    update_columns=[
                        "title",
                        "sort_title",
                        "year",
                        "monitored",
                        "ended",
                        "profile_id",
                        "tags",
                        "episode_count",
                        "updated_at",
                    ],
                )
                counters["series"] += len(series_rows)
                await self.session.commit()
                self.sse_bus.publish(
                    "mirror.sync",
                    {
                        "runId": str(run.id),
                        "phase": "series",
                        "count": counters["series"],
                        "total": page.total,
                    },
                )
                if len(page.data) < SERIES_PAGE_SIZE:
                    break
                start += SERIES_PAGE_SIZE

            series_ids = await self._series_row_ids(instance_id)
            ordered = sorted(seen_series)
            for offset in range(0, len(ordered), EPISODES_SERIES_BATCH):
                batch = ordered[offset : offset + EPISODES_SERIES_BATCH]
                episodes = await client.episodes(series_ids=batch)
                episode_counter, subtitle_counter = await self._store_episodes(
                    instance_id, series_ids, episodes
                )
                counters["episodes"] += episode_counter
                counters["subtitles"] += subtitle_counter
                await self.session.commit()
                self.sse_bus.publish(
                    "mirror.sync",
                    {
                        "runId": str(run.id),
                        "phase": "episodes",
                        "count": counters["episodes"],
                    },
                )

            start = 0
            while True:
                movies = await client.movies(start=start, length=MOVIES_PAGE_SIZE)
                if not movies.data:
                    break
                subtitle_counter = await self._store_movies(instance_id, movies.data)
                counters["movies"] += len(movies.data)
                counters["subtitles"] += subtitle_counter
                await self.session.commit()
                if len(movies.data) < MOVIES_PAGE_SIZE:
                    break
                start += MOVIES_PAGE_SIZE

            if full:
                await self._remove_vanished_series(instance_id, seen_series)
                await self.session.commit()

            await self._finish_run(run, "completed", counters)
        except Exception as error:
            await self.session.rollback()
            await self._finish_run(run, "failed", counters, error=str(error))
            raise
        return run

    async def _series_row_ids(self, instance_id: UUID) -> dict[int, UUID]:
        result = await self.session.execute(
            select(Series.sonarr_series_id, Series.id).where(
                Series.bazarr_instance_id == instance_id
            )
        )
        return {int(sonarr_id): row_id for sonarr_id, row_id in result.tuples().all()}

    async def _store_episodes(
        self,
        instance_id: UUID,
        series_ids: dict[int, UUID],
        episodes: list[EpisodeItem],
    ) -> tuple[int, int]:
        rows: list[dict[str, object]] = []
        for item in episodes:
            series_row = series_ids.get(item.sonarr_series_id)
            if series_row is None:
                continue
            rows.append(
                {
                    "bazarr_instance_id": instance_id,
                    "series_id": series_row,
                    "sonarr_series_id": item.sonarr_series_id,
                    "sonarr_episode_id": item.sonarr_episode_id,
                    "title": item.title or "",
                    "season": item.season,
                    "episode": item.episode,
                    "monitored": item.monitored,
                    "updated_at": datetime.now(UTC),
                }
            )
        await _upsert(
            self.session,
            Episode.__table__,  # pyright: ignore[reportArgumentType]
            rows,
            index_elements=["bazarr_instance_id", "sonarr_episode_id"],
            update_columns=[
                "series_id",
                "sonarr_series_id",
                "title",
                "season",
                "episode",
                "monitored",
                "updated_at",
            ],
        )

        episode_row_ids = await self._episode_row_ids(
            instance_id, [int(str(r["sonarr_episode_id"])) for r in rows]
        )
        subtitle_rows: list[dict[str, object]] = []
        replace_ids: list[UUID] = []
        for item in episodes:
            episode_row = episode_row_ids.get(item.sonarr_episode_id)
            if episode_row is None:
                continue
            replace_ids.append(episode_row)
            for subtitle in item.subtitles:
                if subtitle.code2 is None:
                    continue
                subtitle_rows.append(
                    {
                        "bazarr_instance_id": instance_id,
                        "episode_id": episode_row,
                        "movie_id": None,
                        "language": subtitle.code2,
                        "forced": subtitle.forced,
                        "hi": subtitle.hi,
                        "file_path": subtitle.path,
                    }
                )
        # Existing-subtitle rows have no stable upstream identity; replacing
        # the affected episodes' rows wholesale is the idempotent path.
        if replace_ids:
            _ = await self.session.execute(
                delete(Subtitle).where(Subtitle.episode_id.in_(replace_ids))
            )
        if subtitle_rows:
            _ = await self.session.execute(insert(Subtitle), subtitle_rows)
        return len(rows), len(subtitle_rows)

    async def _episode_row_ids(
        self, instance_id: UUID, sonarr_episode_ids: list[int]
    ) -> dict[int, UUID]:
        if not sonarr_episode_ids:
            return {}
        result = await self.session.execute(
            select(Episode.sonarr_episode_id, Episode.id).where(
                Episode.bazarr_instance_id == instance_id,
                Episode.sonarr_episode_id.in_(sonarr_episode_ids),
            )
        )
        return {int(sonarr_id): row_id for sonarr_id, row_id in result.tuples().all()}

    async def _store_movies(self, instance_id: UUID, movies: list[MovieItem]) -> int:
        rows: list[dict[str, object]] = []
        for item in movies:
            rows.append(
                {
                    "bazarr_instance_id": instance_id,
                    "radarr_id": item.radarr_id,
                    "title": item.title or "",
                    "sort_title": _sort_title(item.title),
                    "year": _year(item.year),
                    "monitored": item.monitored,
                    "profile_id": item.profile_id,
                    "tags": item.tags,
                    "updated_at": datetime.now(UTC),
                }
            )
        await _upsert(
            self.session,
            Movie.__table__,  # pyright: ignore[reportArgumentType]
            rows,
            index_elements=["bazarr_instance_id", "radarr_id"],
            update_columns=[
                "title",
                "sort_title",
                "year",
                "monitored",
                "profile_id",
                "tags",
                "updated_at",
            ],
        )
        movie_row_ids = await self._movie_row_ids(
            instance_id, [int(str(r["radarr_id"])) for r in rows]
        )
        subtitle_rows: list[dict[str, object]] = []
        replace_ids: list[UUID] = []
        for item in movies:
            movie_row = movie_row_ids.get(item.radarr_id)
            if movie_row is None:
                continue
            replace_ids.append(movie_row)
            for subtitle in item.subtitles:
                if subtitle.code2 is None:
                    continue
                subtitle_rows.append(
                    {
                        "bazarr_instance_id": instance_id,
                        "episode_id": None,
                        "movie_id": movie_row,
                        "language": subtitle.code2,
                        "forced": subtitle.forced,
                        "hi": subtitle.hi,
                        "file_path": subtitle.path,
                    }
                )
        if replace_ids:
            _ = await self.session.execute(
                delete(Subtitle).where(Subtitle.movie_id.in_(replace_ids))
            )
        if subtitle_rows:
            _ = await self.session.execute(insert(Subtitle), subtitle_rows)
        return len(subtitle_rows)

    async def _movie_row_ids(
        self, instance_id: UUID, radarr_ids: list[int]
    ) -> dict[int, UUID]:
        if not radarr_ids:
            return {}
        result = await self.session.execute(
            select(Movie.radarr_id, Movie.id).where(
                Movie.bazarr_instance_id == instance_id,
                Movie.radarr_id.in_(radarr_ids),
            )
        )
        return {int(radarr_id): row_id for radarr_id, row_id in result.tuples().all()}

    async def _remove_vanished_series(self, instance_id: UUID, seen: set[int]) -> None:
        existing = await self.session.scalars(
            select(Series.sonarr_series_id).where(
                Series.bazarr_instance_id == instance_id
            )
        )
        vanished = [sid for sid in existing if sid not in seen]
        for offset in range(0, len(vanished), 500):
            chunk = vanished[offset : offset + 500]
            _ = await self.session.execute(
                delete(Series).where(
                    Series.bazarr_instance_id == instance_id,
                    Series.sonarr_series_id.in_(chunk),
                )
            )

    # ------------------------------------------------------------- wanted

    async def sync_wanted(self, instance_id: UUID) -> SyncRun:
        """Fast wanted-list loop — the discovery feed (FR-P1 groundwork)."""
        run = await self._start_run(instance_id, "wanted")
        counters = {"wanted_episodes": 0, "wanted_movies": 0, "withdrawn": 0}
        pass_started = datetime.now(UTC)
        try:
            client = await self._client(instance_id)
            start = 0
            while True:
                page = await client.wanted_episodes(
                    start=start, length=WANTED_PAGE_SIZE
                )
                if not page.data:
                    break
                episode_ids = await self._episode_row_ids(
                    instance_id, [w.sonarr_episode_id for w in page.data]
                )
                rows: list[dict[str, object]] = []
                for wanted in page.data:
                    episode_row = episode_ids.get(wanted.sonarr_episode_id)
                    if episode_row is None:
                        continue  # mirror lags upstream; the next library sync heals
                    for language in wanted.missing_subtitles:
                        if language.code2 is None:
                            continue
                        rows.append(
                            {
                                "bazarr_instance_id": instance_id,
                                "episode_id": episode_row,
                                "movie_id": None,
                                "language": language.code2,
                                "forced": language.forced,
                                "hi": language.hi,
                                "first_seen_at": pass_started,
                                "last_seen_at": pass_started,
                            }
                        )
                await _upsert(
                    self.session,
                    WantedSubtitle.__table__,  # pyright: ignore[reportArgumentType]
                    rows,
                    index_elements=[
                        "bazarr_instance_id",
                        "episode_id",
                        "language",
                        "forced",
                        "hi",
                    ],
                    # first_seen_at is intentionally NOT updated on conflict.
                    update_columns=["last_seen_at"],
                )
                counters["wanted_episodes"] += len(rows)
                await self.session.commit()
                if len(page.data) < WANTED_PAGE_SIZE:
                    break
                start += WANTED_PAGE_SIZE

            start = 0
            while True:
                movies_page = await client.wanted_movies(
                    start=start, length=WANTED_PAGE_SIZE
                )
                if not movies_page.data:
                    break
                movie_ids = await self._movie_row_ids(
                    instance_id, [w.radarr_id for w in movies_page.data]
                )
                rows = []
                for wanted_movie in movies_page.data:
                    movie_row = movie_ids.get(wanted_movie.radarr_id)
                    if movie_row is None:
                        continue
                    for language in wanted_movie.missing_subtitles:
                        if language.code2 is None:
                            continue
                        rows.append(
                            {
                                "bazarr_instance_id": instance_id,
                                "episode_id": None,
                                "movie_id": movie_row,
                                "language": language.code2,
                                "forced": language.forced,
                                "hi": language.hi,
                                "first_seen_at": pass_started,
                                "last_seen_at": pass_started,
                            }
                        )
                await _upsert(
                    self.session,
                    WantedSubtitle.__table__,  # pyright: ignore[reportArgumentType]
                    rows,
                    index_elements=[
                        "bazarr_instance_id",
                        "movie_id",
                        "language",
                        "forced",
                        "hi",
                    ],
                    update_columns=["last_seen_at"],
                )
                counters["wanted_movies"] += len(rows)
                await self.session.commit()
                if len(movies_page.data) < WANTED_PAGE_SIZE:
                    break
                start += WANTED_PAGE_SIZE

            # Withdrawal only after a fully completed pass (FR-R4 spirit):
            # anything not re-seen this pass is gone from Bazarr's wanted list.
            withdrawn = await self.session.execute(
                delete(WantedSubtitle).where(
                    WantedSubtitle.bazarr_instance_id == instance_id,
                    WantedSubtitle.last_seen_at < pass_started,
                )
            )
            counters["withdrawn"] = (
                withdrawn.rowcount if isinstance(withdrawn, CursorResult) else 0
            )
            await self.session.commit()
            await self._finish_run(run, "completed", counters)
        except Exception as error:
            await self.session.rollback()
            await self._finish_run(run, "failed", counters, error=str(error))
            raise
        return run

    # ---------------------------------------------------------------- runs

    async def _start_run(self, instance_id: UUID, kind: str) -> SyncRun:
        run = SyncRun(
            bazarr_instance_id=instance_id,
            kind=kind,
            status="running",
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        await self.session.commit()
        self.sse_bus.publish(
            "mirror.sync", {"runId": str(run.id), "phase": "started", "kind": kind}
        )
        return run

    async def _finish_run(
        self,
        run: SyncRun,
        status: str,
        counters: dict[str, int],
        *,
        error: str | None = None,
    ) -> None:
        run.status = status
        run.finished_at = datetime.now(UTC)
        run.counters = counters
        run.error = error
        await self.session.commit()
        self.sse_bus.publish(
            "mirror.sync",
            {
                "runId": str(run.id),
                "phase": status,
                "kind": run.kind,
                "counters": counters,
            },
        )
        if error is not None:
            _logger.warning("mirror sync failed", run_id=str(run.id), error=error)
