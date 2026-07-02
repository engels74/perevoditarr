"""Scenario DSL for simulator-driven tests (P1-T8).

Seed a library, advance time, flip settings, inject failures, and drive
Bazarr's worker loop against the Lingarr simulator.
"""

from datetime import timedelta

import httpx

from tests.simulators.bazarr import (
    BazarrSimulator,
    SimEpisode,
    SimMovie,
    SimSeries,
    SimSubtitle,
)
from tests.simulators.clock import SimClock
from tests.simulators.lingarr import LingarrSimulator


def asgi_client(app: object, base_url: str = "http://sim.test") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),  # pyright: ignore[reportArgumentType]
        base_url=base_url,
    )


class Scenario:
    def __init__(self) -> None:
        self.clock: SimClock = SimClock()
        self.lingarr: LingarrSimulator = LingarrSimulator(now=self.clock.now)
        self.bazarr: BazarrSimulator = BazarrSimulator(now=self.clock.now)
        self._lingarr_http: httpx.AsyncClient | None = None
        self._next_series_id: int = 0
        self._next_episode_id: int = 0
        self._next_movie_id: int = 0

    # ------------------------------------------------------------- seeding

    def seed_series(
        self,
        *,
        title: str | None = None,
        episode_count: int = 1,
        source_language: str = "en",
        missing_languages: tuple[str, ...] = ("da",),
        monitored: bool = True,
        ended: bool = False,
    ) -> SimSeries:
        self._next_series_id += 1
        series_id = self._next_series_id
        series = SimSeries(
            sonarr_series_id=series_id,
            title=title or f"Series {series_id}",
            monitored=monitored,
            ended=ended,
        )
        self.bazarr.series[series_id] = series
        for number in range(1, episode_count + 1):
            self._next_episode_id += 1
            episode_id = self._next_episode_id
            path = f"/media/series-{series_id}/s01e{number:02d}.mkv"
            self.bazarr.episodes[episode_id] = SimEpisode(
                sonarr_series_id=series_id,
                sonarr_episode_id=episode_id,
                title=f"Episode {number}",
                season=1,
                episode=number,
                monitored=monitored,
                path=path,
                subtitles=[
                    SimSubtitle(
                        code2=source_language, path=f"{path}.{source_language}.srt"
                    )
                ],
                missing=[(code, False, False) for code in missing_languages],
            )
        return series

    def seed_movie(
        self,
        *,
        title: str | None = None,
        source_language: str = "en",
        missing_languages: tuple[str, ...] = ("da",),
        monitored: bool = True,
    ) -> SimMovie:
        self._next_movie_id += 1
        movie_id = self._next_movie_id
        path = f"/media/movie-{movie_id}/movie.mkv"
        movie = SimMovie(
            radarr_id=movie_id,
            title=title or f"Movie {movie_id}",
            monitored=monitored,
            path=path,
            subtitles=[
                SimSubtitle(code2=source_language, path=f"{path}.{source_language}.srt")
            ],
            missing=[(code, False, False) for code in missing_languages],
        )
        self.bazarr.movies[movie_id] = movie
        return movie

    # ------------------------------------------------------------- control

    def advance_time(self, delta: timedelta) -> None:
        self.clock.advance(delta)

    def set_lingarr_setting(self, key: str, value: str) -> None:
        self.lingarr.set_setting(key, value)

    def inject_lingarr_failure(self, *, status_code: int = 500, count: int = 1) -> None:
        self.lingarr.inject_content_failure(status_code=status_code, count=count)

    async def process_jobs(self, limit: int | None = None) -> int:
        """Drive Bazarr's worker against the Lingarr simulator; returns count."""
        if self._lingarr_http is None:
            self._lingarr_http = asgi_client(
                self.lingarr.app, base_url="http://lingarr.test"
            )
        processed = 0
        while self.bazarr.jobs_pending and (limit is None or processed < limit):
            _ = await self.bazarr.process_next_job(self._lingarr_http)
            processed += 1
        return processed

    async def aclose(self) -> None:
        if self._lingarr_http is not None:
            await self._lingarr_http.aclose()
            self._lingarr_http = None
