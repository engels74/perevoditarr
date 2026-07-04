"""Alembic async environment (P1-T1).

The URL comes from PEREVODITARR_DATABASE_URL (via app settings), so the same
migration history runs against Postgres and SQLite (NFR-2).
"""

import asyncio
from logging.config import fileConfig

from advanced_alchemy.types.guid import GUID
from alembic import context
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Numeric, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.sql.schema import Column
from sqlalchemy.types import TypeEngine

# Every model module must be registered on the shared metadata before
# autogenerate runs; perevoditarr.models imports them all.
from perevoditarr import models as _models  # noqa: F401
from perevoditarr.core.db import metadata
from perevoditarr.core.settings import load_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

config.set_main_option("sqlalchemy.url", load_settings().database_url)


def _compare_type(
    migration_context: MigrationContext,
    inspected_column: Column[object],
    metadata_column: Column[object],
    inspected_type: TypeEngine[object],
    metadata_type: TypeEngine[object],
) -> bool | None:
    """Suppress SQLite reflection noise for Advanced Alchemy GUID columns."""
    del inspected_column, metadata_column
    if (
        migration_context.dialect.name == "sqlite"
        and isinstance(metadata_type, GUID)
        and isinstance(inspected_type, Numeric)
        and inspected_type.precision == 16
    ):
        return False
    return None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER in place — batch mode keeps migrations portable (NFR-2).
        render_as_batch=url is not None and url.startswith("sqlite"),
        compare_type=_compare_type,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=_compare_type,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
