"""Admin CLI building blocks (P4-T3): user creation logic + CLI arg helpers."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.cli import (
    resolve_password,
    str_arg,
)
from perevoditarr.core.db import metadata
from perevoditarr.core.errors import ConflictError
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.auth.models import AppSetupState, User
from perevoditarr.modules.auth.service import AuthService


@pytest.fixture
async def session(app_settings: AppSettings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


async def test_create_user_persists_admin(session: AsyncSession) -> None:
    service = AuthService(session)
    user = await service.create_user(
        username="ops", password="correct-horse-battery-staple", email=None
    )
    assert user.is_admin is True
    rows = (await session.scalars(select(User))).all()
    assert [row.username for row in rows] == ["ops"]
    assert rows[0].password_hash is not None


async def test_create_user_rejects_duplicate(session: AsyncSession) -> None:
    service = AuthService(session)
    _ = await service.create_user(username="ops", password="a-long-password-here")
    with pytest.raises(ConflictError):
        _ = await service.create_user(username="ops", password="another-long-password")


async def test_mark_setup_completed_is_idempotent_and_timestamp_stable(
    session: AsyncSession,
) -> None:
    # Regression: mark_setup_completed is an atomic id=1 upsert. Calling it
    # twice must not raise (a naive read-then-insert would let a concurrent
    # second INSERT hit the PK unique index -> unhandled IntegrityError/500) and
    # must leave exactly one row whose completed_at keeps the ORIGINAL timestamp.
    service = AuthService(session)
    await service.mark_setup_completed()
    first = (await session.scalars(select(AppSetupState))).all()
    assert len(first) == 1
    original = first[0].completed_at
    assert original is not None

    await service.mark_setup_completed()  # second call is a no-op, never a 500
    session.expire_all()  # force a fresh read from the database
    rows = (await session.scalars(select(AppSetupState))).all()
    assert len(rows) == 1
    assert rows[0].id == 1
    assert rows[0].completed_at == original


def test_resolve_password_prefers_cli_arg() -> None:
    assert resolve_password("supplied") == "supplied"


def test_resolve_password_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PEREVODITARR_ADMIN_PASSWORD", "from-env")
    assert resolve_password(None) == "from-env"


def test_str_arg_narrows_non_strings() -> None:
    assert str_arg("x") == "x"
    assert str_arg(None) is None
    assert str_arg(123) is None
