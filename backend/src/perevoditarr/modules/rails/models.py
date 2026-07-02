"""Rails ORM model (P3-T1). No `from __future__ import annotations` here.

`rail_state` persists the *stateful* rail posture that cannot be re-derived
from evidence: the operator pause flag, the per-pair circuit-breaker state, and
per-scope scheduling windows. Volume-cap and budget usage are deliberately NOT
stored here — they are counted from the intent dispatch audit trail on demand
(restart-safe by construction, FR-R4), so a crash can never desync a counter.

A row with `bazarr_instance_id IS NULL` is the single global row (pause only);
per-instance rows carry the breaker for that Bazarr↔Lingarr pair (a Bazarr
instance links exactly one Lingarr, so per-instance is the pair). Single-global
uniqueness is service-enforced (get-or-create), matching the codebase's
portable-uniqueness posture (no partial indexes, NFR-2).
"""

from datetime import datetime
from uuid import UUID

from advanced_alchemy.types import JsonB
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from perevoditarr.core.db import UUIDAuditBase


class RailState(UUIDAuditBase):
    __tablename__: str | None = "rail_state"

    # NULL = the global scope (pause flag only); non-NULL = per-instance.
    bazarr_instance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), unique=True
    )
    paused: Mapped[bool] = mapped_column(default=False)
    paused_reason: Mapped[str | None] = mapped_column(Text)
    # Safe-by-default activation (P3-T7): dispatch only fires for an instance
    # after an explicit Observe -> Active transition. Unused on the global row.
    dispatch_active: Mapped[bool] = mapped_column(default=False)
    # Per-instance override of the preset's default dispatch window K (§7.2).
    window_k: Mapped[int | None] = mapped_column(Integer)
    # Breaker per (Bazarr instance, Lingarr) pair — §7.4 provider/systemic class.
    breaker_state: Mapped[str] = mapped_column(
        String(16), default="closed"
    )  # closed | open | half_open
    breaker_consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    breaker_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    breaker_last_probe_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # msgspec-encoded windows.SchedulingWindow list, decoded at the boundary.
    scheduling_windows: Mapped[list[dict[str, object]] | None] = mapped_column(JsonB)
