"""Adversarial red-team suite for the first-run onboarding wizard (G001 QA).

These cases deliberately try to BREAK the wizard's security contract rather
than confirm the happy path (which ``test_setup_wizard.py`` already covers):

1. gate-bypass    -- non-allow-listed /api paths stay 403 while incomplete.
2. token-replay   -- the bootstrap token is single-use; a replay/forgery is
                     rejected and no second admin can be minted.
3. finish-authz   -- /setup/finish demands an admin session (viewer 403,
                     unauth 401).
4. finish-prereq  -- /setup/finish enforces user>0 AND bazarr>=1 (422) and
                     leaves completion + the gate untouched on rejection.
5. finish-csrf    -- /setup/finish is CSRF-protected even for a valid admin.
6. no-premature   -- creating the admin alone never flips completion nor opens
                     the gate; only /setup/finish does.

Reuses the conftest fixtures and the SimulatorGateway pattern from
``test_instances.py`` so registration/discovery route through in-process sims.
"""

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
from tests.conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    bootstrap_token,
    client_auth_runtime,
    csrf_headers,
)
from tests.simulators.scenario import Scenario
from tests.support import json_list, json_obj

VIEWER_USERNAME = "observer"
VIEWER_PASSWORD = "viewer-horse-battery-staple"  # >= 10 chars (Password Meta)

# Real controllers that are NOT on the setup allow-list; the gate must refuse
# every one of these while first-run setup is incomplete.
_NON_ALLOW_LISTED = (
    "/api/v1/rails/status",
    "/api/v1/stats/overview",
    "/api/v1/quarantine",
    "/api/v1/intents",
)


class SimulatorGateway(InstanceGateway):
    """Routes gateway clients into the in-process simulators (see test_instances)."""

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
    """A fresh (setup-incomplete) client with the simulator gateway wired."""
    app.state["gateway"] = SimulatorGateway(scenario)
    with TestClient(app=app) as test_client:
        yield test_client


def _create_admin(client: TestClient[Litestar]) -> None:
    """Create the initial admin via the real (CSRF-exempt) endpoint."""
    response = client.post(
        "/api/v1/setup",
        json={
            "username": ADMIN_USERNAME,
            "password": ADMIN_PASSWORD,
            "bootstrapToken": bootstrap_token(client),
        },
    )
    assert response.status_code == 200, response.text


