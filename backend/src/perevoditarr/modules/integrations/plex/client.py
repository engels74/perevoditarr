"""Plex watch client (P5-T1, FR-X2): server watch history + account watchlist.

Read-only, retries=0, on the shared pooled registry. The X-Plex-Token and
Accept:application/json headers are baked onto the client by the gateway.
History comes from the local server; the watchlist lives on Plex's online
account service (discover.provider.plex.tv) and is best-effort — a server-scoped
token simply yields no watchlist, which is fine (ADR-0007)."""

import msgspec
from httpx import AsyncClient, HTTPError, Response

from perevoditarr.core.errors import (
    PerevoditarrError,
    UpstreamError,
    UpstreamUnavailableError,
)
from perevoditarr.modules.integrations.plex.schemas import (
    PlexEnvelope,
    PlexMetadata,
    PlexRootEnvelope,
)
from perevoditarr.modules.integrations.watch import WatchActivity, WatchSourceProbe

_DISCOVER_WATCHLIST = "https://discover.provider.plex.tv/library/sections/watchlist/all"

type _Params = dict[str, str | int]


class PlexClient:
    def __init__(self, http: AsyncClient, *, include_watchlist: bool = True) -> None:
        self.http: AsyncClient = http
        self.include_watchlist: bool = include_watchlist

    async def _get(self, url: str, *, params: _Params | None = None) -> Response:
        try:
            response = await self.http.get(url, params=params)
        except HTTPError as error:
            raise UpstreamUnavailableError(f"Plex request failed: {error}") from error
        if response.status_code != 200:
            raise UpstreamError(f"Plex GET {url} returned {response.status_code}")
        return response

    def _decode[T](self, content: bytes, expected: type[T]) -> T:
        try:
            return msgspec.json.decode(content, type=expected)
        except msgspec.DecodeError as error:
            raise UpstreamError(f"Plex returned malformed JSON: {error}") from error

    async def probe(self) -> WatchSourceProbe:
        try:
            response = await self._get("/")
        except PerevoditarrError as error:
            return WatchSourceProbe(reachable=False, detail=str(error))
        container = self._decode(response.content, PlexRootEnvelope).media_container
        return WatchSourceProbe(
            reachable=True,
            identity=container.friendly_name,
            version=container.version,
        )

    async def fetch_activity(
        self, *, window_days: int, limit: int
    ) -> list[WatchActivity]:
        _ = window_days  # recency window applied downstream by the aggregator
        response = await self._get(
            "/status/sessions/history/all",
            params={
                "sort": "viewedAt:desc",
                "X-Plex-Container-Start": 0,
                "X-Plex-Container-Size": limit,
            },
        )
        container = self._decode(response.content, PlexEnvelope).media_container
        activity: list[WatchActivity] = [
            item
            for meta in container.metadata
            if (item := _history_activity(meta)) is not None
        ]
        if self.include_watchlist:
            activity.extend(await self._watchlist(limit))
        return activity

    async def _watchlist(self, limit: int) -> list[WatchActivity]:
        try:
            response = await self._get(
                _DISCOVER_WATCHLIST,
                params={
                    "includeCollections": 1,
                    "includeExternalMedia": 1,
                    "X-Plex-Container-Size": limit,
                },
            )
        except PerevoditarrError:
            # Best-effort: a server-scoped token cannot reach the account
            # watchlist. History alone still boosts (ADR-0007).
            return []
        container = self._decode(response.content, PlexEnvelope).media_container
        return [
            item
            for meta in container.metadata
            if (item := _watchlist_activity(meta)) is not None
        ]


def _history_activity(meta: PlexMetadata) -> WatchActivity | None:
    if meta.type == "episode":
        title = meta.grandparent_title
        if not title:
            return None
        return WatchActivity(
            media_type="show", title=title, last_watched_at=meta.viewed_at, play_count=1
        )
    if meta.type == "movie" and meta.title:
        return WatchActivity(
            media_type="movie",
            title=meta.title,
            year=meta.year,
            last_watched_at=meta.viewed_at,
            play_count=1,
        )
    return None


def _watchlist_activity(meta: PlexMetadata) -> WatchActivity | None:
    if not meta.title:
        return None
    if meta.type == "show":
        return WatchActivity(media_type="show", title=meta.title, watchlisted=True)
    if meta.type == "movie":
        return WatchActivity(
            media_type="movie", title=meta.title, year=meta.year, watchlisted=True
        )
    return None
