"""Doctor ORM models (P1-T6). No `from __future__ import annotations`."""

from datetime import datetime
from uuid import UUID

from advanced_alchemy.types import JsonB
from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from perevoditarr.core.db import UUIDv7AuditBase


class DoctorRun(UUIDv7AuditBase):
    __tablename__ = "doctor_run"

    trigger: Mapped[str] = mapped_column(String(16))  # manual | scheduled | contextual
    status: Mapped[str] = mapped_column(String(16))  # running | completed | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # counts per severity, e.g. {"info": 3, "warn": 1, "critical": 0}
    summary: Mapped[dict[str, int] | None] = mapped_column(JsonB)

    findings: Mapped[list[DoctorFinding]] = relationship(
        back_populates="run", lazy="raise", cascade="all, delete-orphan"
    )


class DoctorFinding(UUIDv7AuditBase):
    __tablename__ = "doctor_finding"
    __table_args__ = (Index("ix_doctor_finding_check", "check_id"),)

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("doctor_run.id", ondelete="CASCADE"), index=True
    )
    check_id: Mapped[str] = mapped_column(String(32))  # e.g. "FR-DR2"
    severity: Mapped[str] = mapped_column(String(16))  # info | warn | critical
    bazarr_instance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    lingarr_instance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lingarr_instance.id", ondelete="CASCADE")
    )
    message: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    fix_guidance: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, object] | None] = mapped_column(JsonB)

    run: Mapped[DoctorRun] = relationship(back_populates="findings", lazy="raise")
