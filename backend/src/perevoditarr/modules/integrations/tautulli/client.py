"""Tautulli watch-history client (P5-T1, FR-X2): read-only, retries=0.

Rides the shared pooled registry like every other integration. Tautulli auth
is an `apikey` query param (not a header), injected per request. Watch data is
a soft priority signal only (ADR-0007), so a flaky/unreachable Tautulli only
means "no boost", never a correctness fault.
"""

import msgspec
from httpx import AsyncClient, HTTPError, Response

from perevoditarr.core.errors import (
    PerevoditarrError,
    UpstreamError,
    UpstreamUnavailableError,
)
from perevoditarr.modules.integrations.tautulli.schemas import (
    HistoryEnvelope,
    ServerInfoEnvelope,
)
from perevoditarr.modules.integrations.watch import WatchActivity, WatchSourceProbe

type _Params = dict[str, str | int]


def _as_int(value: int | str | None) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        return int(digits) if digits else None
    return None


class TautulliClient:
    def __init__(self, http: AsyncClient, *, api_key: str) -> None:
        self.http: AsyncClient = http
        self.api_key: str = api_key

    async def _get(self, cmd: str, **extra: str | int) -> Response:
        params: _Params = {"apikey": self.api_key, "cmd": cmd, **extra}
        try:
            response = await self.http.get("/api/v2", params=params)
        except HTTPError as error:
            raise UpstreamUnavailableError(
                f"Tautulli request failed: {error}"
            ) from error
        if response.status_code != 200:
            raise UpstreamError(f"Tautulli cmd={cmd} returned {response.status_code}")
        return response

    def _decode[T](self, content: bytes, expected: type[T]) -> T:
        try:
            return msgspec.json.decode(content, type=expected)
        except msgspec.DecodeError as error:
            raise UpstreamError(f"Tautulli returned malformed JSON: {error}") from error

    async def probe(self) -> WatchSourceProbe:
        try:
            response = await self._get("get_server_info")
        except PerevoditarrError as error:
            return WatchSourceProbe(reachable=False, detail=str(error))
        envelope = self._decode(response.content, ServerInfoEnvelope)
        body = envelope.response
        if body.result != "success" or body.data is None:
            return WatchSourceProbe(
                reachable=False, detail=body.message or "Tautulli rejected the API key"
            )
        return WatchSourceProbe(
            reachable=True,
            identity=body.data.pms_name,
            version=body.data.pms_version,
        )

    async def fetch_activity(
        self, *, window_days: int, limit: int
    ) -> list[WatchActivity]:
        # get_history is time-descending; `limit` bounds the recent window we
        # aggregate. grouping=1 collapses consecutive plays into group_count.
        _ = window_days  # recency window is applied downstream by the aggregator
        response = await self._get(
            "get_history",
            length=limit,
            order_column="date",
            order_dir="desc",
            grouping=1,
        )
        envelope = self._decode(response.content, HistoryEnvelope)
        body = envelope.response
        if body.result != "success" or body.data is None:
            raise UpstreamError(body.message or "Tautulli get_history failed")
        activity: list[WatchActivity] = []
        for row in body.data.data:
            plays = max(1, row.group_count)
            if row.media_type == "episode":
                title = row.grandparent_title or row.full_title
                if not title:
                    continue
                activity.append(
                    WatchActivity(
                        media_type="show",
                        title=title,
                        last_watched_at=row.date,
                        play_count=plays,
                    )
                )
            elif row.media_type == "movie":
                title = row.title or row.full_title
                if not title:
                    continue
                activity.append(
                    WatchActivity(
                        media_type="movie",
                        title=title,
                        year=_as_int(row.year),
                        last_watched_at=row.date,
                        play_count=plays,
                    )
                )
        return activity
