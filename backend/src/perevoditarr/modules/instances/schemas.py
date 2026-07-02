"""Instances API DTOs (P1-T4). API keys are write-only (FR-A5)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import msgspec
from msgspec import UNSET, UnsetType

from perevoditarr.core.schemas import ApiRequest, ApiStruct

InstanceName = Annotated[str, msgspec.Meta(min_length=1, max_length=64)]
InstanceUrl = Annotated[
    str, msgspec.Meta(min_length=1, max_length=512, pattern=r"^https?://")
]

type HealthStatusValue = Literal["ok", "degraded", "unreachable", "unknown"]


class BazarrCapabilities(ApiStruct):
    """Capability-detection slots (PRD §6.6): both false for every released
    Bazarr/Lingarr pair today — by design, nothing may depend on them flipping."""

    translate_returns_job_id: bool = False
    lingarr_receives_episode_id: bool = False
    probed_at: datetime | None = None


class InstanceHealth(ApiStruct):
    status: HealthStatusValue = "unknown"
    latency_ms: float | None = None
    checked_at: datetime | None = None
    queue_depth: int | None = None
    version: str | None = None
    detail: str | None = None


class BazarrInstanceCreate(ApiRequest):
    name: InstanceName
    url: InstanceUrl
    api_key: Annotated[str, msgspec.Meta(min_length=1, max_length=256)]
    enabled: bool = True


class BazarrInstanceUpdate(ApiRequest):
    name: InstanceName | UnsetType = UNSET
    url: InstanceUrl | UnsetType = UNSET
    api_key: Annotated[str, msgspec.Meta(min_length=1, max_length=256)] | UnsetType = (
        UNSET
    )
    enabled: bool | UnsetType = UNSET
    lingarr_instance_id: UUID | None | UnsetType = UNSET


class BazarrInstanceRead(ApiStruct):
    id: UUID
    name: str
    url: str
    enabled: bool
    version: str | None
    lingarr_instance_id: UUID | None
    capabilities: BazarrCapabilities | None
    health: InstanceHealth | None
    created_at: datetime


class LingarrInstanceCreate(ApiRequest):
    name: InstanceName
    url: InstanceUrl
    api_key: Annotated[str, msgspec.Meta(max_length=256)] | None = None
    enabled: bool = True


class LingarrInstanceUpdate(ApiRequest):
    name: InstanceName | UnsetType = UNSET
    url: InstanceUrl | UnsetType = UNSET
    api_key: Annotated[str, msgspec.Meta(max_length=256)] | None | UnsetType = UNSET
    enabled: bool | UnsetType = UNSET


class LingarrInstanceRead(ApiStruct):
    id: UUID
    name: str
    url: str
    enabled: bool
    version: str | None
    has_api_key: bool
    health: InstanceHealth | None
    created_at: datetime


class ConnectionTestRequest(ApiRequest):
    """Dry validation before persisting (P1-T4): nothing is stored."""

    kind: Literal["bazarr", "lingarr"]
    url: InstanceUrl
    api_key: str | None = None


class ConnectionTestResult(ApiStruct):
    reachable: bool
    version: str | None = None
    version_supported: bool | None = None
    latency_ms: float | None = None
    error: str | None = None


class LingarrDiscoveryResult(ApiStruct):
    """What Bazarr's settings say about its configured Lingarr (FR-I2)."""

    configured: bool
    url: str | None = None
    has_api_key: bool = False


class LingarrDiscoveryConfirm(ApiRequest):
    """One-click confirmation: create/link the discovered Lingarr instance."""

    name: InstanceName
