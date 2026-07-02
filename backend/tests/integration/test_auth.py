"""Auth flows end-to-end: setup lockout, sessions, API keys, CSRF (P1-T2)."""

from pathlib import Path

import pytest
from litestar import Litestar
from litestar.testing import TestClient

from perevoditarr.app import create_app
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.auth.security import AuthRuntime
from tests.conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    TEST_SECRET,
    _create_schema,
    complete_setup,
    csrf_headers,
)


class TestSetupFlow:
    def test_api_exposes_only_setup_before_first_user(
        self, client: TestClient[Litestar]
    ) -> None:
        status = client.get("/api/v1/setup/status")
        assert status.status_code == 200
        assert status.json() == {"required": True}
        blocked = client.get("/api/v1/auth/me")
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "setup-required"

    def test_setup_creates_admin_and_logs_in(
        self, client: TestClient[Litestar]
    ) -> None:
        complete_setup(client)
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == ADMIN_USERNAME
        assert me.json()["isAdmin"] is True
        status = client.get("/api/v1/setup/status")
        assert status.json() == {"required": False}

    def test_setup_locks_out_after_first_user(
        self, client: TestClient[Litestar]
    ) -> None:
        complete_setup(client)
        again = client.post(
            "/api/v1/setup",
            json={"username": "second", "password": "another-password-123"},
        )
        assert again.status_code == 409
        assert again.json()["code"] == "conflict"

    def test_weak_setup_password_rejected(self, client: TestClient[Litestar]) -> None:
        response = client.post(
            "/api/v1/setup", json={"username": "admin", "password": "short"}
        )
        assert response.status_code == 400


class TestSessions:
    def test_login_wrong_password_rejected(self, app: Litestar) -> None:
        with TestClient(app=app) as first:
            complete_setup(first)
        with TestClient(app=app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": ADMIN_USERNAME, "password": "wrong-password-123"},
            )
            assert response.status_code == 401

    def test_login_refresh_logout_cycle(self, app: Litestar) -> None:
        with TestClient(app=app) as first:
            complete_setup(first)
        with TestClient(app=app) as client:
            assert client.get("/api/v1/auth/me").status_code == 401

            login = client.post(
                "/api/v1/auth/login",
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            )
            assert login.status_code == 200
            assert login.json()["username"] == ADMIN_USERNAME
            assert client.get("/api/v1/auth/me").status_code == 200

            refresh = client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
            assert refresh.status_code == 200

            logout = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
            assert logout.status_code == 200
            assert client.get("/api/v1/auth/me").status_code == 401

    def test_csrf_required_for_cookie_sessions(
        self, client: TestClient[Litestar]
    ) -> None:
        complete_setup(client)
        # unsafe method without the CSRF header is refused for cookie sessions
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 403


class TestApiKeys:
    def test_api_key_lifecycle(self, app: Litestar) -> None:
        with TestClient(app=app) as client:
            complete_setup(client)
            created = client.post(
                "/api/v1/auth/api-keys",
                json={"name": "automation"},
                headers=csrf_headers(client),
            )
            assert created.status_code == 201, created.text
            payload = created.json()
            raw_key = payload["key"]
            assert raw_key.startswith("pvd_")
            assert payload["prefix"] == raw_key[:12]

            listing = client.get("/api/v1/auth/api-keys")
            assert listing.status_code == 200
            assert [k["name"] for k in listing.json()] == ["automation"]
            # the raw key is never returned after creation (FR-A5)
            assert "key" not in listing.json()[0]

        # a fresh, cookie-less client authenticates with the header alone;
        # API-key requests bypass CSRF (no cookies involved)
        with TestClient(app=app) as headless:
            me = headless.get("/api/v1/auth/me", headers={"X-API-KEY": raw_key})
            assert me.status_code == 200
            create_more = headless.post(
                "/api/v1/auth/api-keys",
                json={"name": "second"},
                headers={"X-API-KEY": raw_key},
            )
            assert create_more.status_code == 201

            bad = headless.get("/api/v1/auth/me", headers={"X-API-KEY": "pvd_nope"})
            assert bad.status_code == 401

    def test_deleted_key_stops_working(self, app: Litestar) -> None:
        with TestClient(app=app) as client:
            complete_setup(client)
            created = client.post(
                "/api/v1/auth/api-keys",
                json={"name": "to-delete"},
                headers=csrf_headers(client),
            ).json()
            deleted = client.delete(
                f"/api/v1/auth/api-keys/{created['id']}", headers=csrf_headers(client)
            )
            assert deleted.status_code == 204
        with TestClient(app=app) as headless:
            response = headless.get(
                "/api/v1/auth/me", headers={"X-API-KEY": created["key"]}
            )
            assert response.status_code == 401


