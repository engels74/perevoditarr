"""Persistence foundations (P1-T1).

Model modules import their declarative base from here and must NOT use
`from __future__ import annotations` (Mapped[...] is introspected at class
creation). Advanced Alchemy's bases already apply the naming conventions on
MetaData and mix in AsyncAttrs.

Base selection (ADR-0005): UUIDAuditBase is the default; append-heavy tables
(mirror rows, intent_event) use UUIDv7AuditBase so time-ordered primary keys
keep b-tree inserts append-only at 100k+ scale.

Relationship guard: every relationship() must declare an explicit loading
strategy, with lazy="raise" as the default guard — enforced by a unit test
that walks all mappers.
"""

from advanced_alchemy.base import UUIDAuditBase, UUIDv7AuditBase, orm_registry
from advanced_alchemy.extensions.litestar import (
    AsyncSessionConfig,
    SQLAlchemyAsyncConfig,
    SQLAlchemyPlugin,
)
from sqlalchemy import MetaData

from perevoditarr.core.settings import AppSettings

__all__ = [
    "UUIDAuditBase",
    "UUIDv7AuditBase",
    "build_alchemy_config",
    "build_sqlalchemy_plugin",
    "metadata",
]

metadata: MetaData = orm_registry.metadata


def build_alchemy_config(settings: AppSettings) -> SQLAlchemyAsyncConfig:
    return SQLAlchemyAsyncConfig(
        connection_string=settings.database_url,
        session_config=AsyncSessionConfig(expire_on_commit=False),
        # Schema is Alembic's job — never create_all in production.
        create_all=False,
    )


def build_sqlalchemy_plugin(config: SQLAlchemyAsyncConfig) -> SQLAlchemyPlugin:
    return SQLAlchemyPlugin(config=config)
