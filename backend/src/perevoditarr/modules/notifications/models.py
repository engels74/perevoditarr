"""Notifications ORM model (P3-T5). No `from __future__ import annotations`.

An Apprise target URL (which carries credentials/tokens) is Fernet-encrypted at
rest (FR-A5) and never returned in plaintext after write. `events` is the JSON
list of routing-matrix keys this route subscribes to.
"""

from advanced_alchemy.types import JsonB
from sqlalchemy import LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from perevoditarr.core.db import UUIDAuditBase


class NotificationRoute(UUIDAuditBase):
    __tablename__: str | None = "notification_route"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    # Apprise URL, encrypted at rest — never logged, never returned in plaintext.
    url_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(default=True)
    # Subscribed routing-matrix event keys (events.NotificationEvent values).
    events: Mapped[list[str] | None] = mapped_column(JsonB)
