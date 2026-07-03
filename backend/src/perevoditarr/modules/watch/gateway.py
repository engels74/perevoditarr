"""Watch client gateway (P5-T1): source rows -> pooled integration clients.

Mirrors instances/gateway.py. Each source type gets its auth wired the way that
API expects (Tautulli: apikey query param; Plex: X-Plex-Token header; Jellyfin:
MediaBrowser Token header) on a client from the shared pooled registry
(retries=0). Tests swap this for a fake gateway.
"""

from litestar.datastructures import State

from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.modules.integrations.jellyfin import JellyfinClient
from perevoditarr.modules.integrations.plex import PlexClient
from perevoditarr.modules.integrations.tautulli import TautulliClient
from perevoditarr.modules.integrations.watch import WatchSourceClient, WatchSourceType
from perevoditarr.modules.watch.schemas import WatchSourceConfig


class WatchGateway:
    def __init__(self, registry: HttpClientRegistry) -> None:
        self.registry: HttpClientRegistry = registry

    def client(
        self,
        *,
        source_type: WatchSourceType,
        url: str,
        credential: str,
        config: WatchSourceConfig,
    ) -> WatchSourceClient:
        if source_type == "tautulli":
            return TautulliClient(self.registry.get(url), api_key=credential)
        if source_type == "plex":
            http = self.registry.get(
                url,
                headers={"X-Plex-Token": credential, "Accept": "application/json"},
            )
            return PlexClient(http, include_watchlist=config.include_watchlist)
        http = self.registry.get(
            url, headers={"Authorization": f'MediaBrowser Token="{credential}"'}
        )
        return JellyfinClient(http, user=config.jellyfin_user)


def provide_watch_gateway(state: State) -> WatchGateway:
    gateway: object = state.get("watch_gateway")
    if isinstance(gateway, WatchGateway):
        return gateway
    registry: object = state.get("http")
    if not isinstance(registry, HttpClientRegistry):
        raise RuntimeError("HTTP client registry is not initialized")
    built = WatchGateway(registry)
    state["watch_gateway"] = built
    return built
