"""Client gateway: instance records -> pooled integration clients (P1-T4).

Tests swap this for a simulator-backed gateway via app.state.
"""

from litestar.datastructures import State

from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.bazarr.client import (
    API_KEY_HEADER as BAZARR_API_KEY_HEADER,
)
from perevoditarr.modules.integrations.lingarr import LingarrClient
from perevoditarr.modules.integrations.lingarr.client import (
    API_KEY_HEADER as LINGARR_API_KEY_HEADER,
)


class InstanceGateway:
    def __init__(self, registry: HttpClientRegistry) -> None:
        self.registry: HttpClientRegistry = registry

    def bazarr(self, url: str, api_key: str) -> BazarrClient:
        return BazarrClient(
            self.registry.get(url, headers={BAZARR_API_KEY_HEADER: api_key})
        )

    def lingarr(self, url: str, api_key: str | None) -> LingarrClient:
        headers = {LINGARR_API_KEY_HEADER: api_key} if api_key else None
        return LingarrClient(self.registry.get(url, headers=headers))


def provide_gateway(state: State) -> InstanceGateway:
    gateway: object = state.get("gateway")
    if isinstance(gateway, InstanceGateway):
        return gateway
    registry: object = state.get("http")
    if not isinstance(registry, HttpClientRegistry):
        raise RuntimeError("HTTP client registry is not initialized")
    built = InstanceGateway(registry)
    state["gateway"] = built
    return built