class TestForwardAuth:
    def _app_with_trusted_proxies(self, tmp_path: Path) -> Litestar:
        settings = AppSettings(
            database_url=f"sqlite+aiosqlite:///{tmp_path}/fa.db",
            secret_key=TEST_SECRET,
            trusted_proxies=("10.0.0.0/8",),
            health_interval_seconds=0,
            sync_interval_seconds=0,
            wanted_interval_seconds=0,
            doctor_interval_seconds=0,
        )
        _create_schema(settings.database_url)
        return create_app(settings=settings)

    def _enable_forward_auth(self, client: TestClient[Litestar]) -> None:
        response = client.put(
            "/api/v1/auth/providers/forward-auth",
            json={"enabled": True},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200, response.text

    def test_enabling_without_trusted_proxies_hard_fails(
        self, client: TestClient[Litestar]
    ) -> None:
        complete_setup(client)
        response = client.put(
            "/api/v1/auth/providers/forward-auth",
            json={"enabled": True},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation-failed"

    def test_spoofed_header_from_untrusted_client_rejected(
        self, tmp_path: Path
    ) -> None:
        app = self._app_with_trusted_proxies(tmp_path)
        with TestClient(app=app) as client:
            complete_setup(client)
            self._enable_forward_auth(client)
        with TestClient(app=app) as attacker:
            # TestClient's host is "testclient", which is not a trusted proxy
            response = attacker.get(
                "/api/v1/auth/me", headers={"Remote-User": "mallory"}
            )
            assert response.status_code == 401

    def test_trusted_proxy_header_provisions_user(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = self._app_with_trusted_proxies(tmp_path)
        with TestClient(app=app) as client:
            complete_setup(client)
            self._enable_forward_auth(client)
        monkeypatch.setattr(
            AuthRuntime, "client_is_trusted_proxy", lambda self, host: True
        )
        with TestClient(app=app) as proxied:
            response = proxied.get(
                "/api/v1/auth/me",
                headers={"Remote-User": "eve", "Remote-Email": "eve@example.com"},
            )
            assert response.status_code == 200
            assert response.json()["username"] == "eve"
            assert response.json()["email"] == "eve@example.com"

    def test_trusted_check_logic(self) -> None:
        from perevoditarr.core.db import build_alchemy_config
        from perevoditarr.core.security import SecretBox

        settings = AppSettings(
            secret_key=TEST_SECRET, trusted_proxies=("10.0.0.0/8", "192.168.1.1")
        )
        runtime = AuthRuntime(
            settings=settings,
            secret_box=SecretBox(TEST_SECRET),
            alchemy_config=build_alchemy_config(settings),
        )
        assert runtime.client_is_trusted_proxy("10.1.2.3")
        assert runtime.client_is_trusted_proxy("192.168.1.1")
        assert not runtime.client_is_trusted_proxy("192.168.1.2")
        assert not runtime.client_is_trusted_proxy("testclient")
        assert not runtime.client_is_trusted_proxy(None)

        unconfigured = AuthRuntime(
            settings=AppSettings(secret_key=TEST_SECRET),
            secret_box=SecretBox(TEST_SECRET),
            alchemy_config=build_alchemy_config(AppSettings(secret_key=TEST_SECRET)),
        )
        # no trusted proxies configured => forward-auth can never authenticate
        assert not unconfigured.client_is_trusted_proxy("10.1.2.3")
