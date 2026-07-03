"""Webhook controller (P5-T3): admin CRUD + token-validated ingestion.

Management endpoints are admin-only; the ingest endpoint is unauthenticated
(Bazarr/Sonarr can't carry a session) and validated purely by the secret token
in the path — an unknown/disabled token returns 404 without leaking which."""

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from litestar import Controller, delete, get, patch, post
from litestar.datastructures import State
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import NotFoundError
from perevoditarr.modules.auth.security import require_admin
from perevoditarr.modules.webhooks.runtime import WebhookRuntime
from perevoditarr.modules.webhooks.schemas import (
    WebhookAck,
    WebhookKind,
    WebhookSourceCreate,
    WebhookSourceCreated,
    WebhookSourceRead,
    WebhookSourceUpdate,
)
from perevoditarr.modules.webhooks.service import (
    WebhookService,
    ingest_path,
    webhook_read,
)


async def provide_webhook_service(db_session: AsyncSession) -> WebhookService:
    return WebhookService(db_session)


def provide_webhook_runtime(state: State) -> WebhookRuntime:
    runtime: object = state.get("webhook_runtime")
    if not isinstance(runtime, WebhookRuntime):
        raise RuntimeError("webhook runtime is not configured on app.state")
    return runtime


class WebhookController(Controller):
    path: str = "/webhooks"
    tags: Sequence[str] | None = ("webhooks",)

    @get("/sources", guards=[require_admin], operation_id="listWebhookSources")
    async def list_sources(
        self, webhook_service: WebhookService
    ) -> list[WebhookSourceRead]:
        return [webhook_read(row) for row in await webhook_service.list_sources()]

    @post("/sources", guards=[require_admin], operation_id="createWebhookSource")
    async def create_source(
        self, data: WebhookSourceCreate, webhook_service: WebhookService
    ) -> WebhookSourceCreated:
        source, token = await webhook_service.create_source(data)
        return WebhookSourceCreated(
            id=source.id,
            name=source.name,
            bazarr_instance_id=source.bazarr_instance_id,
            kind=cast("WebhookKind", source.kind),
            enabled=source.enabled,
            last_received_at=source.last_received_at,
            last_status=source.last_status,
            created_at=source.created_at,
            ingest_path=ingest_path(token),
            token=token,
        )

    @patch(
        "/sources/{source_id:uuid}",
        guards=[require_admin],
        operation_id="updateWebhookSource",
    )
    async def update_source(
        self,
        source_id: UUID,
        data: WebhookSourceUpdate,
        webhook_service: WebhookService,
    ) -> WebhookSourceRead:
        return webhook_read(await webhook_service.update_source(source_id, data))

    @delete(
        "/sources/{source_id:uuid}",
        guards=[require_admin],
        operation_id="deleteWebhookSource",
    )
    async def delete_source(
        self, source_id: UUID, webhook_service: WebhookService
    ) -> None:
        await webhook_service.delete_source(source_id)

    @post(
        "/ingest/{token:str}",
        exclude_from_auth=True,
        status_code=202,
        operation_id="ingestWebhook",
    )
    async def ingest(
        self,
        token: str,
        webhook_service: WebhookService,
        webhook_runtime: WebhookRuntime,
    ) -> WebhookAck:
        source = await webhook_service.resolve(token)
        if source is None or not source.enabled:
            raise NotFoundError("unknown or disabled webhook endpoint")
        await webhook_service.record_received(source)
        fired = webhook_runtime.schedule(source.bazarr_instance_id)
        return WebhookAck(accepted=True, coalesced=not fired)
