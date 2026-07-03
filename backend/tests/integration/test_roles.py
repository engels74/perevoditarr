"""Roles: admin vs. viewer enforcement + user management (P5-T2, FR-A6)."""

from litestar import Litestar
from litestar.testing import TestClient

from tests.conftest import complete_setup, csrf_headers
from tests.support import as_obj, json_list, json_obj

_VIEWER_PASSWORD = "viewer-pass-1234"


def _make_viewer(client: TestClient[Litestar], username: str = "viewer1") -> str:
    headers = csrf_headers(client)
    response = client.post(
        "/api/v1/auth/users",
        json={"username": username, "password": _VIEWER_PASSWORD, "role": "viewer"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    created = json_obj(response)["id"]
    assert isinstance(created, str)
    return created


def test_viewer_reads_but_cannot_write(client: TestClient[Litestar]) -> None:
    complete_setup(client)  # admin session
    _ = _make_viewer(client)

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer1", "password": _VIEWER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    body = json_obj(login)
    assert body["role"] == "viewer"
    assert body["isAdmin"] is False

    # Reads are allowed.
    assert client.get("/api/v1/watch/sources").status_code == 200
    assert client.get("/api/v1/instances/bazarr").status_code == 200

    # Any mutation is denied by the router role guard.
    headers = csrf_headers(client)
    denied = client.post(
        "/api/v1/watch/sources",
        json={
            "name": "t",
            "sourceType": "tautulli",
            "url": "http://tautulli:8181",
            "credential": "k",
        },
        headers=headers,
    )
    assert denied.status_code == 403

    # Session self-service (logout) stays allowed for viewers.
    logout = client.post("/api/v1/auth/logout", json={}, headers=headers)
    assert logout.status_code == 200


def test_user_management_and_last_admin_guards(client: TestClient[Litestar]) -> None:
    complete_setup(client)
    headers = csrf_headers(client)

    users = json_list(client.get("/api/v1/auth/users"))
    assert len(users) == 1
    admin = as_obj(users[0])
    admin_id = admin["id"]
    assert admin["role"] == "admin"

    # The last admin cannot be demoted or deleted.
    demote = client.patch(
        f"/api/v1/auth/users/{admin_id}/role", json={"role": "viewer"}, headers=headers
    )
    assert demote.status_code == 409
    self_delete = client.delete(f"/api/v1/auth/users/{admin_id}", headers=headers)
    assert self_delete.status_code == 409

    viewer_id = _make_viewer(client, "viewer2")
    listed = json_list(client.get("/api/v1/auth/users"))
    assert {as_obj(user)["role"] for user in listed} == {"admin", "viewer"}

    promote = client.patch(
        f"/api/v1/auth/users/{viewer_id}/role",
        json={"role": "admin"},
        headers=headers,
    )
    assert promote.status_code == 200
    assert json_obj(promote)["role"] == "admin"

    deleted = client.delete(f"/api/v1/auth/users/{viewer_id}", headers=headers)
    assert deleted.status_code == 204


def test_viewer_cannot_manage_users(client: TestClient[Litestar]) -> None:
    complete_setup(client)
    _ = _make_viewer(client)
    _ = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer1", "password": _VIEWER_PASSWORD},
    )
    # Even the read list is admin-only (require_admin), so viewers get 403.
    assert client.get("/api/v1/auth/users").status_code == 403
