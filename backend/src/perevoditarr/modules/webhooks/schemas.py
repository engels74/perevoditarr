"""Webhook ingestion DTOs (P5-T3). The token is write-once (FR-A5)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import msgspec
from msgspec import UNSET, UnsetType

from perevoditarr.core.schemas import ApiRequest, ApiStruct

type WebhookKind = Literal["bazarr", "sonarr"]

WebhookName = Annotated[str, msgspec.Meta(min_length=1, max_length=64)]


class WebhookSourceCreate(ApiRequest):
    name: WebhookName
    bazarr_instance_id: UUID
    kind: WebhookKind = "bazarr"


class WebhookSourceUpdate(ApiRequest):
    name: WebhookName | UnsetType = UNSET
    enabled: bool | UnsetType = UNSET


class WebhookSourceRead(ApiStruct):
    id: UUID
    name: str
    bazarr_instance_id: UUID
    kind: WebhookKind
    enabled: bool
    last_received_at: datetime | None
    last_status: str | None
    created_at: datetime


class WebhookSourceCreated(WebhookSourceRead):
    # Relative ingest path with the embedded secret — returned exactly once.
    ingest_path: str
    token: str


class WebhookAck(ApiStruct):
    accepted: bool
    # True when the trigger was suppressed by the coalescing window (a burst).
    coalesced: bool
