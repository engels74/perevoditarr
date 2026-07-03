"""Prometheus metrics endpoint (P4-T3, NFR-6): collector output + HTTP surface."""

from collections.abc import AsyncIterator

import pytest
from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.db import metadata
from perevoditarr.core.metrics import collect_metrics
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.rails.models import RailState
from perevoditarr.modules.telemetry import TelemetryHealthRegistry
from tests.conftest import TEST_SECRET, complete_setup

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


async def test_collect_metrics_reports_intents_and_rails(
    session: AsyncSession,
) -> None:
    instance = BazarrInstance(
        name="main",
        url="http://bazarr.test",
        api_key_encrypted=SECRET.encrypt_text("k"),
    )
    session.add(instance)
    await session.flush()
    intent = Intent(
        bazarr_instance_id=instance.id,
        media_type="episode",
        external_media_id=1,
        sonarr_series_id=1,
        display_title="Show",
        source_language="en",
        target_language="da",
        state="dispatched",
    )
    session.add(intent)
    await session.flush()
    session.add(
        IntentEvent(
            intent_id=intent.id,
            actor="dispatcher",
            from_state="eligible",
            to_state="dispatched",
            reason="dispatched",
        )
    )
    session.add(RailState(bazarr_instance_id=None))  # global row
    session.add(RailState(bazarr_instance_id=instance.id, breaker_state="open"))
    await session.commit()

    text = await collect_metrics(session, TelemetryHealthRegistry())
    assert 'perevoditarr_intents{state="dispatched"} 1' in text
    assert "perevoditarr_dispatches_total 1" in text
    assert 'perevoditarr_dispatches_recent{window="hour"} 1' in text
    assert 'perevoditarr_rail_paused{scope="global"} 0' in text
    # An open breaker on the instance surfaces as state code 2.
    assert 'perevoditarr_rail_breaker_state{scope="instance",instance="main"} 2' in text


def test_metrics_endpoint_is_served_unauthenticated(
    client: TestClient[Litestar],
) -> None:
    complete_setup(client)
    # /metrics is at the root, excluded from auth (like /health).
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "perevoditarr_intents" in response.text
