"""Shared test fixtures: schema-provisioned app + client helpers."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from perevoditarr import models as models  # register all mappers (re-export)
from perevoditarr.app import create_app
from perevoditarr.core.db import metadata
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.auth import AuthRuntime

TEST_SECRET = "test-secret-key-0123456789abcdef-0123456789abcdef"  # gitleaks:allow
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct-horse-battery-staple"


def _create_schema(database_url: str) -> None:
    async def run() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        await engine.dispose()

    asyncio.run(run())


@pytest.fixture
def app_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        secret_key=TEST_SECRET,
        health_interval_seconds=0,  # keep background loops out of tests
        sync_interval_seconds=0,
        wanted_interval_seconds=0,
        doctor_interval_seconds=0,
        discovery_interval_seconds=0,
        reconcile_interval_seconds=0,
        dispatch_interval_seconds=0,
        verify_interval_seconds=0,
        digest_interval_seconds=0,
        telemetry_poll_interval_seconds=0,
        stats_rollup_interval_seconds=0,
        budget_reconcile_interval_seconds=0,
    )


@pytest.fixture
def app(app_settings: AppSettings) -> Litestar:
    _create_schema(app_settings.database_url)
    return create_app(settings=app_settings)


@pytest.fixture
def client(app: Litestar) -> Iterator[TestClient[Litestar]]:
    with TestClient(app=app) as test_client:
        yield test_client


def client_auth_runtime(client: TestClient[Litestar]) -> AuthRuntime:
    """Reach the app's AuthRuntime through the test client (typed once here)."""
    runtime = cast(Litestar, client.app).state.get("auth_runtime")
    assert isinstance(runtime, AuthRuntime)
    return runtime


def bootstrap_token(client: TestClient[Litestar]) -> str:
    """Return the in-memory first-run bootstrap token minted at startup."""
    token = client_auth_runtime(client).bootstrap.current_token()
    assert token is not None, "bootstrap token was not issued at startup"
    return token


def complete_setup(
    client: TestClient[Litestar],
    *,
    username: str = ADMIN_USERNAME,
    password: str = ADMIN_PASSWORD,
) -> None:
    response = client.post(
        "/api/v1/setup",
        json={
            "username": username,
            "password": password,
            "bootstrapToken": bootstrap_token(client),
        },
    )
    assert response.status_code == 200, response.text
    # POST /api/v1/setup only creates the initial admin now; it no longer marks
    # first-run setup complete (that is POST /api/v1/setup/finish, which needs a
    # Bazarr instance). Existing integration suites just need the gate OPEN, so
    # flip the in-memory AuthRuntime cache: is_setup_completed() then
    # short-circuits True for this app instance (tests reuse one app).
    client_auth_runtime(client).mark_setup_completed()


def csrf_headers(client: TestClient[Litestar]) -> dict[str, str]:
    token = client.cookies.get("csrftoken")
    if token is None:
        _ = client.get("/api/v1/auth/me")  # any safe request sets the cookie
        token = client.cookies.get("csrftoken")
    assert token is not None, "CSRF cookie was never set"
    return {"x-csrftoken": token}
