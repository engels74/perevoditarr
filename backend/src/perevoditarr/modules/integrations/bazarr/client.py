"""Bazarr API client (P1-T3).

Rides a long-lived pooled httpx.AsyncClient (X-API-KEY header, retries=0 —
PRD §6.3). Perevoditarr's single ecosystem write surface is translate()
(PRD §7.5); everything else is read-only.
"""

import msgspec
from httpx import AsyncClient, HTTPError, Response

from perevoditarr.core.errors import (
    UnsupportedVersionError,
    UpstreamError,
    UpstreamUnavailableError,
)
from perevoditarr.modules.integrations.bazarr.schemas import (
    EpisodeHistoryPage,
    EpisodeItem,
    EpisodesResponse,
    JobItem,
    JobsResponse,
    LanguagesProfile,
    MovieHistoryPage,
    MoviesPage,
    SeriesPage,
    SystemSettings,
    SystemStatusData,
    SystemStatusResponse,
    WantedEpisodesPage,
    WantedMoviesPage,
)

type _Params = dict[str, str | int | bool | list[int]]

MIN_BAZARR_VERSION = (1, 5, 6)  # FR-I1 / PRD §6.1

API_KEY_HEADER = "X-API-KEY"


def parse_version(raw: str) -> tuple[int, ...]:
    """Parse '1.5.6', 'v1.5.6-beta.4' or '1.5.6 by maintainer' into a tuple."""
    cleaned = raw.strip().removeprefix("v").split(" ")[0].split("-")[0]
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    if not parts:
        raise UpstreamError(f"unparseable Bazarr version string: {raw!r}")
    return tuple(parts)


def ensure_supported_version(raw: str) -> tuple[int, ...]:
    version = parse_version(raw)
    if version < MIN_BAZARR_VERSION:
        minimum = ".".join(str(p) for p in MIN_BAZARR_VERSION)
        raise UnsupportedVersionError(
            f"Bazarr {raw} is not supported: Perevoditarr requires >= {minimum} "
            "(asynchronous jobs queue; PRD §6.1)"
        )
    return version


class BazarrClient:
    def __init__(self, http: AsyncClient) -> None:
        self.http: AsyncClient = http

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: _Params | None = None,
        ok_statuses: tuple[int, ...] = (200,),
    ) -> Response:
        try:
            response = await self.http.request(method, path, params=params)
        except HTTPError as error:
            raise UpstreamUnavailableError(f"Bazarr request failed: {error}") from error
        if response.status_code not in ok_statuses:
            raise UpstreamError(
                f"Bazarr {method} {path} returned {response.status_code}"
            )
        return response

    # --- system ----------------------------------------------------------

    async def system_status(self) -> SystemStatusData:
        response = await self._request("GET", "/api/system/status")
        return msgspec.json.decode(response.content, type=SystemStatusResponse).data

    async def system_settings(self) -> SystemSettings:
        response = await self._request("GET", "/api/system/settings")
        return msgspec.json.decode(response.content, type=SystemSettings)

    async def languages_profiles(self) -> list[LanguagesProfile]:
        response = await self._request("GET", "/api/system/languages/profiles")
        return msgspec.json.decode(response.content, type=list[LanguagesProfile])

    # --- library ---------------------------------------------------------

    async def series(self, *, start: int = 0, length: int = -1) -> SeriesPage:
        response = await self._request(
            "GET", "/api/series", params={"start": start, "length": length}
        )
        return msgspec.json.decode(response.content, type=SeriesPage)

    async def episodes(self, *, series_ids: list[int]) -> list[EpisodeItem]:
        response = await self._request(
            "GET", "/api/episodes", params={"seriesid[]": series_ids}
        )
        return msgspec.json.decode(response.content, type=EpisodesResponse).data

    async def movies(self, *, start: int = 0, length: int = -1) -> MoviesPage:
        response = await self._request(
            "GET", "/api/movies", params={"start": start, "length": length}
        )
        return msgspec.json.decode(response.content, type=MoviesPage)

    async def wanted_episodes(
        self, *, start: int = 0, length: int = -1
    ) -> WantedEpisodesPage:
        response = await self._request(
            "GET", "/api/episodes/wanted", params={"start": start, "length": length}
        )
        return msgspec.json.decode(response.content, type=WantedEpisodesPage)

    async def wanted_movies(
        self, *, start: int = 0, length: int = -1
    ) -> WantedMoviesPage:
        response = await self._request(
            "GET", "/api/movies/wanted", params={"start": start, "length": length}
        )
        return msgspec.json.decode(response.content, type=WantedMoviesPage)

    # --- history (action == 6 => translated; durable evidence, §6.8) ------

    async def episodes_history(
        self, *, start: int = 0, length: int = -1, episode_id: int | None = None
    ) -> EpisodeHistoryPage:
        params: _Params = {"start": start, "length": length}
        if episode_id is not None:
            params["episodeid"] = episode_id
        response = await self._request("GET", "/api/episodes/history", params=params)
        return msgspec.json.decode(response.content, type=EpisodeHistoryPage)

    async def movies_history(
        self, *, start: int = 0, length: int = -1, radarr_id: int | None = None
    ) -> MovieHistoryPage:
        params: _Params = {"start": start, "length": length}
        if radarr_id is not None:
            params["radarrid"] = radarr_id
        response = await self._request("GET", "/api/movies/history", params=params)
        return msgspec.json.decode(response.content, type=MovieHistoryPage)

    # --- jobs queue: transient dispatch buffer + backpressure only (§6.2) --

    async def jobs(self, *, status: str | None = None) -> list[JobItem]:
        params: _Params = {}
        if status is not None:
            params["status"] = status
        response = await self._request("GET", "/api/system/jobs", params=params)
        return msgspec.json.decode(response.content, type=JobsResponse).data

    async def delete_job(self, job_id: int) -> None:
        _ = await self._request(
            "DELETE", "/api/system/jobs", params={"id": job_id}, ok_statuses=(204,)
        )

    # --- the single ecosystem write surface (PRD §7.5) --------------------

    async def translate(
        self,
        *,
        language: str,
        subtitle_path: str,
        media_type: str,  # "episode" | "movie"
        media_id: int,  # sonarrEpisodeId | radarrId
        forced: bool = False,
        hi: bool = False,
        original_format: bool = False,
    ) -> None:
        """Enqueue a translation in Bazarr (async 204; NO job id — §6.2)."""
        _ = await self._request(
            "PATCH",
            "/api/subtitles",
            params={
                "action": "translate",
                "language": language,
                "path": subtitle_path,
                "type": media_type,
                "id": media_id,
                # Bazarr parses these as literal "True"/"False" strings.
                "forced": "True" if forced else "False",
                "hi": "True" if hi else "False",
                "original_format": "True" if original_format else "False",
            },
            ok_statuses=(204,),
        )