def _register_bazarr(client: TestClient[Litestar], name: str = "main") -> None:
    response = client.post(
        "/api/v1/instances/bazarr",
        json={"name": name, "url": "http://bazarr.test", "apiKey": "bazarr-key"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text


def _create_viewer(client: TestClient[Litestar]) -> None:
    """Create a read-only viewer through the admin-only user endpoint."""
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": VIEWER_USERNAME,
            "password": VIEWER_PASSWORD,
            "role": "viewer",
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    assert json_obj(response)["role"] == "viewer"


def _user_count(client: TestClient[Litestar]) -> int:
    """Count users via the admin-only listing (proves no phantom admins)."""
    response = client.get("/api/v1/auth/users")
    assert response.status_code == 200, response.text
    return len(json_list(response))


def _status_completed(client: TestClient[Litestar]) -> bool:
    completed = json_obj(client.get("/api/v1/setup/status"))["completed"]
    assert isinstance(completed, bool)
    return completed


class TestGateBypassSweep:
    """Case 1: enumerate non-allow-listed endpoints -> all 403 setup-required."""

    def test_reading_non_allow_listed_paths_are_all_gated(
        self, client: TestClient[Litestar]
    ) -> None:
        for path in _NON_ALLOW_LISTED:
            response = client.get(path)
            assert response.status_code == 403, f"{path} -> {response.status_code}"
            assert json_obj(response)["code"] == "setup-required", path

    def test_mutating_handler_on_non_allow_listed_path_is_gated(
        self, client: TestClient[Litestar]
    ) -> None:
        # The gate wraps every matched route handler, so a real WRITE handler on
        # a non-allow-listed prefix (the intents Lingarr passthrough action) is
        # refused with setup-required before the handler body ever runs -- no
        # mutation, no data leak. (A write verb to a GET-only path is a routing
        # 405 that never reaches a handler, which is also safe but not the gate.)
        response = client.post(
            "/api/v1/intents/00000000-0000-0000-0000-000000000000/lingarr/1/retry"
        )
        assert response.status_code == 403, response.text
        assert json_obj(response)["code"] == "setup-required"


class TestBootstrapTokenReplay:
    """Case 2: the bootstrap token is cleared post-creation; no second admin."""

    def test_replayed_and_forged_tokens_are_rejected(
        self, client: TestClient[Litestar]
    ) -> None:
        token = bootstrap_token(client)
        _create_admin(client)  # consumes/clears the token

        # Replay the exact same (now-cleared) token.
        replay = client.post(
            "/api/v1/setup",
            json={
                "username": "intruder",
                "password": "intruder-password-99",
                "bootstrapToken": token,
            },
        )
        assert replay.status_code == 403
        assert json_obj(replay)["code"] == "invalid-bootstrap-token"

        # A forged token of the correct length is likewise refused.
        forged = client.post(
            "/api/v1/setup",
            json={
                "username": "intruder",
                "password": "intruder-password-99",
                "bootstrapToken": "aaaa-bbbb-cccc",
            },
        )
        assert forged.status_code == 403
        assert json_obj(forged)["code"] == "invalid-bootstrap-token"

        # No phantom admin was created and completion was not falsely flipped.
        assert _user_count(client) == 1
        assert _status_completed(client) is False
        assert client_auth_runtime(client).bootstrap.current_token() is None


class TestFinishAuthorization:
    """Case 3: /setup/finish requires an admin session (viewer 403, unauth 401)."""

    def test_viewer_cannot_finish_setup(
        self, app: Litestar, client: TestClient[Litestar]
    ) -> None:
        _create_admin(client)
        _register_bazarr(client)  # prereqs satisfied so 403 is authz, not 422
        _create_viewer(client)

        with TestClient(app=app) as viewer:
            login = viewer.post(
                "/api/v1/auth/login",
                json={"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD},
            )
            assert login.status_code == 200, login.text
            forbidden = viewer.post(
                "/api/v1/setup/finish", headers=csrf_headers(viewer)
            )
            assert forbidden.status_code == 403, forbidden.text

        # The viewer's rejected attempt left completion untouched.
        assert _status_completed(client) is False

    def test_unauthenticated_cannot_finish_setup(
        self, app: Litestar, client: TestClient[Litestar]
    ) -> None:
        _create_admin(client)
        _register_bazarr(client)

        with TestClient(app=app) as anon:
            # No session cookie -> auth rejects the request (401) before CSRF is
            # ever considered; the wizard cannot be finished anonymously.
            unauth = anon.post("/api/v1/setup/finish")
            assert unauth.status_code == 401, unauth.text

        assert _status_completed(client) is False


class TestFinishPrerequisiteBypass:
    """Case 4: admin-only (0 Bazarr) finish -> 422; gate & completion unchanged."""

    def test_finish_without_bazarr_is_rejected_and_gate_stays_closed(
        self, client: TestClient[Litestar]
    ) -> None:
        _create_admin(client)  # user>0 but bazarr==0

        rejected = client.post("/api/v1/setup/finish", headers=csrf_headers(client))
        assert rejected.status_code == 422
        assert json_obj(rejected)["code"] == "validation-failed"

        # Completion did not flip and the gate is still closed for gated paths.
        assert _status_completed(client) is False
        gated = client.get("/api/v1/rails/status")
        assert gated.status_code == 403
        assert json_obj(gated)["code"] == "setup-required"


class TestFinishCsrf:
    """Case 5: /setup/finish is CSRF-protected even for a valid admin session."""

    def test_finish_without_csrf_header_is_refused(
        self, client: TestClient[Litestar]
    ) -> None:
        _create_admin(client)
        _register_bazarr(client)  # prereqs met so failure is purely CSRF

        no_csrf = client.post("/api/v1/setup/finish")
        assert no_csrf.status_code == 403, no_csrf.text
        # Completion must not have happened via the CSRF-less request.
        assert _status_completed(client) is False


class TestNoPrematureCompletion:
    """Case 6: admin creation alone never completes setup nor opens the gate."""

    def test_admin_creation_does_not_flip_completion_or_open_gate(
        self, client: TestClient[Litestar]
    ) -> None:
        _create_admin(client)

        assert _status_completed(client) is False
        after_admin = client.get("/api/v1/rails/status")
        assert after_admin.status_code == 403
        assert json_obj(after_admin)["code"] == "setup-required"

        # Even after the required Bazarr exists (phase == finish), completion is
        # still False and the gate is still closed until /setup/finish runs.
        _register_bazarr(client)
        assert json_obj(client.get("/api/v1/setup/status"))["phase"] == "finish"
        assert _status_completed(client) is False
        assert client.get("/api/v1/stats/overview").status_code == 403
