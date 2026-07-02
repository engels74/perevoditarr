import httpx

from perevoditarr.core.http import HttpClientRegistry, build_transport


def test_transport_retries_disabled() -> None:
    # PRD §6.3 / FR-DR9: transport-level retries are banned; Bazarr already
    # retries toward Lingarr. Intent-level retry is the only retry surface.
    transport = build_transport()
    pool = transport._pool  # pyright: ignore[reportPrivateUsage]
    assert pool._retries == 0  # pyright: ignore[reportPrivateUsage]


async def test_registry_pools_clients_by_url_and_credentials() -> None:
    registry = HttpClientRegistry()
    try:
        a = registry.get("http://bazarr:6767", headers={"X-API-KEY": "one"})
        b = registry.get("http://bazarr:6767", headers={"X-API-KEY": "one"})
        c = registry.get("http://bazarr:6767", headers={"X-API-KEY": "two"})
        d = registry.get("http://lingarr:9876", headers={"X-Api-Key": "one"})
        assert a is b
        assert a is not c
        assert a is not d
    finally:
        await registry.aclose()


async def test_registry_close_closes_all_clients() -> None:
    registry = HttpClientRegistry()
    client = registry.get("http://bazarr:6767")
    await registry.aclose()
    assert client.is_closed


async def test_registry_replaces_closed_clients() -> None:
    registry = HttpClientRegistry()
    try:
        first = registry.get("http://bazarr:6767")
        await first.aclose()
        second = registry.get("http://bazarr:6767")
        assert second is not first
        assert not second.is_closed
    finally:
        await registry.aclose()


def test_client_key_never_contains_credentials() -> None:
    key = HttpClientRegistry._key(  # pyright: ignore[reportPrivateUsage]
        "http://bazarr:6767", {"X-API-KEY": "super-secret"}
    )
    assert "super-secret" not in key


def test_default_client_configuration() -> None:
    registry = HttpClientRegistry()
    client = registry.get("http://bazarr:6767")
    assert isinstance(client.timeout, httpx.Timeout)
    assert client.timeout.connect == 5.0
