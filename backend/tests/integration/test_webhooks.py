"""Webhook ingestion endpoints (P5-T3, FR-X4): CRUD, token validation, coalesce."""

import asyncio

from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.webhooks import WebhookRuntime
from tests.conftest import complete_setup, csrf_headers
from tests.support import as_obj, json_list, json_obj

_VIEWER_PASSWORD = "viewer-pass-1234"


def _seed_instance(database_url: str) -> str:
    async def run() -> str:
        engine = create_async_engine(database_url)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as session:
            instance = BazarrInstance(
                name="bz", url="http://bazarr:6767", api_key_encrypted=b"x"
            )
            session.add(instance)
            await session.commit()
            instance_id = str(instance.id)
        await engine.dispose()
        return instance_id

    return asyncio.run(run())


def _stub_trigger(app: Litestar) -> None:
    runtime = app.state.get("webhook_runtime")
    assert isinstance(runtime, WebhookRuntime)

    async def _noop(_: object) -> None:
        return None

    runtime.set_trigger(_noop)


def _str_field(body: dict[str, object], key: str) -> str:
    value = body[key]
    assert isinstance(value, str)
    return value


def test_webhook_crud_and_ingest(
    client: TestClient[Litestar], app: Litestar, app_settings: AppSettings
) -> None:
    complete_setup(client)
    _stub_trigger(app)
    instance_id = _seed_instance(app_settings.database_url)
    headers = csrf_headers(client)

    created = client.post(
        "/api/v1/webhooks/sources",
        json={"name": "bz-hook", "bazarrInstanceId": instance_id, "kind": "bazarr"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    created_body = json_obj(created)
    token = _str_field(created_body, "token")
    path = _str_field(created_body, "ingestPath")
    assert path.endswith(token)

    # The secret is never persisted in plaintext — the list view omits it.
    listed = json_list(client.get("/api/v1/webhooks/sources"))
    assert len(listed) == 1
    assert "token" not in as_obj(listed[0])

    first = client.post(path)
    assert first.status_code == 202
    assert json_obj(first) == {"accepted": True, "coalesced": False}

    # Immediate repeat is coalesced (burst protection + dedup with polling).
    second = client.post(path)
    assert second.status_code == 202
    assert json_obj(second)["coalesced"] is True

    # An unknown token leaks nothing — plain 404.
    assert client.post("/api/v1/webhooks/ingest/whk_bogus").status_code == 404

    after = as_obj(json_list(client.get("/api/v1/webhooks/sources"))[0])
    assert after["lastReceivedAt"] is not None
    assert after["lastStatus"] == "accepted"


def test_disabled_webhook_rejects_ingest(
    client: TestClient[Litestar], app: Litestar, app_settings: AppSettings
) -> None:
    complete_setup(client)
    _stub_trigger(app)
    instance_id = _seed_instance(app_settings.database_url)
    headers = csrf_headers(client)

    created = client.post(
        "/api/v1/webhooks/sources",
        json={"name": "bz-hook", "bazarrInstanceId": instance_id},
        headers=headers,
    )
    created_body = json_obj(created)
    source_id = _str_field(created_body, "id")
    path = _str_field(created_body, "ingestPath")
    disabled = client.patch(
        f"/api/v1/webhooks/sources/{source_id}",
        json={"enabled": False},
        headers=headers,
    )
    assert disabled.status_code == 200
    assert client.post(path).status_code == 404


def test_viewer_cannot_manage_webhooks(
    client: TestClient[Litestar], app: Litestar
) -> None:
    complete_setup(client)
    _stub_trigger(app)
    headers = csrf_headers(client)
    _ = client.post(
        "/api/v1/auth/users",
        json={"username": "viewer1", "password": _VIEWER_PASSWORD, "role": "viewer"},
        headers=headers,
    )
    _ = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer1", "password": _VIEWER_PASSWORD},
    )
    assert client.get("/api/v1/webhooks/sources").status_code == 403
