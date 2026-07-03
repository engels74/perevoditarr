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
    _create_schema,  # pyright: ignore[reportPrivateUsage]  # conftest's module-private schema provisioner, reused to build an isolated trusted-proxy app
    bootstrap_token,
    client_auth_runtime,
    complete_setup,
    csrf_headers,
)
from tests.support import as_obj, json_list, json_obj


class TestSetupFlow:
    def test_api_exposes_only_setup_before_first_user(
        self, client: TestClient[Litestar]
    ) -> None:
        status = client.get("/api/v1/setup/status")
        assert status.status_code == 200
        status_body = json_obj(status)
        assert status_body["required"] is True
        assert status_body["bootstrapRequired"] is True
        assert status_body["completed"] is False
        assert status_body["phase"] == "admin"
        # A non-allow-listed /api path is gated (403 setup-required) pre-setup...
        gated = client.get("/api/v1/rails/status")
        assert gated.status_code == 403
        assert json_obj(gated)["code"] == "setup-required"
        # ...while an allow-listed prefix (auth) passes the gate and hits JWT
        # auth instead: unauthenticated -> 401, not 403 setup-required.
        blocked = client.get("/api/v1/auth/me")
        assert blocked.status_code == 401

    def test_setup_creates_admin_and_logs_in(
        self, client: TestClient[Litestar]
    ) -> None:
        complete_setup(client)
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        me_body = json_obj(me)
        assert me_body["username"] == ADMIN_USERNAME
        assert me_body["isAdmin"] is True
        status = client.get("/api/v1/setup/status")
        status_body = json_obj(status)
        assert status_body["required"] is False
        assert status_body["bootstrapRequired"] is False
        assert status_body["completed"] is True
        assert status_body["phase"] == "done"

    def test_setup_locks_out_after_first_user(
        self, client: TestClient[Litestar]
    ) -> None:
        complete_setup(client)
        # The token is cleared on completion, so a replayed setup can no longer
        # present a valid one — first-run setup is closed.
        again = client.post(
            "/api/v1/setup",
            json={
                "username": "second",
                "password": "another-password-123",
                "bootstrapToken": "aaaa-bbbb-cccc",
            },
        )
        assert again.status_code == 403
        assert json_obj(again)["code"] == "invalid-bootstrap-token"
        status = client.get("/api/v1/setup/status")
        status_body = json_obj(status)
        assert status_body["required"] is False
        assert status_body["completed"] is True

    def test_setup_missing_token_is_rejected(
        self, client: TestClient[Litestar]
    ) -> None:
        response = client.post(
            "/api/v1/setup",
            json={"username": "admin", "password": "another-password-123"},
        )
        # msgspec rejects the body: bootstrapToken is a required field.
        assert response.status_code == 400

    def test_setup_wrong_token_is_forbidden(self, client: TestClient[Litestar]) -> None:
        response = client.post(
            "/api/v1/setup",
            json={
                "username": "admin",
                "password": "another-password-123",
                "bootstrapToken": "aaaa-bbbb-cccc",
            },
        )
        assert response.status_code == 403
        assert json_obj(response)["code"] == "invalid-bootstrap-token"
        # A rejected attempt must not have created a user.
        assert json_obj(client.get("/api/v1/setup/status"))["required"] is True

    def test_bootstrap_token_issued_and_cleared(
        self, client: TestClient[Litestar]
    ) -> None:
        runtime = client_auth_runtime(client)
        # Minted at startup while setup is incomplete...
        assert runtime.bootstrap.current_token() is not None
        complete_setup(client)
        # ...and torn down once setup completes.
        assert runtime.bootstrap.current_token() is None

    def test_weak_setup_password_rejected(self, client: TestClient[Litestar]) -> None:
        token = bootstrap_token(client)
        response = client.post(
            "/api/v1/setup",
            json={"username": "admin", "password": "short", "bootstrapToken": token},
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
            assert json_obj(login)["username"] == ADMIN_USERNAME
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
            payload = json_obj(created)
            raw_key = payload["key"]
            assert isinstance(raw_key, str)
            assert raw_key.startswith("pvd_")
            assert payload["prefix"] == raw_key[:12]

            listing = client.get("/api/v1/auth/api-keys")
            assert listing.status_code == 200
            listing_body = json_list(listing)
            assert [as_obj(k)["name"] for k in listing_body] == ["automation"]
            # the raw key is never returned after creation (FR-A5)
            assert "key" not in as_obj(listing_body[0])

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
            created = json_obj(
                client.post(
                    "/api/v1/auth/api-keys",
                    json={"name": "to-delete"},
                    headers=csrf_headers(client),
                )
            )
            raw_key = created["key"]
            assert isinstance(raw_key, str)
            deleted = client.delete(
                f"/api/v1/auth/api-keys/{created['id']}", headers=csrf_headers(client)
            )
            assert deleted.status_code == 204
        with TestClient(app=app) as headless:
            response = headless.get("/api/v1/auth/me", headers={"X-API-KEY": raw_key})
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
        assert json_obj(response)["code"] == "validation-failed"

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

        def _always_trusted(_self: AuthRuntime, _host: str | None) -> bool:
            return True

        monkeypatch.setattr(AuthRuntime, "client_is_trusted_proxy", _always_trusted)
        with TestClient(app=app) as proxied:
            response = proxied.get(
                "/api/v1/auth/me",
                headers={"Remote-User": "eve", "Remote-Email": "eve@example.com"},
            )
            assert response.status_code == 200
            body = json_obj(response)
            assert body["username"] == "eve"
            assert body["email"] == "eve@example.com"

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
