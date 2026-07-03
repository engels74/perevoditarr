"""Unit tests for the first-run setup ASGI gate (P6-T1).

The gate runs at ASGI position 0, before JWT auth, so it must stay
user-agnostic: it may only branch on the request path and the durable
`is_setup_completed()` fact, never on `scope['user']`.
"""

from typing import override

import pytest
from litestar.enums import ScopeType
from litestar.types import Receive, Scope, Send

from perevoditarr.core.db import build_alchemy_config
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.auth.security import (
    _SETUP_ALLOWED_PREFIXES,  # pyright: ignore[reportPrivateUsage]  # module-private allow-list is the unit under test
    AuthRuntime,
    SetupRequiredError,
    setup_gate_middleware,
)
from tests.conftest import TEST_SECRET


class _NoUserScope(dict[str, object]):
    """A scope that fails loudly if the gate ever reads scope['user']."""

    @override
    def __getitem__(self, key: str) -> object:
        if key == "user":
            raise AssertionError("setup gate must never read scope['user']")
        return super().__getitem__(key)

    @override
    def get(self, key: str, default: object = None) -> object:
        if key == "user":
            raise AssertionError("setup gate must never read scope['user']")
        return super().get(key, default)


class _FakeApp:
    """Minimal stand-in for the Litestar app: only exposes `.state`."""

    def __init__(self, runtime: AuthRuntime) -> None:
        self.state: dict[str, object] = {"auth_runtime": runtime}


def _runtime(*, completed: bool) -> AuthRuntime:
    settings = AppSettings(secret_key=TEST_SECRET)
    runtime = AuthRuntime(
        settings=settings,
        secret_box=SecretBox(TEST_SECRET),
        alchemy_config=build_alchemy_config(settings),
    )

    async def _is_setup_completed() -> bool:
        return completed

    # Shadow the bound method so the gate never touches a database.
    runtime.is_setup_completed = _is_setup_completed
    return runtime


async def _noop_receive() -> dict[str, object]:  # pragma: no cover - never awaited
    return {"type": "http.request"}


async def _drive(runtime: AuthRuntime, path: str, *, scope_type: str = "http") -> bool:
    """Run the gate for `path`; return whether the downstream app was reached."""
    reached = {"downstream": False}

    async def _downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        reached["downstream"] = True

    gate = setup_gate_middleware(_downstream)
    scope: Scope = _NoUserScope(  # pyright: ignore[reportAssignmentType]  # test double stands in for an ASGI scope
        type=scope_type, path=path, app=_FakeApp(runtime)
    )

    async def _send(_message: object) -> None:  # pragma: no cover - never sent
        return None

    await gate(scope, _noop_receive, _send)  # pyright: ignore[reportArgumentType]  # test doubles for receive/send
    return reached["downstream"]


def test_allow_list_is_exactly_the_wizard_reachable_prefixes() -> None:
    assert _SETUP_ALLOWED_PREFIXES == (
        "/api/v1/setup",
        "/api/v1/health",
        "/api/v1/auth",
        "/api/v1/instances",
        "/api/v1/policy",
        "/api/v1/notifications",
    )


async def test_gate_blocks_non_allow_listed_api_while_incomplete() -> None:
    runtime = _runtime(completed=False)
    with pytest.raises(SetupRequiredError) as excinfo:
        _ = await _drive(runtime, "/api/v1/rails/status")
    assert excinfo.value.code == "setup-required"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/setup/status",
        "/api/v1/health",
        "/api/v1/auth/me",
        "/api/v1/instances/bazarr",
        "/api/v1/policy/presets",
        "/api/v1/notifications/routes",
    ],
)
async def test_gate_passes_allow_listed_prefixes_while_incomplete(path: str) -> None:
    runtime = _runtime(completed=False)
    assert await _drive(runtime, path) is True


@pytest.mark.parametrize("path", ["/", "/setup", "/health", "/static/app.js"])
async def test_gate_ignores_non_api_paths_while_incomplete(path: str) -> None:
    runtime = _runtime(completed=False)
    assert await _drive(runtime, path) is True


async def test_gate_is_a_noop_once_setup_completed() -> None:
    runtime = _runtime(completed=True)
    # Even a normally-gated /api path passes straight through post-completion.
    assert await _drive(runtime, "/api/v1/rails/status") is True


async def test_gate_ignores_non_http_scopes() -> None:
    runtime = _runtime(completed=False)
    # A websocket scope on an otherwise-gated path is not the gate's concern.
    assert (
        await _drive(runtime, "/api/v1/rails/status", scope_type=ScopeType.WEBSOCKET)
        is True
    )
