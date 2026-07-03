"""Auth ORM models (P1-T2). No `from __future__ import annotations` here."""

from datetime import datetime
from uuid import UUID

from advanced_alchemy.base import DefaultBase
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from perevoditarr.core.db import UUIDAuditBase


class User(UUIDAuditBase):
    __tablename__: str | None = "user_account"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    # None for externally-authenticated users (OIDC / forward-auth).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    # admin (full) | viewer (read-only observer), FR-A6 / ADR-0008. Kept as a
    # string for a clean generalization path if finer roles ever land.
    role: Mapped[str] = mapped_column(String(16), default="admin")
    is_active: Mapped[bool] = mapped_column(default=True)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="user", lazy="raise", cascade="all, delete-orphan"
    )


class ApiKey(UUIDAuditBase):
    __tablename__: str | None = "api_key"

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
    __tablename__: str | None = "auth_provider_config"

    provider_type: Mapped[str] = mapped_column(String(32), unique=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    # Full provider settings struct, Fernet-encrypted (client secrets live here).
    settings_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)


class AppSetupState(DefaultBase):
    """Single fixed row (id=1) recording first-run completion as a durable fact.

    `completed` is derived as `completed_at IS NOT NULL`. The row is never
    autoseeded — its absence means setup is not complete. The named CHECK plus
    the id=1-targeted upsert keep this a true singleton on SQLite and Postgres.
    """

    __tablename__: str | None = "app_setup_state"
    __table_args__: tuple[CheckConstraint, ...] = (
        CheckConstraint("id = 1", name="singleton"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
