"""Nightly performance harness (P1-T5, NFR-2/NFR-4).

Seeds a synthetic 100k-episode library directly into the database and asserts
the browser's server-side query budgets on PostgreSQL. Runs in CI-nightly
(PEREVODITARR_PERF_DATABASE_URL set, marker `perf`); skipped otherwise.
"""

import asyncio
import os
import time
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from perevoditarr import models as models  # register all mappers (re-export)
from perevoditarr.core.db import metadata
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.mirror.models import (
    Episode,
    Series,
    Subtitle,
    WantedSubtitle,
)
from perevoditarr.modules.mirror.service import MirrorService

PERF_DB_ENV = "PEREVODITARR_PERF_DATABASE_URL"
SERIES_COUNT = 1_000
EPISODES_PER_SERIES = 100  # => 100_000 episodes
SUBTITLES_PER_EPISODE = 2  # => 200_000 subtitle rows
WANTED_RATIO = 5  # every 5th episode wants "da"
BUDGET_SECONDS = 0.2  # NFR-4: < 200 ms server time per browse interaction

pytestmark = pytest.mark.perf

_perf_url = os.environ.get(PERF_DB_ENV)


def _require_url() -> str:
    if not _perf_url:
        pytest.skip(f"{PERF_DB_ENV} not set - perf harness runs in CI-nightly")
    return _perf_url


async def _seed(url: str) -> uuid.UUID:
    engine = create_async_engine(url)
    instance_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.drop_all)
        await connection.run_sync(metadata.create_all)
        _ = await connection.execute(
            insert(BazarrInstance),
            [
                {
                    "id": instance_id,
                    "name": "perf",
                    "url": "http://bazarr.perf",
                    "api_key_encrypted": b"x",
                    "enabled": True,
                }
            ],
        )
        episode_rows: list[dict[str, object]] = []
        subtitle_rows: list[dict[str, object]] = []
        wanted_rows: list[dict[str, object]] = []
        series_rows: list[dict[str, object]] = []
        for series_index in range(SERIES_COUNT):
            series_id = uuid.uuid4()
            series_rows.append(
                {
                    "id": series_id,
                    "bazarr_instance_id": instance_id,
                    "sonarr_series_id": series_index + 1,
                    "title": f"Series {series_index:05d}",
                    "sort_title": f"series {series_index:05d}",
                    "year": 2020,
                    "monitored": True,
                    "ended": False,
                    "episode_count": EPISODES_PER_SERIES,
                }
            )
            for episode_index in range(EPISODES_PER_SERIES):
                episode_id = uuid.uuid4()
                sonarr_episode_id = (
                    series_index * EPISODES_PER_SERIES + episode_index + 1
                )
                episode_rows.append(
                    {
                        "id": episode_id,
                        "bazarr_instance_id": instance_id,
                        "series_id": series_id,
                        "sonarr_series_id": series_index + 1,
                        "sonarr_episode_id": sonarr_episode_id,
                        "title": f"Episode {episode_index + 1}",
                        "season": 1 + episode_index // 20,
                        "episode": episode_index % 20 + 1,
                        "monitored": True,
                    }
                )
                for lang in ("en", "de")[:SUBTITLES_PER_EPISODE]:
                    subtitle_rows.append(
                        {
                            "id": uuid.uuid4(),
                            "bazarr_instance_id": instance_id,
                            "episode_id": episode_id,
                            "movie_id": None,
                            "language": lang,
                            "forced": False,
                            "hi": False,
                            "file_path": f"/media/{sonarr_episode_id}.{lang}.srt",
                        }
                    )
                if sonarr_episode_id % WANTED_RATIO == 0:
                    wanted_rows.append(
                        {
                            "id": uuid.uuid4(),
                            "bazarr_instance_id": instance_id,
                            "episode_id": episode_id,
                            "movie_id": None,
                            "language": "da",
                            "forced": False,
                            "hi": False,
                            "first_seen_at": now,
                            "last_seen_at": now,
                        }
                    )
        _ = await connection.execute(insert(Series), series_rows)
        for offset in range(0, len(episode_rows), 10_000):
            _ = await connection.execute(
                insert(Episode),
                episode_rows[offset : offset + 10_000],
            )
        for offset in range(0, len(subtitle_rows), 10_000):
            _ = await connection.execute(
                insert(Subtitle),
                subtitle_rows[offset : offset + 10_000],
            )
        for offset in range(0, len(wanted_rows), 10_000):
            _ = await connection.execute(
                insert(WantedSubtitle),
                wanted_rows[offset : offset + 10_000],
            )
    await engine.dispose()
    return instance_id


async def _timed[T](awaitable: Awaitable[T]) -> tuple[float, T]:
    started = time.perf_counter()
    result = await awaitable
    return time.perf_counter() - started, result


def test_browse_query_budgets_at_100k_scale() -> None:
    url = _require_url()

    async def run() -> None:
        instance_id = await _seed(url)
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = MirrorService(session)

            elapsed, page = await _timed(
                service.series_page(instance_id=instance_id, limit=50)
            )
            assert page.total == SERIES_COUNT
            assert elapsed < BUDGET_SECONDS, f"series page took {elapsed:.3f}s"

            elapsed, page = await _timed(
                service.series_page(
                    instance_id=instance_id, search="series 0042", limit=50
                )
            )
            assert page.total >= 1
            assert elapsed < BUDGET_SECONDS, f"title search took {elapsed:.3f}s"

            elapsed, page = await _timed(
                service.series_page(
                    instance_id=instance_id, missing_language="da", limit=50
                )
            )
            assert page.total == SERIES_COUNT  # every series has wanted rows
            assert elapsed < BUDGET_SECONDS, f"missing filter took {elapsed:.3f}s"

            series_row = page.items[0]
            elapsed, episodes = await _timed(
                service.series_episodes(series_row.id, limit=100)
            )
            assert episodes.total == EPISODES_PER_SERIES
            assert elapsed < BUDGET_SECONDS, f"episode drilldown took {elapsed:.3f}s"

            elapsed, coverage = await _timed(service.coverage(instance_id=instance_id))
            assert any(c.language == "en" for c in coverage)
            # coverage powers a dashboard card; allow a looser budget
            assert elapsed < BUDGET_SECONDS * 5, f"coverage took {elapsed:.3f}s"
        await engine.dispose()

    asyncio.run(run())
