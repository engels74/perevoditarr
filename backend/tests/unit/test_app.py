from pathlib import Path

import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from perevoditarr.app import create_app
from perevoditarr.core.settings import AppSettings
from tests.conftest import TEST_SECRET, _create_schema, complete_setup


class _OpenAPIPaths(msgspec.Struct):
    paths: dict[str, object]


def test_health(client: TestClient[Litestar]) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_locked_before_setup(client: TestClient[Litestar]) -> None:
    response = client.get("/api/v1/hello")
    assert response.status_code == 403
    assert response.json()["code"] == "setup-required"


def test_hello_is_camel_cased_after_setup(client: TestClient[Litestar]) -> None:
    complete_setup(client)
    response = client.get("/api/v1/hello")
    assert response.status_code == 200
    payload = msgspec.json.decode(response.content, type=dict[str, str])
    assert payload["appName"] == "Perevoditarr"
    assert "message" in payload


def test_openapi_schema_served(client: TestClient[Litestar]) -> None:
    response = client.get("/schema/openapi.json")
    assert response.status_code == 200
    schema = msgspec.json.decode(response.content, type=_OpenAPIPaths)
    assert "/api/v1/health" in schema.paths
    assert "/api/v1/auth/login" in schema.paths
    assert "/api/v1/events" in schema.paths


def test_unknown_path_is_404_without_spa(client: TestClient[Litestar]) -> None:
    response = client.get("/some/client/route")
    assert response.status_code == 404


@pytest.fixture
def spa_app(tmp_path: Path) -> Litestar:
    spa = tmp_path / "spa"
    spa.mkdir()
    _ = (spa / "index.html").write_text("<!doctype html><title>spa</title>")
    settings = AppSettings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/spa.db",
        secret_key=TEST_SECRET,
        spa_dir=str(spa),
        health_interval_seconds=0,
        sync_interval_seconds=0,
        wanted_interval_seconds=0,
        doctor_interval_seconds=0,
    )
    _create_schema(settings.database_url)
    return create_app(settings=settings)


def test_spa_fallback_serves_index(spa_app: Litestar) -> None:
    with TestClient(app=spa_app) as client:
        # deep link falls back to the SPA shell
        response = client.get("/library/some-series")
        assert response.status_code == 200
        assert "spa" in response.text
        # API errors stay JSON and are never swallowed by the fallback
        response = client.get("/api/v1/nope")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
