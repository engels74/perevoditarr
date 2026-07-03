"""Plex MediaContainer structs (P5-T1). JSON is requested via Accept:
application/json; keys are camelCase, `MediaContainer`/`Metadata` capitalized."""

import msgspec


class PlexMetadata(msgspec.Struct, kw_only=True, rename="camel"):
    type: str = ""
    title: str = ""
    grandparent_title: str = ""
    year: int | None = None
    viewed_at: int | None = None


class PlexContainer(msgspec.Struct, kw_only=True):
    metadata: list[PlexMetadata] = msgspec.field(name="Metadata", default_factory=list)


class PlexEnvelope(msgspec.Struct, kw_only=True):
    media_container: PlexContainer = msgspec.field(
        name="MediaContainer", default_factory=PlexContainer
    )


class PlexRootContainer(msgspec.Struct, kw_only=True, rename="camel"):
    friendly_name: str | None = None
    version: str | None = None
    machine_identifier: str | None = None


class PlexRootEnvelope(msgspec.Struct, kw_only=True):
    media_container: PlexRootContainer = msgspec.field(
        name="MediaContainer", default_factory=PlexRootContainer
    )
