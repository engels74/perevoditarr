"""In-process Bazarr simulator (P1-T8).

Implements the consumed surface with the researched v1.5.6 semantics:
- translate PATCH enqueues an in-memory job and returns 204 with NO job id
- the shared jobs queue keeps failed/completed capped at 10, all in-memory
- the Bazarr→Lingarr call converts language codes (zh/zt/pb) and sends
  arrMediaId = sonarr SERIES id + show title for episodes (§6.5)
- an empty-array Lingarr response is treated as success and the file is
  "saved" anyway — the §6.4 corruption trap, tracked in corrupted_items
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, cast

import httpx
from litestar import Litestar, MediaType, Request, Response, get
from litestar.datastructures import State
from litestar.handlers import delete as http_delete
from litestar.handlers import patch as http_patch

from tests.support import json_list

type _Req = Request[object, object, State]

LANGUAGE_CODE_CONVERT = {"zh": "zh-CN", "zt": "zh-TW", "pb": "pt-BR"}

_LANGUAGE_NAMES = {
    "en": "English",
    "da": "Danish",
    "de": "German",
    "ja": "Japanese",
    "zh": "Chinese",
    "zt": "Chinese Traditional",
    "pb": "Brazilian Portuguese",
}


def _language_payload(
    code2: str, forced: bool = False, hi: bool = False
) -> dict[str, object]:
    return {
        "name": _LANGUAGE_NAMES.get(code2, code2),
        "code2": code2,
        "code3": code2 + "x",  # shape fidelity only; code3 is unused by clients
        "forced": forced,
        "hi": hi,
    }


@dataclass
class SimSubtitle:
    code2: str
    path: str | None
    forced: bool = False
    hi: bool = False

    def payload(self) -> dict[str, object]:
        data = _language_payload(self.code2, self.forced, self.hi)
        data["path"] = self.path
        data["file_size"] = 1000 if self.path else 0
        return data


@dataclass
class SimEpisode:
    sonarr_series_id: int
    sonarr_episode_id: int
    title: str
    season: int
    episode: int
    monitored: bool = True
    path: str = ""
    subtitles: list[SimSubtitle] = field(default_factory=list)
    # (code2, forced, hi) triples still wanted by Bazarr
    missing: list[tuple[str, bool, bool]] = field(default_factory=list)


@dataclass
class SimSeries:
    sonarr_series_id: int
    title: str
    monitored: bool = True
    ended: bool = False
    profile_id: int | None = 1
    series_type: str = "standard"
    tags: list[str] = field(default_factory=list)


@dataclass
class SimMovie:
    radarr_id: int
    title: str
    monitored: bool = True
    profile_id: int | None = 1
    path: str = ""
    subtitles: list[SimSubtitle] = field(default_factory=list)
    missing: list[tuple[str, bool, bool]] = field(default_factory=list)


@dataclass
class SimJob:
    job_id: int
    job_name: str
    status: Literal["pending", "running", "failed", "completed"]
    payload: dict[str, object] = field(default_factory=dict)
    progress_value: int = 0
    progress_max: int = 0
    progress_message: str = ""

    def wire(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_name": self.job_name,
            "status": self.status,
            "last_run_time": "",
            "is_progress": True,
            "is_signalr": False,
            "progress_value": self.progress_value,
            "progress_max": self.progress_max,
            "progress_message": self.progress_message,
        }


class BazarrSimulator:
    def __init__(
        self,
        *,
        api_key: str = "bazarr-key",
        version: str = "1.5.6",
        lingarr_url: str = "http://lingarr.test",
        lingarr_token: str = "lingarr-key",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.api_key: str = api_key
        self.version: str = version
        self.concurrent_jobs: int = 4
        self.upgrade_manual: bool = True
        self.translator_type: str = "lingarr"
        self.lingarr_url: str = lingarr_url
        self.lingarr_token: str = lingarr_token
        self.now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))

        self.series: dict[int, SimSeries] = {}
        self.episodes: dict[int, SimEpisode] = {}
        self.movies: dict[int, SimMovie] = {}
        self.profiles: list[dict[str, object]] = [
            {
                "profileId": 1,
                "name": "Default",
                "cutoff": None,
                "items": [
                    {"id": 1, "language": "en", "hi": "False", "forced": "False"},
                    {"id": 2, "language": "da", "hi": "False", "forced": "False"},
                ],
                "mustContain": [],
                "mustNotContain": [],
                "originalFormat": False,
                "tag": None,
            }
        ]

        self._next_job_id: int = 0
        self.jobs_pending: deque[SimJob] = deque()
        self.jobs_running: deque[SimJob] = deque()
        self.jobs_failed: deque[SimJob] = deque(maxlen=10)  # §6.2 cap
        self.jobs_completed: deque[SimJob] = deque(maxlen=10)  # §6.2 cap

        self.episode_history: list[dict[str, object]] = []
        self.movie_history: list[dict[str, object]] = []
        # §6.4 trap evidence: items "saved" from an empty Lingarr response.
        self.corrupted_items: list[dict[str, object]] = []

        self.app: Litestar = self._build_app()

    # ------------------------------------------------------------------ app

    def _authorized(self, request: _Req) -> bool:
        header = request.headers.get("X-API-KEY")
        query = request.query_params.get("apikey")
        return self.api_key in (header, query)

    def _build_app(self) -> Litestar:
        sim = self

        def guard(request: _Req) -> Response[str] | None:
            if not sim._authorized(request):
                return Response(
                    "Unauthorized", status_code=401, media_type=MediaType.TEXT
                )
            return None

        @get("/api/system/status", sync_to_thread=False)
        def system_status(request: _Req) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            return Response(
                {
                    "data": {
                        "bazarr_version": sim.version,
                        "sonarr_version": "4.0.0",
                        "radarr_version": "5.0.0",
                        "operating_system": "SimOS",
                        "python_version": "3.14.0",
                        "timezone": "UTC",
                    }
                }
            )

        @get("/api/system/settings", sync_to_thread=False)
        def system_settings(request: _Req) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            return Response(
                {
                    "general": {
                        "concurrent_jobs": sim.concurrent_jobs,
                        "upgrade_manual": sim.upgrade_manual,
                        "use_sonarr": True,
                        "use_radarr": True,
                    },
                    "translator": {
                        "translator_type": sim.translator_type,
                        "lingarr_url": sim.lingarr_url,
                        "lingarr_token": sim.lingarr_token,
                    },
                }
            )

        @get("/api/system/languages/profiles", sync_to_thread=False)
        def languages_profiles(request: _Req) -> Response[list[dict[str, object]]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            return Response(sim.profiles)

        @get("/api/series", sync_to_thread=False)
        def series_list(
            request: _Req, start: int = 0, length: int = -1
        ) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            rows: list[dict[str, object]] = [
                {
                    "sonarrSeriesId": s.sonarr_series_id,
                    "title": s.title,
                    "year": "2024",
                    "monitored": s.monitored,
                    "ended": s.ended,
                    "profileId": s.profile_id,
                    "episodeFileCount": sum(
                        1
                        for e in sim.episodes.values()
                        if e.sonarr_series_id == s.sonarr_series_id
                    ),
                    "episodeMissingCount": sum(
                        len(e.missing)
                        for e in sim.episodes.values()
                        if e.sonarr_series_id == s.sonarr_series_id
                    ),
                    "seriesType": s.series_type,
                    "tags": s.tags,
                }
                for s in sorted(sim.series.values(), key=lambda s: s.sonarr_series_id)
            ]
            return Response(_paged(rows, start, length))

        @get("/api/episodes", sync_to_thread=False)
        def episodes_list(request: _Req) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            wanted_series = {
                int(v)
                for v in cast(
                    "list[str]", request.query_params.getall("seriesid[]", [])
                )
            }
            rows = [
                {
                    "sonarrSeriesId": e.sonarr_series_id,
                    "sonarrEpisodeId": e.sonarr_episode_id,
                    "title": e.title,
                    "season": e.season,
                    "episode": e.episode,
                    "monitored": e.monitored,
                    "path": e.path,
                    "subtitles": [s.payload() for s in e.subtitles],
                    "missing_subtitles": [
                        _language_payload(c, f, h) for (c, f, h) in e.missing
                    ],
                }
                for e in sorted(
                    sim.episodes.values(), key=lambda e: e.sonarr_episode_id
                )
                if not wanted_series or e.sonarr_series_id in wanted_series
            ]
            return Response({"data": rows})

        @get("/api/movies", sync_to_thread=False)
        def movies_list(
            request: _Req, start: int = 0, length: int = -1
        ) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            wanted_movies = {
                int(v)
                for v in cast(
                    "list[str]", request.query_params.getall("radarrid[]", [])
                )
            }
            rows: list[dict[str, object]] = [
                {
                    "radarrId": m.radarr_id,
                    "title": m.title,
                    "year": "2024",
                    "monitored": m.monitored,
                    "path": m.path,
                    "profileId": m.profile_id,
                    "subtitles": [s.payload() for s in m.subtitles],
                    "missing_subtitles": [
                        _language_payload(c, f, h) for (c, f, h) in m.missing
                    ],
                    "tags": [],
                }
                for m in sorted(sim.movies.values(), key=lambda m: m.radarr_id)
                if not wanted_movies or m.radarr_id in wanted_movies
            ]
            return Response(_paged(rows, start, length))

        @get("/api/episodes/wanted", sync_to_thread=False)
        def wanted_episodes(
            request: _Req, start: int = 0, length: int = -1
        ) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            rows: list[dict[str, object]] = []
            for e in sorted(sim.episodes.values(), key=lambda e: -e.sonarr_episode_id):
                if not e.missing:
                    continue
                series = sim.series.get(e.sonarr_series_id)
                rows.append(
                    {
                        "seriesTitle": series.title if series else "",
                        "episode_number": f"{e.season}x{e.episode}",
                        "episodeTitle": e.title,
                        "missing_subtitles": [
                            _language_payload(c, f, h) for (c, f, h) in e.missing
                        ],
                        "sonarrSeriesId": e.sonarr_series_id,
                        "sonarrEpisodeId": e.sonarr_episode_id,
                        "sceneName": None,
                        "tags": series.tags if series else [],
                        "seriesType": series.series_type if series else "standard",
                    }
                )
            return Response(_paged(rows, start, length))

        @get("/api/movies/wanted", sync_to_thread=False)
        def wanted_movies(
            request: _Req, start: int = 0, length: int = -1
        ) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            rows: list[dict[str, object]] = [
                {
                    "title": m.title,
                    "missing_subtitles": [
                        _language_payload(c, f, h) for (c, f, h) in m.missing
                    ],
                    "radarrId": m.radarr_id,
                    "sceneName": None,
                    "tags": [],
                }
                for m in sorted(sim.movies.values(), key=lambda m: -m.radarr_id)
                if m.missing
            ]
            return Response(_paged(rows, start, length))

        @get("/api/episodes/history", sync_to_thread=False)
        def episodes_history(
            request: _Req,
            start: int = 0,
            length: int = -1,
            episodeid: int | None = None,
        ) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            rows = [
                r
                for r in reversed(sim.episode_history)
                if episodeid is None or r["sonarrEpisodeId"] == episodeid
            ]
            return Response(_paged(rows, start, length))

        @get("/api/movies/history", sync_to_thread=False)
        def movies_history(
            request: _Req,
            start: int = 0,
            length: int = -1,
            radarrid: int | None = None,
        ) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            rows = [
                r
                for r in reversed(sim.movie_history)
                if radarrid is None or r["radarrId"] == radarrid
            ]
            return Response(_paged(rows, start, length))

        @get("/api/system/jobs", sync_to_thread=False)
        def jobs_list(
            request: _Req, status: str | None = None, id: int | None = None
        ) -> Response[dict[str, object]]:
            if (denied := guard(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            jobs = sim.all_jobs()
            if id is not None:
                jobs = [j for j in jobs if j.job_id == id]
            if status is not None:
                jobs = [j for j in jobs if j.status == status]
            return Response({"data": [j.wire() for j in jobs]})

        @http_delete("/api/system/jobs", status_code=204, sync_to_thread=False)
        def jobs_delete(request: _Req, id: int) -> None:
            if not sim._authorized(request):
                return
            sim.jobs_pending = deque(j for j in sim.jobs_pending if j.job_id != id)

        @http_patch("/api/subtitles", sync_to_thread=False)
        def subtitles_patch(request: _Req) -> Response[object]:
            if not sim._authorized(request):
                return Response(
                    "Unauthorized", status_code=401, media_type=MediaType.TEXT
                )
            params = request.query_params
            action = params.get("action")
            if action != "translate":
                return Response(
                    "unsupported action in simulator",
                    status_code=400,
                    media_type=MediaType.TEXT,
                )
            media_type = params.get("type")
            media_id = int(str(params.get("id")))
            language = str(params.get("language"))
            path = str(params.get("path"))
            forced = str(params.get("forced")) == "True"
            hi = str(params.get("hi")) == "True"

            if media_type == "episode":
                episode = sim.episodes.get(media_id)
                if episode is None:
                    return Response(
                        "Episode not found", status_code=404, media_type=MediaType.TEXT
                    )
                source = _match_source(episode.subtitles, path)
            else:
                movie = sim.movies.get(media_id)
                if movie is None:
                    return Response(
                        "Movie not found", status_code=404, media_type=MediaType.TEXT
                    )
                source = _match_source(movie.subtitles, path)
            if source is None:
                return Response(
                    "Invalid source language code",
                    status_code=400,
                    media_type=MediaType.TEXT,
                )

            # Async enqueue, 204, no job id in the response (§6.2).
            sim._next_job_id += 1
            job = SimJob(
                job_id=sim._next_job_id,
                job_name=(
                    f"Translating from {source.code2.upper()} to {language.upper()} "
                    "using Lingarr"
                ),
                status="pending",
                payload={
                    "media_type": media_type,
                    "media_id": media_id,
                    "from_lang": source.code2,
                    "to_lang": language,
                    "forced": forced,
                    "hi": hi,
                    "path": path,
                },
            )
            sim.jobs_pending.append(job)
            return Response(None, status_code=204)

        return Litestar(
            route_handlers=[
                system_status,
                system_settings,
                languages_profiles,
                series_list,
                episodes_list,
                movies_list,
                wanted_episodes,
                wanted_movies,
                episodes_history,
                movies_history,
                jobs_list,
                jobs_delete,
                subtitles_patch,
            ],
            openapi_config=None,
        )

    # ------------------------------------------------------------- worker

    def all_jobs(self) -> list[SimJob]:
        return (
            list(self.jobs_pending)
            + list(self.jobs_running)
            + list(self.jobs_failed)
            + list(self.jobs_completed)
        )

    async def process_next_job(self, lingarr_http: httpx.AsyncClient) -> SimJob | None:
        """Run one queued translate job the way Bazarr's worker would (§6.3-§6.5).

        The §6.4 trap is faithful: an empty Lingarr array still 'saves' the
        file and logs history action 6; the item lands in corrupted_items.
        """
        if not self.jobs_pending:
            return None
        job = self.jobs_pending.popleft()
        job.status = "running"
        self.jobs_running.append(job)

        payload = job.payload
        media_type = str(payload["media_type"])
        media_id = int(str(payload["media_id"]))
        from_lang = str(payload["from_lang"])
        to_lang = str(payload["to_lang"])

        if media_type == "episode":
            episode = self.episodes[media_id]
            series = self.series[episode.sonarr_series_id]
            arr_media_id = episode.sonarr_series_id  # §6.5: SERIES id
            title = series.title  # §6.5: show title only
            api_media_type = "Episode"
        else:
            movie = self.movies[media_id]
            arr_media_id = movie.radarr_id
            title = movie.title
            api_media_type = "Movie"

        body = {
            "arrMediaId": arr_media_id,
            "title": title,
            "sourceLanguage": LANGUAGE_CODE_CONVERT.get(from_lang, from_lang),
            "targetLanguage": LANGUAGE_CODE_CONVERT.get(to_lang, to_lang),
            "mediaType": api_media_type,
            "lines": [{"position": 0, "line": "Hello world"}],
        }
        headers = {"X-Api-Key": self.lingarr_token} if self.lingarr_token else {}
        try:
            response = await lingarr_http.post(
                "/api/translate/content", json=body, headers=headers
            )
        except httpx.HTTPError:
            self._finish_job(job, "failed")
            return job
        if response.status_code != 200:
            self._finish_job(job, "failed")
            return job

        lines = json_list(response)
        self._save_translated(media_type, media_id, to_lang, payload, empty=not lines)
        job.job_name = job.job_name.replace("Translating", "Translated", 1)
        self._finish_job(job, "completed")
        return job

    def _finish_job(self, job: SimJob, status: Literal["failed", "completed"]) -> None:
        if job in self.jobs_running:
            self.jobs_running.remove(job)
        job.status = status
        (self.jobs_failed if status == "failed" else self.jobs_completed).append(job)

    def _save_translated(
        self,
        media_type: str,
        media_id: int,
        to_lang: str,
        payload: dict[str, object],
        *,
        empty: bool,
    ) -> None:
        forced = bool(payload["forced"])
        hi = bool(payload["hi"])
        dest_path = f"{payload['path']}.{to_lang}.srt"
        subtitle = SimSubtitle(code2=to_lang, path=dest_path, forced=forced, hi=hi)
        timestamp = self.now().isoformat()
        if media_type == "episode":
            episode = self.episodes[media_id]
            episode.subtitles.append(subtitle)
            episode.missing = [m for m in episode.missing if m != (to_lang, forced, hi)]
            self.episode_history.append(
                {
                    "action": 6,
                    "timestamp": timestamp,
                    "sonarrSeriesId": episode.sonarr_series_id,
                    "sonarrEpisodeId": episode.sonarr_episode_id,
                    "language": _language_payload(to_lang, forced, hi),
                    "subtitles_path": dest_path,
                    "description": "translated using Lingarr",
                    "upgradable": True,
                }
            )
        else:
            movie = self.movies[media_id]
            movie.subtitles.append(subtitle)
            movie.missing = [m for m in movie.missing if m != (to_lang, forced, hi)]
            self.movie_history.append(
                {
                    "action": 6,
                    "timestamp": timestamp,
                    "radarrId": movie.radarr_id,
                    "title": movie.title,
                    "language": _language_payload(to_lang, forced, hi),
                    "subtitles_path": dest_path,
                    "description": "translated using Lingarr",
                    "upgradable": True,
                }
            )
        if empty:
            # §6.4: zero translated lines, file written anyway => silent
            # corruption, indistinguishable from success upstream.
            self.corrupted_items.append(
                {"media_type": media_type, "media_id": media_id, "language": to_lang}
            )


def _paged(rows: list[dict[str, object]], start: int, length: int) -> dict[str, object]:
    total = len(rows)
    window = rows[start : start + length] if length > 0 else rows
    return {"data": window, "total": total}


def _match_source(subtitles: list[SimSubtitle], path: str) -> SimSubtitle | None:
    import os

    basename = os.path.basename(path)
    for subtitle in subtitles:
        if subtitle.path and os.path.basename(subtitle.path) == basename:
            return subtitle
    return None
