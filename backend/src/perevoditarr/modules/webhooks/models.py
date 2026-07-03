"""Webhook ingestion ORM model (P5-T3, FR-X4). No `from __future__ import`.

A `webhook_source` is a per-instance inbound endpoint that Bazarr/Sonarr POST
to as a discovery/sync trigger. The secret lives only as a SHA-256 hash — the
raw token is shown once at creation (like an API key, FR-A5).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from perevoditarr.core.db import UUIDAuditBase


class WebhookSource(UUIDAuditBase):
    __tablename__: str | None = "webhook_source"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    bazarr_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("bazarr_instance.id", ondelete="CASCADE"), index=True
    )
    # bazarr | sonarr — which notifier posts here (informational).
    kind: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(32))
