"""LDAP bind authentication (P5-T2, FR-A4): settings round-trip + login fallback.

The ldap3 bind itself is stubbed — we exercise Perevoditarr's fallback wiring
and provisioning, not an LDAP server."""

import pytest
from litestar import Litestar
from litestar.testing import TestClient

from perevoditarr.modules.auth.ldap import LdapIdentity
from perevoditarr.modules.auth.schemas import LdapProviderSettings
from tests.conftest import complete_setup, csrf_headers
from tests.support import json_obj


async def _fake_ldap(
    _settings: LdapProviderSettings, username: str, password: str
) -> LdapIdentity | None:
    if username == "ldapuser" and password == "ldap-pass-1234":
        return LdapIdentity(username="ldapuser", email="ldapuser@example.com")
    return None


def _configure_ldap(client: TestClient[Litestar]) -> None:
    headers = csrf_headers(client)
    response = client.put(
        "/api/v1/auth/providers/ldap",
        json={
            "enabled": True,
            "serverUri": "ldap://ldap:389",
            "userSearchBase": "ou=users,dc=example,dc=com",
            "bindPassword": "service-secret",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    read = json_obj(response)
    assert read["bindPasswordSet"] is True
    # Secret is never echoed back in plaintext (FR-A5).
    assert "bindPassword" not in read


def test_ldap_settings_round_trip(client: TestClient[Litestar]) -> None:
    complete_setup(client)
    _configure_ldap(client)
    read = json_obj(client.get("/api/v1/auth/providers/ldap"))
    assert read["enabled"] is True
    assert read["serverUri"] == "ldap://ldap:389"
    assert read["bindPasswordSet"] is True


def test_ldap_login_provisions_viewer(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    complete_setup(client)
    _configure_ldap(client)
    monkeypatch.setattr(
        "perevoditarr.modules.auth.controllers.ldap_authenticate", _fake_ldap
    )
    headers = csrf_headers(client)
    _ = client.post("/api/v1/auth/logout", json={}, headers=headers)

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "ldapuser", "password": "ldap-pass-1234"},
    )
    assert login.status_code == 200, login.text
    body = json_obj(login)
    assert body["username"] == "ldapuser"
    # Externally-provisioned non-first user defaults to viewer (ADR-0008).
    assert body["role"] == "viewer"


def test_ldap_wrong_password_still_rejected(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    complete_setup(client)
    _configure_ldap(client)
    monkeypatch.setattr(
        "perevoditarr.modules.auth.controllers.ldap_authenticate", _fake_ldap
    )
    headers = csrf_headers(client)
    _ = client.post("/api/v1/auth/logout", json={}, headers=headers)

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "ldapuser", "password": "wrong"},
    )
    assert login.status_code == 401
