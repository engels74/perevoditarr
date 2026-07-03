"""Webhook source service (P5-T3): CRUD, token minting, token resolution."""

import hashlib
import secrets
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from advanced_alchemy.exceptions import NotFoundError as AANotFoundError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from msgspec import UNSET
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import ConflictError, NotFoundError
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.webhooks.models import WebhookSource
from perevoditarr.modules.webhooks.schemas import (
    WebhookKind,
    WebhookSourceCreate,
    WebhookSourceRead,
    WebhookSourceUpdate,
)

WEBHOOK_TOKEN_PREFIX = "whk_"
INGEST_PATH = "/api/v1/webhooks/ingest"


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ingest_path(token: str) -> str:
    return f"{INGEST_PATH}/{token}"


def webhook_read(row: WebhookSource) -> WebhookSourceRead:
    return WebhookSourceRead(
        id=row.id,
        name=row.name,
        bazarr_instance_id=row.bazarr_instance_id,
        kind=cast("WebhookKind", row.kind),
        enabled=row.enabled,
        last_received_at=row.last_received_at,
        last_status=row.last_status,
        created_at=row.created_at,
    )


class WebhookSourceRepository(SQLAlchemyAsyncRepository[WebhookSource]):
    model_type: type[WebhookSource] = WebhookSource


class WebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session
        self.repo: WebhookSourceRepository = WebhookSourceRepository(session=session)

    async def list_sources(self) -> list[WebhookSource]:
        return list(await self.repo.list(order_by=[("name", False)]))

    async def get_source(self, source_id: UUID) -> WebhookSource:
        try:
            return await self.repo.get(source_id)
        except AANotFoundError as error:
            raise NotFoundError(f"webhook source {source_id} not found") from error

    async def create_source(
        self, data: WebhookSourceCreate
    ) -> tuple[WebhookSource, str]:
        await self._ensure_unique_name(data.name)
        await self._ensure_instance(data.bazarr_instance_id)
        raw = WEBHOOK_TOKEN_PREFIX + secrets.token_urlsafe(32)
        source = WebhookSource(
            name=data.name,
            bazarr_instance_id=data.bazarr_instance_id,
            kind=data.kind,
            token_hash=_hash_token(raw),
            enabled=True,
        )
        self.session.add(source)
        await self.session.commit()
        return source, raw

    async def update_source(
        self, source_id: UUID, data: WebhookSourceUpdate
    ) -> WebhookSource:
        source = await self.get_source(source_id)
        if data.name is not UNSET and data.name != source.name:
            await self._ensure_unique_name(data.name)
            source.name = data.name
        if data.enabled is not UNSET:
            source.enabled = data.enabled
        await self.session.commit()
        return source

    async def delete_source(self, source_id: UUID) -> None:
        _ = await self.get_source(source_id)
        _ = await self.repo.delete(source_id)
        await self.session.commit()

    async def resolve(self, token: str) -> WebhookSource | None:
        return (
            await self.session.scalars(
                select(WebhookSource).where(
                    WebhookSource.token_hash == _hash_token(token)
                )
            )
        ).one_or_none()

    async def record_received(
        self, source: WebhookSource, *, status: str = "accepted"
    ) -> None:
        source.last_received_at = datetime.now(UTC)
        source.last_status = status
        await self.session.commit()

    async def _ensure_instance(self, instance_id: UUID) -> None:
        exists = (
            await self.session.scalars(
                select(BazarrInstance.id).where(BazarrInstance.id == instance_id)
            )
        ).first()
        if exists is None:
            raise NotFoundError(f"Bazarr instance {instance_id} not found")

    async def _ensure_unique_name(self, name: str) -> None:
        existing = (
            await self.session.scalars(
                select(WebhookSource.id).where(WebhookSource.name == name)
            )
        ).first()
        if existing is not None:
            raise ConflictError(f"a webhook source named {name!r} already exists")
