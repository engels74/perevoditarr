"""Jellyfin API structs (P5-T1). Jellyfin JSON keys are PascalCase."""

import msgspec


class JellyfinUserData(msgspec.Struct, kw_only=True, rename="pascal"):
    play_count: int = 0
    last_played_date: str | None = None
    played: bool = False


class JellyfinItem(msgspec.Struct, kw_only=True, rename="pascal"):
    name: str = ""
    type: str = ""
    series_name: str | None = None
    production_year: int | None = None
    user_data: JellyfinUserData = msgspec.field(default_factory=JellyfinUserData)


class JellyfinItemsResponse(msgspec.Struct, kw_only=True, rename="pascal"):
    items: list[JellyfinItem] = msgspec.field(default_factory=list)
    total_record_count: int = 0


class JellyfinUser(msgspec.Struct, kw_only=True, rename="pascal"):
    id: str = ""
    name: str = ""


class JellyfinSystemInfo(msgspec.Struct, kw_only=True, rename="pascal"):
    server_name: str | None = None
    version: str | None = None
    id: str | None = None
