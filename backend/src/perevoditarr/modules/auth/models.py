"""Auth ORM models (P1-T2). No `from __future__ import annotations` here."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from perevoditarr.core.db import UUIDAuditBase


class User(UUIDAuditBase):
    __tablename__ = "user_account"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    # None for externally-authenticated users (OIDC / forward-auth).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    is_admin: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="user", lazy="raise", cascade="all, delete-orphan"
    )


class ApiKey(UUIDAuditBase):
    __tablename__ = "api_key"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    # First characters of the raw key, for identification in the UI; the raw
    # key itself is never stored (FR-A5).
    prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="api_keys", lazy="raise")


class AuthProviderConfig(UUIDAuditBase):
    __tablename__ = "auth_provider_config"

    provider_type: Mapped[str] = mapped_column(String(32), unique=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    # Full provider settings struct, Fernet-encrypted (client secrets live here).
    settings_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
