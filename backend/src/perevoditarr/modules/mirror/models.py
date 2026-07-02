"""Library mirror ORM models (P1-T5). No `from __future__ import annotations`.

Instance-scoped (FR-I4), sized for 100k+ episodes / 300k+ subtitle rows per
instance (FR-M3/NFR-2). Append-heavy tables ride UUIDv7 keys (ADR-0005).
Composite indexes cover the browser's filter/sort paths: coverage per
language, title search, series drill-down, wanted-by-language.
"""

from datetime import date, datetime
from uuid import UUID

from advanced_alchemy.types import JsonB
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from perevoditarr.core.db import UUIDv7AuditBase


class Series(UUIDv7AuditBase):
    __tablename__ = "series"
    __table_args__ = (
        UniqueConstraint("bazarr_instance_id", "sonarr_series_id"),
        Index("ix_series_instance_sort_title", "bazarr_instance_id", "sort_title"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    sonarr_series_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    sort_title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    monitored: Mapped[bool] = mapped_column(default=True)
    ended: Mapped[bool | None] = mapped_column(default=None)
    profile_id: Mapped[int | None] = mapped_column(Integer)
    audio_language: Mapped[list[dict[str, object]] | None] = mapped_column(JsonB)
    tags: Mapped[list[str] | None] = mapped_column(JsonB)
    episode_count: Mapped[int] = mapped_column(Integer, default=0)

    episodes: Mapped[list[Episode]] = relationship(
        back_populates="series", lazy="raise", cascade="all, delete-orphan"
    )


class Episode(UUIDv7AuditBase):
    __tablename__ = "episode"
    __table_args__ = (
        UniqueConstraint("bazarr_instance_id", "sonarr_episode_id"),
        Index(
            "ix_episode_instance_series_number",
            "bazarr_instance_id",
            "sonarr_series_id",
            "season",
            "episode",
        ),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), index=True
    )
    # Denormalized Sonarr ids: the §6.5 in-flight lookups and sync upserts key
    # on them without a join.
    sonarr_series_id: Mapped[int] = mapped_column(Integer)
    sonarr_episode_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    season: Mapped[int] = mapped_column(Integer)
    episode: Mapped[int] = mapped_column(Integer)
    monitored: Mapped[bool] = mapped_column(default=True)
    air_date: Mapped[date | None] = mapped_column(Date)
    audio_language: Mapped[list[dict[str, object]] | None] = mapped_column(JsonB)

    series: Mapped[Series] = relationship(back_populates="episodes", lazy="raise")
    subtitles: Mapped[list[Subtitle]] = relationship(
        back_populates="episode",
        lazy="raise",
        cascade="all, delete-orphan",
        foreign_keys="Subtitle.episode_id",
    )


class Movie(UUIDv7AuditBase):
    __tablename__ = "movie"
    __table_args__ = (
        UniqueConstraint("bazarr_instance_id", "radarr_id"),
        Index("ix_movie_instance_sort_title", "bazarr_instance_id", "sort_title"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    radarr_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    sort_title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    monitored: Mapped[bool] = mapped_column(default=True)
    profile_id: Mapped[int | None] = mapped_column(Integer)
    audio_language: Mapped[list[dict[str, object]] | None] = mapped_column(JsonB)
    tags: Mapped[list[str] | None] = mapped_column(JsonB)

    subtitles: Mapped[list[Subtitle]] = relationship(
        back_populates="movie",
        lazy="raise",
        cascade="all, delete-orphan",
        foreign_keys="Subtitle.movie_id",
    )


class Subtitle(UUIDv7AuditBase):
    """An existing subtitle (file or embedded track) as Bazarr reports it."""

    __tablename__ = "subtitle"
    __table_args__ = (
        Index("ix_subtitle_instance_language", "bazarr_instance_id", "language"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    episode_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("episode.id", ondelete="CASCADE"), index=True
    )
    movie_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("movie.id", ondelete="CASCADE"), index=True
    )
    language: Mapped[str] = mapped_column(String(8))  # Bazarr code2 space (FR-P4)
    forced: Mapped[bool] = mapped_column(default=False)
    hi: Mapped[bool] = mapped_column(default=False)
    # Null path = embedded track (no file on disk from Bazarr's perspective).
    file_path: Mapped[str | None] = mapped_column(Text)

    episode: Mapped[Episode | None] = relationship(
        back_populates="subtitles", lazy="raise", foreign_keys=[episode_id]
    )
    movie: Mapped[Movie | None] = relationship(
        back_populates="subtitles", lazy="raise", foreign_keys=[movie_id]
    )


class WantedSubtitle(UUIDv7AuditBase):
    """A missing subtitle Bazarr wants — the discovery feed (FR-M1/FR-P1)."""

    __tablename__ = "wanted_subtitle"
    __table_args__ = (
        # Explicit names: both constraints start with bazarr_instance_id, and
        # the naming convention (uq_<table>_<column_0_name>) keys off only the
        # first column, so the default-generated names collide (PostgreSQL
        # then rejects the second CREATE as a duplicate object).
        UniqueConstraint(
            "bazarr_instance_id",
            "episode_id",
            "language",
            "forced",
            "hi",
            name="uq_wanted_subtitle_bazarr_instance_id_episode_id",
        ),
        UniqueConstraint(
            "bazarr_instance_id",
            "movie_id",
            "language",
            "forced",
            "hi",
            name="uq_wanted_subtitle_bazarr_instance_id_movie_id",
        ),
        Index("ix_wanted_instance_language", "bazarr_instance_id", "language"),
        Index("ix_wanted_instance_last_seen", "bazarr_instance_id", "last_seen_at"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    episode_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("episode.id", ondelete="CASCADE"), index=True
    )
    movie_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("movie.id", ondelete="CASCADE"), index=True
    )
    language: Mapped[str] = mapped_column(String(8))
    forced: Mapped[bool] = mapped_column(default=False)
    hi: Mapped[bool] = mapped_column(default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Disappearance from Bazarr's wanted list => candidate withdrawal (P2-T3);
    # rows are matched against last_seen_at instead of being hard-deleted
    # mid-sync so a crashed sync never fabricates withdrawals (FR-R4 spirit).
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncRun(UUIDv7AuditBase):
    __tablename__ = "sync_run"
    __table_args__ = (
        Index("ix_sync_run_instance_created", "bazarr_instance_id", "created_at"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # full | incremental | wanted
    status: Mapped[str] = mapped_column(String(16))  # running | completed | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counters: Mapped[dict[str, int] | None] = mapped_column(JsonB)
    error: Mapped[str | None] = mapped_column(Text)
