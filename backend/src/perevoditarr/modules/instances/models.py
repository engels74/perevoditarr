"""Instance ORM models (P1-T4). No `from __future__ import annotations` here.

Credentials are Fernet-encrypted at rest (FR-A5). Capability and health
snapshots are JSON columns holding msgspec-typed payloads decoded at the
service boundary.
"""

from uuid import UUID

from advanced_alchemy.types import JsonB
from sqlalchemy import ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from perevoditarr.core.db import UUIDAuditBase


class LingarrInstance(UUIDAuditBase):
    __tablename__: str | None = "lingarr_instance"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str] = mapped_column(String(512))
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(default=True)
    version: Mapped[str | None] = mapped_column(String(32))
    health_snapshot: Mapped[dict[str, object] | None] = mapped_column(JsonB)

    bazarr_instances: Mapped[list[BazarrInstance]] = relationship(
        back_populates="lingarr", lazy="raise"
    )


class BazarrInstance(UUIDAuditBase):
    __tablename__: str | None = "bazarr_instance"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str] = mapped_column(String(512))
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(default=True)
    version: Mapped[str | None] = mapped_column(String(32))
    # N Bazarr -> 1 Lingarr (PRD FR-I2)
    lingarr_instance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lingarr_instance.id", ondelete="SET NULL")
    )
    # Per-instance capability record (PRD §6.6 / FR-DR10)
    capabilities: Mapped[dict[str, object] | None] = mapped_column(JsonB)
    health_snapshot: Mapped[dict[str, object] | None] = mapped_column(JsonB)

    lingarr: Mapped[LingarrInstance | None] = relationship(
        back_populates="bazarr_instances", lazy="joined"
    )
