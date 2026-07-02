"""Long-lived outbound HTTP clients, one per external system (P1-T1).

Transport-level retries are banned everywhere (PRD §6.3 / FR-DR9): Bazarr
already retries 3x toward Lingarr, so any retry here multiplies provider
spend. Retry semantics live at intent level only. build_transport() is the
single seam the FR-DR9 self-check and the P3-T6 CI test assert against.
"""

import hashlib
from collections.abc import Mapping

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
DEFAULT_LIMITS = httpx.Limits(
    max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0
)


def build_transport() -> httpx.AsyncHTTPTransport:
    return httpx.AsyncHTTPTransport(retries=0)


class HttpClientRegistry:
    """Pooled clients keyed by (base URL, credential digest).

    Created in the app lifespan, stored on app.state, closed on shutdown —
    never per-request. Keys are hashed so API keys never appear in reprs.
    """

    def __init__(
        self,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        limits: httpx.Limits = DEFAULT_LIMITS,
    ) -> None:
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._timeout: httpx.Timeout = timeout
        self._limits: httpx.Limits = limits

    def get(
        self, base_url: str, *, headers: Mapping[str, str] | None = None
    ) -> httpx.AsyncClient:
        key = self._key(base_url, headers)
        client = self._clients.get(key)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(
                base_url=base_url,
                headers=dict(headers) if headers else None,
                timeout=self._timeout,
                limits=self._limits,
                transport=build_transport(),
            )
            self._clients[key] = client
        return client

    async def aclose(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()

    @staticmethod
    def _key(base_url: str, headers: Mapping[str, str] | None) -> str:
        digest = hashlib.sha256(base_url.encode())
        for name, value in sorted((headers or {}).items()):
            digest.update(f"\x00{name}\x1f{value}".encode())
        return digest.hexdigest()
