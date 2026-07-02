"""Typed Lingarr API response structs (P1-T3, PRD Appendix A).

Lingarr serializes camelCase JSON with string enums (validated against the
1.2.4 line source). Decoding is tolerant of additive upstream fields.
"""

from datetime import datetime
from typing import Literal

import msgspec

type TranslationStatusValue = Literal[
    "Pending", "InProgress", "Completed", "Failed", "Cancelled", "Interrupted"
]
type LingarrMediaType = Literal["Movie", "Show", "Season", "Episode"]

# Active means dedup-relevant (PRD §6.4): Pending or InProgress.
ACTIVE_STATUSES: frozenset[str] = frozenset({"Pending", "InProgress"})


class VersionInfo(msgspec.Struct, kw_only=True, rename="camel"):
    new_version: bool = False
    is_development: bool = False
    current_version: str | None = None
    latest_version: str | None = None


class TranslationRequestRecord(msgspec.Struct, kw_only=True, rename="camel"):
    id: int
    job_id: str | None = None
    media_id: int | None = None
    title: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    subtitle_to_translate: str | None = None
    translated_subtitle: str | None = None
    media_type: str | None = None
    status: str | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ActiveTranslation(msgspec.Struct, kw_only=True, rename="camel"):
    """§6.5 granularity: no episode identity, only media id + type + status."""

    media_id: int | None = None
    media_type: str | None = None
    status: str | None = None


class PagedTranslationRequests(msgspec.Struct, kw_only=True, rename="camel"):
    items: list[TranslationRequestRecord] = msgspec.field(default_factory=list)
    total_count: int = 0
    page_number: int = 1
    page_size: int = 20


class LingarrStatistics(msgspec.Struct, kw_only=True, rename="camel"):
    total_lines_translated: int = 0
    total_files_translated: int = 0
    total_characters_translated: int = 0
    total_movies: int = 0
    total_episodes: int = 0
    total_subtitles: int = 0
    translations_by_media_type: dict[str, int] = msgspec.field(default_factory=dict)
    translations_by_service: dict[str, int] = msgspec.field(default_factory=dict)
    subtitles_by_language: dict[str, int] = msgspec.field(default_factory=dict)


class OnboardingRequired(msgspec.Struct, kw_only=True, rename="camel"):
    message: str | None = None
    onboarding_required: bool = False
