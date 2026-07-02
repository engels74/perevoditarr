"""Statistics ORM models (P4-T1, FR-U8). No `from __future__ import annotations`.

Two durable surfaces:

* `StatsDaily` — per-(Bazarr instance, day, media type) rollup counters, so the
  stats API answers throughput/failure-rate/outcome-mix questions with a cheap
  indexed range scan instead of re-aggregating the whole `intent_event` audit
  trail at request time (the plan's "efficient rollup tables" requirement). The
  rollup job re-derives each day's row from durable evidence, so it stays
  restart-safe (FR-R4) and never double-counts across a crash.
* `LingarrActuals` — the latest rolling actuals snapshot per Lingarr instance,
  reconciled from Lingarr's own statistics API (§6.7 authoritative). It corrects
  the conservative volume heuristics feeding the estimator (P2-T5) and the
  budget rails (P3-T1).

Both stay dialect-portable (NFR-2): plain integer/float/date columns, no
JSON-path queries.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import SchemaItem

from perevoditarr.core.db import UUIDAuditBase


class StatsDaily(UUIDAuditBase):
    """One row per (Bazarr instance, UTC day, media type): the outcome counters
    the stats dashboard charts. Re-derived by the rollup job from `intent_event`
    transition rows in the day's window (idempotent upsert)."""

    __tablename__: str | None = "stats_daily"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint(
            "bazarr_instance_id",
            "day",
            "media_type",
            name="uq_stats_daily_instance_day_media",
        ),
        Index("ix_stats_daily_instance_day", "bazarr_instance_id", "day"),
        Index("ix_stats_daily_day", "day"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date)
    media_type: Mapped[str] = mapped_column(String(8))  # episode | movie
    dispatched: Mapped[int] = mapped_column(Integer, default=0)
    converged: Mapped[int] = mapped_column(Integer, default=0)
    superseded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    # Failure taxonomy split (§7.4), read from each failed event's evidence.
    failed_transient: Mapped[int] = mapped_column(Integer, default=0)
    failed_environmental: Mapped[int] = mapped_column(Integer, default=0)
    failed_provider: Mapped[int] = mapped_column(Integer, default=0)
    failed_poison: Mapped[int] = mapped_column(Integer, default=0)
    # Estimated translated volume for converged intents in the window.
    converged_characters: Mapped[int] = mapped_column(Integer, default=0)
    # Dispatch->convergence latency (FR-U8 "durations"): running sum + sample
    # count so the API can report a mean without storing every observation.
    duration_seconds_total: Mapped[int] = mapped_column(Integer, default=0)
    duration_samples: Mapped[int] = mapped_column(Integer, default=0)


class LingarrActuals(UUIDAuditBase):
    """Rolling per-file averages reconciled from Lingarr's statistics API, one
    row per Lingarr instance (latest snapshot; the reconcile job upserts it)."""

    __tablename__: str | None = "lingarr_actuals"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint(
            "lingarr_instance_id", name="uq_lingarr_actuals_lingarr_instance_id"
        ),
    )

    lingarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("lingarr_instance.id", ondelete="CASCADE"), index=True
    )
    sample_files: Mapped[int] = mapped_column(Integer, default=0)
    lines_per_file: Mapped[float] = mapped_column(Float, default=0.0)
    characters_per_file: Mapped[float] = mapped_column(Float, default=0.0)
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    total_lines: Mapped[int] = mapped_column(Integer, default=0)
    total_characters: Mapped[int] = mapped_column(Integer, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StatsLanguageDaily(UUIDAuditBase):
    """Per-(Bazarr instance, day, target language) converged counter: the
    monotonic coverage-growth series the dashboard trends (FR-U8)."""

    __tablename__: str | None = "stats_language_daily"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint(
            "bazarr_instance_id",
            "day",
            "target_language",
            name="uq_stats_language_daily_instance_day_language",
        ),
        Index("ix_stats_language_daily_instance_day", "bazarr_instance_id", "day"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date)
    target_language: Mapped[str] = mapped_column(String(8))
    converged: Mapped[int] = mapped_column(Integer, default=0)
