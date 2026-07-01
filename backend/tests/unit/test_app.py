from pathlib import Path

import msgspec
import pytest
from litestar.testing import TestClient

from perevoditarr.app import SPA_DIR_ENV, create_app


class _OpenAPIPaths(msgspec.Struct):
    paths: dict[str, object]


def test_health() -> None:
    with TestClient(app=create_app()) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_hello_is_camel_cased() -> None:
    with TestClient(app=create_app()) as client:
        response = client.get("/api/v1/hello")
        assert response.status_code == 200
        payload = msgspec.json.decode(response.content, type=dict[str, str])
        assert payload["appName"] == "Perevoditarr"
        assert "message" in payload


def test_openapi_schema_served() -> None:
    with TestClient(app=create_app()) as client:
        response = client.get("/schema/openapi.json")
        assert response.status_code == 200
        schema = msgspec.json.decode(response.content, type=_OpenAPIPaths)
        assert "/api/v1/health" in schema.paths
        assert "/api/v1/hello" in schema.paths


def test_unknown_path_is_json_404_without_spa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SPA_DIR_ENV, raising=False)
    with TestClient(app=create_app()) as client:
        response = client.get("/some/client/route")
        assert response.status_code == 404


def test_spa_fallback_serves_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    monkeypatch.setenv(SPA_DIR_ENV, str(tmp_path))
    with TestClient(app=create_app()) as client:
        # deep link falls back to the SPA shell
        response = client.get("/library/some-series")
        assert response.status_code == 200
        assert "spa" in response.text
        # API 404s stay JSON and are never swallowed by the fallback
        response = client.get("/api/v1/nope")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
