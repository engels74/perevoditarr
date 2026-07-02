"""OIDC login flow against mocked Authentik/Authelia IdPs (P1-T2, FR-A2).

The discovery documents under tests/fixtures/oidc/ are the documented
provider fixtures the plan calls for; both providers run the same
authorization-code + PKCE path.
"""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import respx
from httpx import Response as MockResponse
from litestar import Litestar
from litestar.testing import TestClient

from tests.conftest import complete_setup, csrf_headers

FIXTURES = Path(__file__).parent.parent / "fixtures" / "oidc"


def _configure_oidc(client: TestClient[Litestar], issuer: str) -> None:
    response = client.put(
        "/api/v1/auth/providers/oidc",
        json={
            "enabled": True,
            "issuer": issuer,
            "clientId": "perevoditarr",
            "clientSecret": "s3cret",
            "displayName": "SSO",
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["clientSecretSet"] is True
    assert "clientSecret" not in body  # write-only (FR-A5)


@pytest.mark.parametrize("provider", ["authentik", "authelia"])
def test_oidc_login_flow(app: Litestar, provider: str) -> None:
    discovery = json.loads((FIXTURES / f"{provider}.json").read_text())
    issuer: str = discovery["issuer"]

    with TestClient(app=app) as admin:
        complete_setup(admin)
        _configure_oidc(admin, issuer)

    with respx.mock(assert_all_called=False) as router:
        _ = router.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration").mock(
            return_value=MockResponse(200, json=discovery)
        )
        _ = router.post(discovery["token_endpoint"]).mock(
            return_value=MockResponse(
                200, json={"access_token": "at-123", "token_type": "Bearer"}
            )
        )
        _ = router.get(discovery["userinfo_endpoint"]).mock(
            return_value=MockResponse(
                200,
                json={
                    "sub": f"{provider}-user-1",
                    "email": "eve@example.com",
                    "preferred_username": "eve",
                },
            )
        )

        with TestClient(app=app) as browser:
            start = browser.get("/api/v1/auth/oidc/login", follow_redirects=False)
            assert start.status_code == 302
            location = start.headers["location"]
            assert location.startswith(discovery["authorization_endpoint"])
            query = parse_qs(urlsplit(location).query)
            assert query["code_challenge_method"] == ["S256"]
            state = query["state"][0]

            callback = browser.get(
                f"/api/v1/auth/oidc/callback?code=auth-code&state={state}",
                follow_redirects=False,
            )
            assert callback.status_code == 302, callback.text
            assert callback.headers["location"] == "/"

            me = browser.get("/api/v1/auth/me")
            assert me.status_code == 200
            assert me.json()["username"] == "eve"
            assert me.json()["email"] == "eve@example.com"


def test_oidc_callback_rejects_state_mismatch(app: Litestar) -> None:
    discovery = json.loads((FIXTURES / "authelia.json").read_text())
    issuer: str = discovery["issuer"]

    with TestClient(app=app) as admin:
        complete_setup(admin)
        _configure_oidc(admin, issuer)

    with respx.mock(assert_all_called=False) as router:
        _ = router.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration").mock(
            return_value=MockResponse(200, json=discovery)
        )

        with TestClient(app=app) as browser:
            start = browser.get("/api/v1/auth/oidc/login", follow_redirects=False)
            assert start.status_code == 302

            callback = browser.get(
                "/api/v1/auth/oidc/callback?code=auth-code&state=forged-state",
                follow_redirects=False,
            )
            assert callback.status_code == 401


def test_oidc_login_disabled_by_default(app: Litestar) -> None:
    with TestClient(app=app) as client:
        complete_setup(client)
        providers = client.get("/api/v1/auth/providers")
        assert providers.status_code == 200
        assert providers.json() == {"builtin": True, "oidc": None}
        response = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
        assert response.status_code == 422
