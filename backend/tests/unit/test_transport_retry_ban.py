"""Transport-retry ban (P3-T6, FR-DR9 / PRD §6.3).

Bazarr already retries 3x toward Lingarr; any transport-level retry in
Perevoditarr's own clients would multiply provider spend up to 9x per failure.
Retry semantics live at the intent level only. These tests are the FR-DR9
self-check: `build_transport()` is the single transport factory and disables
retries, every pooled client uses it, and no module smuggles in its own
retry-enabled transport.
"""

import re
from pathlib import Path

import httpx

from perevoditarr.core.http import HttpClientRegistry, build_transport

_SRC = Path(__file__).resolve().parents[2] / "src" / "perevoditarr"


def _pool_retries(transport: httpx.AsyncHTTPTransport) -> int:
    return transport._pool._retries  # pyright: ignore[reportPrivateUsage]  # asserting httpx internals


def test_build_transport_disables_retries() -> None:
    assert _pool_retries(build_transport()) == 0


async def test_pooled_clients_disable_retries() -> None:
    registry = HttpClientRegistry()
    try:
        client = registry.get("http://bazarr.test", headers={"X-API-KEY": "k"})
        transport = client._transport  # pyright: ignore[reportPrivateUsage]  # asserting httpx internals
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        assert _pool_retries(transport) == 0
    finally:
        await registry.aclose()


def test_no_module_enables_transport_retries() -> None:
    # Every AsyncHTTPTransport in the source must pin retries=0.
    pattern = re.compile(r"AsyncHTTPTransport\(([^)]*)\)")
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            args = match.group(1)
            if "retries=0" not in args.replace(" ", ""):
                offenders.append(f"{path.name}: {match.group(0)}")
    assert offenders == [], offenders
