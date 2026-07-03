"""Watch-integration API DTOs (P5-T1). Credentials are write-only (FR-A5)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

import msgspec
from msgspec import UNSET, UnsetType

from perevoditarr.core.schemas import ApiRequest, ApiStruct
from perevoditarr.modules.integrations.watch import WatchSourceType

WatchSourceName = Annotated[str, msgspec.Meta(min_length=1, max_length=64)]
WatchSourceUrl = Annotated[
    str, msgspec.Meta(min_length=1, max_length=512, pattern=r"^https?://")
]
WatchCredential = Annotated[str, msgspec.Meta(min_length=1, max_length=512)]


class WatchSourceConfig(msgspec.Struct, kw_only=True, rename="camel"):
    """Per-source options, stored as the source's JSON config column."""

    # Jellyfin: which user's playback data to read (defaults to the first user).
    jellyfin_user: str | None = None
    # Plex: also pull the account watchlist from discover.provider.plex.tv.
    include_watchlist: bool = True


class WatchSourceCreate(ApiRequest):
    name: WatchSourceName
    source_type: WatchSourceType
    url: WatchSourceUrl
    credential: WatchCredential
    enabled: bool = True
    config: WatchSourceConfig = msgspec.field(default_factory=WatchSourceConfig)


class WatchSourceUpdate(ApiRequest):
    name: WatchSourceName | UnsetType = UNSET
    url: WatchSourceUrl | UnsetType = UNSET
    credential: WatchCredential | UnsetType = UNSET
    enabled: bool | UnsetType = UNSET
    config: WatchSourceConfig | UnsetType = UNSET


class WatchSourceHealth(ApiStruct):
    reachable: bool
    identity: str | None = None
    version: str | None = None
    detail: str | None = None
    checked_at: datetime | None = None


class WatchSourceRead(ApiStruct):
    id: UUID
    name: str
    source_type: WatchSourceType
    url: str
    has_credential: bool
    enabled: bool
    config: WatchSourceConfig
    health: WatchSourceHealth | None
    last_refreshed_at: datetime | None
    created_at: datetime


class WatchSourceTestRequest(ApiRequest):
    """Dry connectivity check before persisting: nothing is stored."""

    source_type: WatchSourceType
    url: WatchSourceUrl
    credential: WatchCredential
    config: WatchSourceConfig = msgspec.field(default_factory=WatchSourceConfig)


class WatchSourceTestResult(ApiStruct):
    reachable: bool
    identity: str | None = None
    version: str | None = None
    detail: str | None = None


class WatchRefreshResult(ApiStruct):
    """Outcome of a manual/scheduled cache refresh."""

    sources_polled: int
    sources_failed: int
    titles_scored: int
