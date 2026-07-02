"""Intent ledger ORM models (P2-T2, FR-R1). No `from __future__ import annotations`.

`intent` is natural-key-unique per PRD §7.1: one row per desired translation,
keyed on stable *arr ids (mirror rows are volatile across resyncs, so the
identity never references mirror UUIDs). `sonarr_series_id` is denormalized so
the §6.5 scheduling-invariant lookup — one in-flight per (instance, series,
source→target) — needs no join. `intent_event` is the append-only audit trail
(FR-V1/V2): every state transition writes exactly one row, never updated or
deleted. Bases per ADR-0005: intents are long-lived mutable rows
(UUIDAuditBase); events are append-heavy (UUIDv7AuditBase).
"""

from datetime import datetime
from uuid import UUID

from advanced_alchemy.types import JsonB
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import SchemaItem

from perevoditarr.core.db import UUIDAuditBase, UUIDv7AuditBase


class Intent(UUIDAuditBase):
    __tablename__: str | None = "intent"
    __table_args__: tuple[SchemaItem, ...] = (
        # Natural identity (PRD §7.1): re-discovery upserts, never duplicates.
        UniqueConstraint(
            "bazarr_instance_id",
            "media_type",
            "external_media_id",
            "target_language",
            "forced",
            "hi",
            name="uq_intent_identity",
        ),
        # Backlog scans: state IN (...) ORDER BY priority.
        Index("ix_intent_state_priority", "state", "priority"),
        Index("ix_intent_instance_state", "bazarr_instance_id", "state"),
        # §6.5 series-pair in-flight lookup (movies ride the unique's prefix).
        Index(
            "ix_intent_series_pair",
            "bazarr_instance_id",
            "sonarr_series_id",
            "source_language",
            "target_language",
        ),
        Index("ix_intent_created_at", "created_at"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    media_type: Mapped[str] = mapped_column(String(8))  # episode | movie
    # sonarr_episode_id for episodes, radarr_id for movies.
    external_media_id: Mapped[int] = mapped_column(Integer)
    sonarr_series_id: Mapped[int | None] = mapped_column(Integer)
    season: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    # Show title for episodes, movie title for movies — the §6.5-granularity
    # display/matching title (what Lingarr sees as `title`).
    display_title: Mapped[str] = mapped_column(String(512))
    source_language: Mapped[str] = mapped_column(String(8))  # Bazarr code2
    target_language: Mapped[str] = mapped_column(String(8))
    forced: Mapped[bool] = mapped_column(default=False)
    hi: Mapped[bool] = mapped_column(default=False)
    state: Mapped[str] = mapped_column(String(16), default="discovered")
    # Set at dispatch (P3): deadline by which convergence evidence is expected.
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    # Manual bump-to-front (FR-Q4): set = jumps the backlog, newest bump first.
    bumped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # msgspec-encoded trace.TraceStep list, decoded at the service boundary.
    decision_trace: Mapped[list[dict[str, object]] | None] = mapped_column(JsonB)

    events: Mapped[list[IntentEvent]] = relationship(
        back_populates="intent",
        lazy="raise",
        cascade="all, delete-orphan",
        order_by="IntentEvent.created_at",
    )


class IntentEvent(UUIDv7AuditBase):
    __tablename__: str | None = "intent_event"
    __table_args__: tuple[SchemaItem, ...] = (
        Index("ix_intent_event_intent_created", "intent_id", "created_at"),
    )

    intent_id: Mapped[UUID] = mapped_column(
        ForeignKey("intent.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(
        String(64)
    )  # discovery|reconciler|startup|user:*
    from_state: Mapped[str | None] = mapped_column(String(16))  # None = creation
    to_state: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    # Durable-evidence snapshot backing the transition (§6.8) — never telemetry.
    evidence: Mapped[dict[str, object] | None] = mapped_column(JsonB)

    intent: Mapped[Intent] = relationship(back_populates="events", lazy="raise")


class PassthroughAction(UUIDv7AuditBase):
    """Audit trail for user-initiated Lingarr pass-through actions (P4-T2,
    FR-X3): each cancel/retry/resume/remove acting on a Lingarr request is
    recorded here (never automated) so the item timeline shows exactly who did
    what and whether Lingarr accepted it. Append-only, like intent_event."""

    __tablename__: str | None = "passthrough_action"
    __table_args__: tuple[SchemaItem, ...] = (
        Index("ix_passthrough_action_intent_created", "intent_id", "created_at"),
    )

    intent_id: Mapped[UUID] = mapped_column(
        ForeignKey("intent.id", ondelete="CASCADE"), index=True
    )
    lingarr_request_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))  # cancel|retry|resume|remove
    actor: Mapped[str] = mapped_column(String(64))  # user:<username>
    status: Mapped[str] = mapped_column(String(16))  # ok | failed
    detail: Mapped[str | None] = mapped_column(Text)
