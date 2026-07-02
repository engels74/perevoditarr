"""Notifications API DTOs (P3-T5). camelCase on the wire; URLs never leave in
plaintext (FR-A5) — reads carry only a masked `scheme://***` hint."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

import msgspec
from msgspec import UNSET, UnsetType

from perevoditarr.core.schemas import ApiRequest, ApiStruct
from perevoditarr.modules.notifications.events import NotificationEvent

RouteName = Annotated[str, msgspec.Meta(min_length=1, max_length=64)]
AppriseUrl = Annotated[str, msgspec.Meta(min_length=3, max_length=2048)]
EventList = Annotated[list[NotificationEvent], msgspec.Meta(max_length=16)]


class NotificationRouteRead(ApiStruct):
    id: UUID
    name: str
    enabled: bool
    events: list[str]
    url_masked: str
    created_at: datetime


class NotificationRouteCreate(ApiRequest):
    name: RouteName
    url: AppriseUrl
    enabled: bool = True
    events: EventList = msgspec.field(default_factory=list)


class NotificationRouteUpdate(ApiRequest):
    name: RouteName | UnsetType = UNSET
    url: AppriseUrl | UnsetType = UNSET
    enabled: bool | UnsetType = UNSET
    events: EventList | UnsetType = UNSET


class TestFireResult(ApiStruct):
    route_id: UUID
    sent: bool
    detail: str


class DigestResult(ApiStruct):
    generated_at: datetime
    routes_notified: int
    converged: int
    superseded: int
    failed: int
    estimated_characters: int


def mask_url(url: str) -> str:
    scheme, sep, _ = url.partition("://")
    return f"{scheme}://***" if sep else "***"
