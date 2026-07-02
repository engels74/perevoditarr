"""Instances module end-to-end (P1-T4): registration gate, discovery, health."""

from collections.abc import Iterator
from typing import override

import httpx
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.lingarr import LingarrClient
from tests.conftest import complete_setup, csrf_headers
from tests.simulators.scenario import Scenario
from tests.support import as_obj, json_list, json_obj


class SimulatorGateway(InstanceGateway):
    """Routes gateway clients into the in-process simulators."""

    def __init__(self, scenario: Scenario) -> None:
        super().__init__(HttpClientRegistry())
        self.scenario: Scenario = scenario

    @override
    def bazarr(self, url: str, api_key: str) -> BazarrClient:
        transport = httpx.ASGITransport(app=self.scenario.bazarr.app)  # pyright: ignore[reportArgumentType]
        return BazarrClient(
            httpx.AsyncClient(
                transport=transport, base_url=url, headers={"X-API-KEY": api_key}
            )
        )

    @override
    def lingarr(self, url: str, api_key: str | None) -> LingarrClient:
        transport = httpx.ASGITransport(app=self.scenario.lingarr.app)  # pyright: ignore[reportArgumentType]
        headers = {"X-Api-Key": api_key} if api_key else None
        return LingarrClient(
            httpx.AsyncClient(transport=transport, base_url=url, headers=headers)
        )


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


@pytest.fixture
def client(app: Litestar, scenario: Scenario) -> Iterator[TestClient[Litestar]]:
    app.state["gateway"] = SimulatorGateway(scenario)
    with TestClient(app=app) as test_client:
        complete_setup(test_client)
        yield test_client


