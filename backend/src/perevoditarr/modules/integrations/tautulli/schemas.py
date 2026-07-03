"""Tautulli API response structs (P5-T1). Boundary decode tolerates additive
upstream fields (forbid_unknown_fields=False, the msgspec default)."""

import msgspec


class HistoryRow(msgspec.Struct, kw_only=True):
    date: int | None = None
    media_type: str = ""
    title: str = ""
    full_title: str = ""
    grandparent_title: str = ""
    # Tautulli reports year as int on newer builds, occasionally a string.
    year: int | str | None = None
    group_count: int = 1


class HistoryData(msgspec.Struct, kw_only=True):
    data: list[HistoryRow] = msgspec.field(default_factory=list)


class HistoryResponse(msgspec.Struct, kw_only=True):
    result: str = "error"
    message: str | None = None
    data: HistoryData | None = None


class HistoryEnvelope(msgspec.Struct, kw_only=True):
    response: HistoryResponse


class ServerInfoData(msgspec.Struct, kw_only=True):
    pms_name: str | None = None
    pms_version: str | None = None
    pms_identifier: str | None = None


class ServerInfoResponse(msgspec.Struct, kw_only=True):
    result: str = "error"
    message: str | None = None
    data: ServerInfoData | None = None


class ServerInfoEnvelope(msgspec.Struct, kw_only=True):
    response: ServerInfoResponse
