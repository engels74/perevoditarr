"""Mirror API DTOs (P1-T5). The UI browses the mirror, never Bazarr (FR-M1)."""

from datetime import date, datetime
from uuid import UUID

from perevoditarr.core.schemas import ApiStruct


class SubtitleRead(ApiStruct):
    language: str
    forced: bool
    hi: bool
    is_embedded: bool


class WantedRead(ApiStruct):
    language: str
    forced: bool
    hi: bool


class SeriesRead(ApiStruct):
    id: UUID
    bazarr_instance_id: UUID
    sonarr_series_id: int
    title: str
    year: int | None
    monitored: bool
    ended: bool | None
    episode_count: int
    wanted_count: int


class EpisodeRead(ApiStruct):
    id: UUID
    sonarr_series_id: int
    sonarr_episode_id: int
    title: str
    season: int
    episode: int
    monitored: bool
    air_date: date | None
    subtitles: list[SubtitleRead]
    wanted: list[WantedRead]


class MovieRead(ApiStruct):
    id: UUID
    bazarr_instance_id: UUID
    radarr_id: int
    title: str
    year: int | None
    monitored: bool
    subtitles: list[SubtitleRead]
    wanted: list[WantedRead]


class CoverageStat(ApiStruct):
    language: str
    episodes_with_subtitle: int
    movies_with_subtitle: int
    episodes_wanted: int
    movies_wanted: int


class SyncRunRead(ApiStruct):
    id: UUID
    bazarr_instance_id: UUID
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    counters: dict[str, int] | None
    error: str | None


class FreshnessRead(ApiStruct):
    bazarr_instance_id: UUID
    last_full_sync_at: datetime | None
    last_wanted_sync_at: datetime | None
    stale: bool
