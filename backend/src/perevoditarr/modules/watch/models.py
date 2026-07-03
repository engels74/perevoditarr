"""Watch-integration ORM models (P5-T1). No `from __future__ import annotations`.

`watch_source` is a configured Tautulli/Plex/Jellyfin server (credentials
Fernet-encrypted, FR-A5). `watch_score` is the durable score cache (PRD §11):
one aggregated signal per §6.5 title identity, refreshed on a TTL by the watch
refresh loop and read by discovery's scorer. Watch data is a soft signal only
(ADR-0007), so this is deliberately not instance-scoped — it describes media,
not a Bazarr instance.
"""

from datetime import datetime

from advanced_alchemy.types import JsonB
from sqlalchemy import DateTime, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import SchemaItem

from perevoditarr.core.db import UUIDAuditBase


class WatchSource(UUIDAuditBase):
    __tablename__: str | None = "watch_source"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    # tautulli | plex | jellyfin
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    url: Mapped[str] = mapped_column(String(512))
    # API key / token, encrypted at rest (FR-A5); never returned after write.
    credential_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(default=True)
    # Per-source options: e.g. Jellyfin {"user": "..."}, Plex
    # {"includeWatchlist": true}. msgspec-typed at the service boundary.
    config: Mapped[dict[str, object] | None] = mapped_column(JsonB)
    health_snapshot: Mapped[dict[str, object] | None] = mapped_column(JsonB)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WatchScore(UUIDAuditBase):
    __tablename__: str | None = "watch_score"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint(
            "media_type", "title_key", "year", name="uq_watch_score_identity"
        ),
    )

    # show | movie
    media_type: Mapped[str] = mapped_column(String(8), index=True)
    # normalize_title() output — the join key against the mirror's display title.
    title_key: Mapped[str] = mapped_column(String(255), index=True)
    # Original title for display/debug (unnormalized).
    title: Mapped[str] = mapped_column(String(512))
    # 0 for shows / unknown (kept non-null so the unique index is portable).
    year: Mapped[int] = mapped_column(Integer, default=0)
    watched_recently: Mapped[bool] = mapped_column(default=False)
    watched_frequently: Mapped[bool] = mapped_column(default=False)
    watchlisted: Mapped[bool] = mapped_column(default=False)
    # Source names that contributed, for the plan-preview trace.
    sources: Mapped[list[str]] = mapped_column(JsonB, default=list)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
