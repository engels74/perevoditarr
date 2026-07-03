"""Jellyfin watch client (P5-T1, FR-X2): played-item playback data.

Read-only, retries=0, on the shared pooled registry. The
`Authorization: MediaBrowser Token="…"` header is baked on by the gateway.
Jellyfin scopes user data per user, so we resolve a user id (configured name/id
or the first user) then read played Episodes/Movies with their play counts and
last-played timestamps, aggregated to §6.5 title identity (ADR-0007)."""

from datetime import datetime

import msgspec
from httpx import AsyncClient, HTTPError, Response

from perevoditarr.core.errors import (
    PerevoditarrError,
    UpstreamError,
    UpstreamUnavailableError,
)
from perevoditarr.modules.integrations.jellyfin.schemas import (
    JellyfinItemsResponse,
    JellyfinSystemInfo,
    JellyfinUser,
)
from perevoditarr.modules.integrations.watch import WatchActivity, WatchSourceProbe

type _Params = dict[str, str | int]


def _epoch(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    # Jellyfin emits 7-digit fractional seconds; fromisoformat accepts at most 6,
    # so truncate the fractional block while keeping any timezone suffix.
    if "." in text:
        head, _, tail = text.partition(".")
        cut = 0
        while cut < len(tail) and tail[cut].isdigit():
            cut += 1
        frac, tz = tail[:cut][:6], tail[cut:]
        text = f"{head}.{frac}{tz}" if frac else f"{head}{tz}"
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None


class JellyfinClient:
    def __init__(self, http: AsyncClient, *, user: str | None = None) -> None:
        self.http: AsyncClient = http
        self.user: str | None = user

    async def _get(self, path: str, *, params: _Params | None = None) -> Response:
        try:
            response = await self.http.get(path, params=params)
        except HTTPError as error:
            raise UpstreamUnavailableError(
                f"Jellyfin request failed: {error}"
            ) from error
        if response.status_code != 200:
            raise UpstreamError(f"Jellyfin GET {path} returned {response.status_code}")
        return response

    def _decode[T](self, content: bytes, expected: type[T]) -> T:
        try:
            return msgspec.json.decode(content, type=expected)
        except msgspec.DecodeError as error:
            raise UpstreamError(f"Jellyfin returned malformed JSON: {error}") from error

    async def probe(self) -> WatchSourceProbe:
        try:
            response = await self._get("/System/Info")
        except PerevoditarrError as error:
            return WatchSourceProbe(reachable=False, detail=str(error))
        info = self._decode(response.content, JellyfinSystemInfo)
        return WatchSourceProbe(
            reachable=True, identity=info.server_name, version=info.version
        )

    async def _resolve_user_id(self) -> str | None:
        users = self._decode((await self._get("/Users")).content, list[JellyfinUser])
        if self.user:
            wanted = self.user.casefold()
            for candidate in users:
                if candidate.id == self.user or candidate.name.casefold() == wanted:
                    return candidate.id
        return users[0].id if users else None

    async def fetch_activity(
        self, *, window_days: int, limit: int
    ) -> list[WatchActivity]:
        _ = window_days  # recency window applied downstream by the aggregator
        user_id = await self._resolve_user_id()
        if user_id is None:
            raise UpstreamError("Jellyfin exposes no users for the configured API key")
        response = await self._get(
            "/Items",
            params={
                "userId": user_id,
                "IncludeItemTypes": "Episode,Movie",
                "Filters": "IsPlayed",
                "Recursive": "true",
                "SortBy": "DatePlayed",
                "SortOrder": "Descending",
                "Fields": "SeriesName,ProductionYear",
                "EnableUserData": "true",
                "Limit": limit,
            },
        )
        items = self._decode(response.content, JellyfinItemsResponse).items
        activity: list[WatchActivity] = []
        for item in items:
            plays = max(1, item.user_data.play_count)
            watched_at = _epoch(item.user_data.last_played_date)
            if item.type == "Episode":
                if not item.series_name:
                    continue
                activity.append(
                    WatchActivity(
                        media_type="show",
                        title=item.series_name,
                        last_watched_at=watched_at,
                        play_count=plays,
                    )
                )
            elif item.type == "Movie" and item.name:
                activity.append(
                    WatchActivity(
                        media_type="movie",
                        title=item.name,
                        year=item.production_year,
                        last_watched_at=watched_at,
                        play_count=plays,
                    )
                )
        return activity
