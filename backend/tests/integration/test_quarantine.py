"""Quarantine store + APIs (P3-T3, FR-R6): listing, and the retry/release/
exclude manual actions with their transition guardrails."""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.db import metadata
from perevoditarr.core.errors import ConflictError
from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.instances import InstanceGateway
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.models import Intent
from perevoditarr.modules.intents.quarantine import QuarantineService
from perevoditarr.modules.policy.service import PolicyService
from tests.conftest import TEST_SECRET

SECRET = SecretBox(TEST_SECRET)


@pytest.fixture
async def session(app_settings: AppSettings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


def _service(session: AsyncSession) -> QuarantineService:
    return QuarantineService(session, SECRET, InstanceGateway(HttpClientRegistry()))


async def _instance(session: AsyncSession) -> BazarrInstance:
    instance = BazarrInstance(
        name="main",
        url="http://bazarr.test",
        api_key_encrypted=SECRET.encrypt_text("k"),
    )
    session.add(instance)
    await session.flush()
    return instance


async def _intent(
    session: AsyncSession, instance_id: UUID, *, state: str, series_id: int = 1
) -> Intent:
    intent = Intent(
        bazarr_instance_id=instance_id,
        media_type="episode",
        external_media_id=series_id * 10,
        sonarr_series_id=series_id,
        season=1,
        episode_number=1,
        display_title="Alpha",
        source_language="en",
        target_language="da",
        state=state,
    )
    session.add(intent)
    await session.flush()
    return intent


async def test_lists_separate_quarantine_and_needs_attention(
    session: AsyncSession,
) -> None:
    instance = await _instance(session)
    _ = await _intent(session, instance.id, state="quarantined", series_id=1)
    _ = await _intent(session, instance.id, state="failed", series_id=2)
    service = _service(session)

    quarantined = await service.list_quarantined(
        bazarr_instance_id=None, limit=50, offset=0
    )
    needs_attention = await service.list_needs_attention(
        bazarr_instance_id=None, limit=50, offset=0
    )
    assert quarantined.total == 1
    assert quarantined.items[0].state == "quarantined"
    assert needs_attention.total == 1
    assert needs_attention.items[0].state == "failed"


async def test_retry_reeligibilizes(session: AsyncSession) -> None:
    instance = await _instance(session)
    intent = await _intent(session, instance.id, state="quarantined")
    result = await _service(session).retry(intent.id)
    assert result.state == "eligible"


async def test_retry_reeligibilizes_needs_attention(session: AsyncSession) -> None:
    # Needs-attention items are `failed` (environmental failure parked without
    # retry burn); the same manual retry re-eligibilizes them, mirroring the
    # quarantine retry, once the operator has cleared the cause (FR-R6).
    instance = await _instance(session)
    intent = await _intent(session, instance.id, state="failed")
    result = await _service(session).retry(intent.id)
    assert result.state == "eligible"


async def test_release_closes_intent(session: AsyncSession) -> None:
    instance = await _instance(session)
    intent = await _intent(session, instance.id, state="quarantined")
    result = await _service(session).release(intent.id)
    assert result.state == "superseded"


async def test_exclude_closes_intent_and_adds_exclusion(
    session: AsyncSession,
) -> None:
    instance = await _instance(session)
    intent = await _intent(session, instance.id, state="quarantined", series_id=7)
    result = await _service(session).exclude(intent.id)
    assert result.state == "superseded"

    policy = PolicyService(session, SECRET, InstanceGateway(HttpClientRegistry()))
    exclusions = await policy.list_exclusions(bazarr_instance_id=instance.id)
    assert any(e.kind == "series" and e.rule_key == "7" for e in exclusions)


async def test_retry_on_non_retryable_state_is_conflict(session: AsyncSession) -> None:
    # Only quarantined and needs-attention (failed) intents are retryable; a
    # dispatched (in-flight) intent is not a manual-transition source.
    instance = await _instance(session)
    intent = await _intent(session, instance.id, state="dispatched")
    with pytest.raises(ConflictError):
        _ = await _service(session).retry(intent.id)
