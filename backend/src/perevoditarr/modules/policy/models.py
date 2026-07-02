"""Policy ORM models (P2-T1). No `from __future__ import annotations` here.

Presets and translation profiles are global objects; assignments, exclusions,
and overrides are instance-scoped (FR-I4). Layered policy values live in a
JSON column decoded to `resolver.PolicyValues` at the service boundary — the
resolver never sees ORM rows, and export/import round-trips stay lossless.
"""

from uuid import UUID

from advanced_alchemy.types import JsonB
from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import SchemaItem

from perevoditarr.core.db import UUIDAuditBase


class Preset(UUIDAuditBase):
    __tablename__: str | None = "preset"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Shipped presets are forkable but not deletable; exactly one preset is
    # active at a time (service-enforced — partial unique indexes aren't
    # dialect-portable, NFR-2).
    built_in: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=False, index=True)
    values: Mapped[dict[str, object] | None] = mapped_column(JsonB)
    # Rail posture (K, caps, budget, breaker) carried as preset data now,
    # consumed by the rails subsystem in Phase 3 (P3-T1).
    rails: Mapped[dict[str, object] | None] = mapped_column(JsonB)


class TranslationProfile(UUIDAuditBase):
    __tablename__: str | None = "translation_profile"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    values: Mapped[dict[str, object] | None] = mapped_column(JsonB)

    assignments: Mapped[list[ProfileAssignment]] = relationship(
        back_populates="profile", lazy="raise", cascade="all, delete-orphan"
    )


class ProfileAssignment(UUIDAuditBase):
    __tablename__: str | None = "profile_assignment"
    __table_args__: tuple[SchemaItem, ...] = (
        # scope_key encodes the scope target: "" for instance scope, the tag
        # for library scope, str(sonarr_series_id)/str(radarr_id) otherwise —
        # portable uniqueness without NULL-in-unique-constraint semantics.
        UniqueConstraint("bazarr_instance_id", "scope_type", "scope_key"),
        Index("ix_profile_assignment_instance", "bazarr_instance_id"),
    )

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("translation_profile.id", ondelete="CASCADE"), index=True
    )
    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE")
    )
    scope_type: Mapped[str] = mapped_column(String(16))  # instance|library|series|movie
    scope_key: Mapped[str] = mapped_column(String(128), default="")

    profile: Mapped[TranslationProfile] = relationship(
        back_populates="assignments", lazy="joined", innerjoin=True
    )


class Exclusion(UUIDAuditBase):
    __tablename__: str | None = "exclusion"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint("bazarr_instance_id", "kind", "rule_key"),
        Index("ix_exclusion_instance_kind", "bazarr_instance_id", "kind"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))  # series|movie|tag|language_pair
    # series/movie: the arr id; tag: the tag; language_pair: "src->tgt".
    rule_key: Mapped[str] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)


class Override(UUIDAuditBase):
    __tablename__: str | None = "override"
    __table_args__: tuple[SchemaItem, ...] = (
        UniqueConstraint("bazarr_instance_id", "media_type", "media_key"),
        Index("ix_override_instance", "bazarr_instance_id"),
    )

    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE")
    )
    media_type: Mapped[str] = mapped_column(String(8))  # series|movie
    media_key: Mapped[str] = mapped_column(String(32))  # arr id as string
    values: Mapped[dict[str, object] | None] = mapped_column(JsonB)
