"""Guided onboarding wizard end-to-end (P6-T1).

Drives the real setup wizard surface: /setup/status derivation, admin
creation (CSRF-exempt), the gate's allow-list vs. block behaviour, the
CSRF-protected /setup/finish prerequisite, the optional policy step, and a
restart that re-mints the bootstrap token while durable completion is unset.
"""

import asyncio
from collections.abc import Iterator
from typing import override

import httpx
import pytest
from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.app import create_app
from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.lingarr import LingarrClient
from perevoditarr.modules.policy.models import Preset
from tests.conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    bootstrap_token,
    client_auth_runtime,
    csrf_headers,
)
from tests.simulators.scenario import Scenario
from tests.support import as_obj, json_list, json_obj


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


async def _seed_builtin_presets(database_url: str) -> None:
    """Replicate migration b3f1a27d9e40's seed: 4 built-ins, Observe active.

    The test schema is provisioned via metadata.create_all (no migrations), so
    the shipped presets must be seeded explicitly for the optional policy step.
    """
    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                Preset(
                    name="Observe",
                    built_in=True,
                    active=True,
                    values={"dry_run": True},
                    rails={},
                ),
                Preset(
                    name="Conservative",
                    built_in=True,
                    active=False,
                    values={"dry_run": False},
                    rails={},
                ),
                Preset(
                    name="Balanced",
                    built_in=True,
                    active=False,
                    values={"dry_run": False},
                    rails={},
                ),
                Preset(
                    name="Aggressive",
                    built_in=True,
                    active=False,
                    values={"dry_run": False},
                    rails={},
                ),
            ]
        )
        await session.commit()
    await engine.dispose()


class TestWizardHappyPath:
    def test_admin_to_bazarr_to_finish(self, client: TestClient[Litestar]) -> None:
        # Fresh install: no admin yet.
        start = json_obj(client.get("/api/v1/setup/status"))
        assert start["phase"] == "admin"
        assert start["completed"] is False

        _create_admin(client)

        # Admin exists, no Bazarr yet -> the wizard asks for a Bazarr.
        after_admin = json_obj(client.get("/api/v1/setup/status"))
        assert after_admin["phase"] == "bazarr"
        assert after_admin["completed"] is False
        assert as_obj(after_admin["checklist"])["hasAdmin"] is True

        _register_bazarr(client)

        # Required steps satisfied -> the wizard is ready to finish.
        ready = json_obj(client.get("/api/v1/setup/status"))
        assert ready["phase"] == "finish"
        assert as_obj(ready["checklist"])["bazarrCount"] == 1

        finished = client.post("/api/v1/setup/finish", headers=csrf_headers(client))
        assert finished.status_code == 201, finished.text
        finished_body = json_obj(finished)
        assert finished_body["completed"] is True
        assert finished_body["phase"] == "done"

        # The gate is now open: a previously-blocked path answers 200.
        assert client.get("/api/v1/rails/status").status_code == 200


class TestGateBoundary:
    def test_unauthenticated_boundary(self, client: TestClient[Litestar]) -> None:
        # Allow-listed prefixes pass the gate but still need a session -> 401.
        assert client.get("/api/v1/instances/bazarr").status_code == 401
        assert client.get("/api/v1/policy/presets").status_code == 401

        # Non-allow-listed /api paths are gated -> 403 setup-required.
        rails = client.get("/api/v1/rails/status")
        assert rails.status_code == 403
        assert json_obj(rails)["code"] == "setup-required"
        stats = client.get("/api/v1/stats/overview")
        assert stats.status_code == 403
        assert json_obj(stats)["code"] == "setup-required"

    def test_authenticated_admin_may_configure_before_finish(
        self, client: TestClient[Litestar]
    ) -> None:
        _create_admin(client)
        # Do NOT finish: the gate must still let an authenticated admin reach the
        # config handler so the wizard can register a Bazarr pre-completion.
        _register_bazarr(client)
        assert json_obj(client.get("/api/v1/setup/status"))["completed"] is False


class TestFinishPrerequisite:
    def test_finish_rejected_without_bazarr_then_accepted(
        self, client: TestClient[Litestar]
    ) -> None:
        _create_admin(client)

        rejected = client.post("/api/v1/setup/finish", headers=csrf_headers(client))
        assert rejected.status_code == 422
        assert json_obj(rejected)["code"] == "validation-failed"

        _register_bazarr(client)

        accepted = client.post("/api/v1/setup/finish", headers=csrf_headers(client))
        assert accepted.status_code == 201, accepted.text
        assert json_obj(accepted)["completed"] is True