def _register_bazarr(
    client: TestClient[Litestar], name: str = "main"
) -> dict[str, object]:
    response = client.post(
        "/api/v1/instances/bazarr",
        json={"name": name, "url": "http://bazarr.test", "apiKey": "bazarr-key"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return json_obj(response)


class TestRegistration:
    def test_register_bazarr_persists_version_and_capabilities(
        self, client: TestClient[Litestar]
    ) -> None:
        created = _register_bazarr(client)
        assert created["version"] == "1.5.6"
        capabilities = created["capabilities"]
        assert isinstance(capabilities, dict)
        assert capabilities["translateReturnsJobId"] is False
        assert capabilities["lingarrReceivesEpisodeId"] is False
        # the API key is write-only (FR-A5)
        assert "apiKey" not in created
        listing = client.get("/api/v1/instances/bazarr")
        assert [as_obj(i)["name"] for i in json_list(listing)] == ["main"]

    def test_register_rejects_unsupported_version(
        self, client: TestClient[Litestar], scenario: Scenario
    ) -> None:
        scenario.bazarr.version = "1.5.5"
        response = client.post(
            "/api/v1/instances/bazarr",
            json={"name": "old", "url": "http://bazarr.test", "apiKey": "bazarr-key"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422
        assert json_obj(response)["code"] == "unsupported-version"
        assert json_list(client.get("/api/v1/instances/bazarr")) == []

    def test_register_rejects_bad_credentials(
        self, client: TestClient[Litestar]
    ) -> None:
        response = client.post(
            "/api/v1/instances/bazarr",
            json={"name": "bad", "url": "http://bazarr.test", "apiKey": "wrong"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 502

    def test_duplicate_name_conflicts(self, client: TestClient[Litestar]) -> None:
        _ = _register_bazarr(client)
        response = client.post(
            "/api/v1/instances/bazarr",
            json={"name": "main", "url": "http://bazarr.test", "apiKey": "bazarr-key"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 409

    def test_enable_disable_flag(self, client: TestClient[Litestar]) -> None:
        created = _register_bazarr(client)
        response = client.patch(
            f"/api/v1/instances/bazarr/{created['id']}",
            json={"enabled": False},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200
        assert json_obj(response)["enabled"] is False


class TestConnectionTest:
    def test_dry_validation_success(self, client: TestClient[Litestar]) -> None:
        response = client.post(
            "/api/v1/instances/test",
            json={
                "kind": "bazarr",
                "url": "http://bazarr.test",
                "apiKey": "bazarr-key",
            },
            headers=csrf_headers(client),
        )
        assert response.status_code == 201
        body = json_obj(response)
        assert body["reachable"] is True
        assert body["version"] == "1.5.6"
        assert body["versionSupported"] is True
        # dry validation never persists (P1-T4)
        assert json_list(client.get("/api/v1/instances/bazarr")) == []

    def test_dry_validation_failure(self, client: TestClient[Litestar]) -> None:
        response = client.post(
            "/api/v1/instances/test",
            json={"kind": "bazarr", "url": "http://bazarr.test", "apiKey": "nope"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 201
        assert json_obj(response)["reachable"] is False

    def test_lingarr_test(self, client: TestClient[Litestar]) -> None:
        response = client.post(
            "/api/v1/instances/test",
            json={"kind": "lingarr", "url": "http://lingarr.test"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 201
        body = json_obj(response)
        assert body["version"] == "1.2.4"
        assert body["versionSupported"] is True


class TestLingarrDiscovery:
    def test_discovery_and_confirm_links_instances(
        self, client: TestClient[Litestar]
    ) -> None:
        created = _register_bazarr(client)
        discovery = client.get(
            f"/api/v1/instances/bazarr/{created['id']}/lingarr-discovery"
        )
        assert discovery.status_code == 200
        body = json_obj(discovery)
        assert body["configured"] is True
        assert body["url"] == "http://lingarr.test"
        assert body["hasApiKey"] is True
        # the token itself is never exposed (FR-A5)
        assert "apiKey" not in body
        assert "token" not in body

        confirm = client.post(
            f"/api/v1/instances/bazarr/{created['id']}/lingarr-discovery/confirm",
            json={"name": "shared-lingarr"},
            headers=csrf_headers(client),
        )
        assert confirm.status_code == 201, confirm.text
        lingarr = json_obj(confirm)
        assert lingarr["hasApiKey"] is True
        assert lingarr["version"] == "1.2.4"

        bazarr_list = json_list(client.get("/api/v1/instances/bazarr"))
        assert as_obj(bazarr_list[0])["lingarrInstanceId"] == lingarr["id"]

    def test_linked_lingarr_cannot_be_deleted(
        self, client: TestClient[Litestar]
    ) -> None:
        created = _register_bazarr(client)
        confirm = client.post(
            f"/api/v1/instances/bazarr/{created['id']}/lingarr-discovery/confirm",
            json={"name": "shared"},
            headers=csrf_headers(client),
        )
        lingarr_id = json_obj(confirm)["id"]
        blocked = client.delete(
            f"/api/v1/instances/lingarr/{lingarr_id}", headers=csrf_headers(client)
        )
        assert blocked.status_code == 409
        # unlink, then delete succeeds
        _ = client.patch(
            f"/api/v1/instances/bazarr/{created['id']}",
            json={"lingarrInstanceId": None},
            headers=csrf_headers(client),
        )
        deleted = client.delete(
            f"/api/v1/instances/lingarr/{lingarr_id}", headers=csrf_headers(client)
        )
        assert deleted.status_code == 204


class TestHealth:
    def test_manual_health_check_persists_snapshot(
        self, client: TestClient[Litestar]
    ) -> None:
        created = _register_bazarr(client)
        response = client.post(
            f"/api/v1/instances/bazarr/{created['id']}/health-check",
            headers=csrf_headers(client),
        )
        assert response.status_code == 201
        health = as_obj(json_obj(response)["health"])
        assert health["status"] == "ok"
        assert health["queueDepth"] == 0
        assert health["version"] == "1.5.6"
        # snapshot survives via the list endpoint (restart-safe persistence)
        listing = json_list(client.get("/api/v1/instances/bazarr"))
        assert as_obj(as_obj(listing[0])["health"])["status"] == "ok"