class TestCsrfOnFinish:
    def test_finish_requires_csrf_but_admin_creation_does_not(
        self, client: TestClient[Litestar]
    ) -> None:
        # Admin creation POST /api/v1/setup works WITHOUT a CSRF header.
        _create_admin(client)
        _register_bazarr(client)

        # /setup/finish is NOT csrf-exempt: without the header it is refused.
        no_csrf = client.post("/api/v1/setup/finish")
        assert no_csrf.status_code == 403

        with_csrf = client.post("/api/v1/setup/finish", headers=csrf_headers(client))
        assert with_csrf.status_code == 201, with_csrf.text


class TestOptionalPolicyStep:
    def test_seeded_presets_and_activation(
        self, app: Litestar, app_settings: AppSettings, scenario: Scenario
    ) -> None:
        asyncio.run(_seed_builtin_presets(app_settings.database_url))
        app.state["gateway"] = SimulatorGateway(scenario)
        with TestClient(app=app) as client:
            _create_admin(client)

            presets = json_list(client.get("/api/v1/policy/presets"))
            by_name = {as_obj(p)["name"]: as_obj(p) for p in presets}
            assert set(by_name) == {
                "Observe",
                "Conservative",
                "Balanced",
                "Aggressive",
            }
            assert by_name["Observe"]["active"] is True
            assert all(
                by_name[name]["active"] is False
                for name in ("Conservative", "Balanced", "Aggressive")
            )

            target_id = by_name["Balanced"]["id"]
            activated = client.post(
                f"/api/v1/policy/presets/{target_id}/activate",
                headers=csrf_headers(client),
            )
            assert activated.status_code == 201, activated.text
            assert json_obj(activated)["active"] is True

            after = {
                as_obj(p)["name"]: as_obj(p)
                for p in json_list(client.get("/api/v1/policy/presets"))
            }
            assert after["Balanced"]["active"] is True
            assert after["Observe"]["active"] is False

    def test_policy_step_is_skippable(self, client: TestClient[Litestar]) -> None:
        # A wizard that never touches policy still reaches finish: policy is not
        # a prerequisite.
        _create_admin(client)
        _register_bazarr(client)
        assert json_obj(client.get("/api/v1/setup/status"))["phase"] == "finish"
        finished = client.post("/api/v1/setup/finish", headers=csrf_headers(client))
        assert finished.status_code == 201, finished.text
        assert json_obj(finished)["completed"] is True


class TestResumeAfterRestart:
    def test_restart_remints_token_and_derives_phase(
        self, app: Litestar, app_settings: AppSettings
    ) -> None:
        # First boot: create the admin via the real endpoint (durable completion
        # is NOT set by POST /setup — that is /setup/finish's job).
        with TestClient(app=app) as first:
            _create_admin(first)
            assert json_obj(first.get("/api/v1/setup/status"))["completed"] is False

        # Restart: a brand-new app on the SAME sqlite file (schema already there).
        restarted = create_app(settings=app_settings)
        with TestClient(app=restarted) as second:
            # Durable setup is still incomplete -> a fresh bootstrap token mints.
            assert client_auth_runtime(second).bootstrap.current_token() is not None

            status = json_obj(second.get("/api/v1/setup/status"))
            assert status["completed"] is False
            assert status["phase"] == "bazarr"  # admin present, no Bazarr yet

            # The previously-created admin can still authenticate after restart.
            login = second.post(
                "/api/v1/auth/login",
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            )
            assert login.status_code == 200


class TestDurableCompletionPersistsAcrossRestart:
    def test_finish_persists_and_reopens_gate_from_cold_cache(
        self, app: Litestar, app_settings: AppSettings, scenario: Scenario
    ) -> None:
        # First boot: drive the FULL wizard through /setup/finish so the durable
        # app_setup_state flag is written (not just the in-memory cache).
        app.state["gateway"] = SimulatorGateway(scenario)
        with TestClient(app=app) as first:
            _create_admin(first)
            _register_bazarr(first)
            finished = first.post("/api/v1/setup/finish", headers=csrf_headers(first))
            assert finished.status_code == 201, finished.text
            assert json_obj(first.get("/api/v1/setup/status"))["completed"] is True

        # Restart: a brand-new app on the SAME sqlite file. Its AuthRuntime cache
        # is cold, so completion can only be known from the durable flag.
        restarted = create_app(settings=app_settings)
        restarted.state["gateway"] = SimulatorGateway(scenario)
        with TestClient(app=restarted) as second:
            # Setup is durably complete -> the first-run banner mints NO token.
            assert client_auth_runtime(second).bootstrap.current_token() is None

            status = json_obj(second.get("/api/v1/setup/status"))
            assert status["completed"] is True
            assert status["phase"] == "done"

            # The gate opened from the durable flag alone (cold cache): an
            # authenticated admin reaches a path that was setup-gated before.
            login = second.post(
                "/api/v1/auth/login",
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            )
            assert login.status_code == 200, login.text
            assert second.get("/api/v1/rails/status").status_code == 200
