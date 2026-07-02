"""Sustained-dispatch load test (P3-T6): drain a large backlog across many
rounds and assert the bounded window and §6.5 invariant hold, the corruption
trap is never tripped, and everything converges. Exercises the orchestrator
under scale without asserting wall-clock budgets (NFR-4 UI budgets are covered
by the P1-T5 browse-budget perf harness)."""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.db import metadata
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.dispatch.dispatcher import DispatcherService
from perevoditarr.modules.dispatch.verification import VerificationService
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.intents.models import Intent
from perevoditarr.modules.rails.service import RailsService
from tests.conftest import TEST_SECRET
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.scenario import Scenario

SECRET = SecretBox(TEST_SECRET)
SERIES_COUNT = 30
WINDOW_K = 4


@pytest.fixture
async def scenario() -> AsyncIterator[Scenario]:
    s = Scenario()
    yield s
    await s.aclose()


@pytest.fixture
async def session(app_settings: AppSettings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


async def _count(session: AsyncSession, instance_id: object, state: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Intent)
            .where(Intent.bazarr_instance_id == instance_id, Intent.state == state)
        )
    ).scalar_one()


async def test_sustained_dispatch_drains_backlog_without_corruption(
    session: AsyncSession, scenario: Scenario
) -> None:
    scenario.advance_time(timedelta(days=3650))  # future-date sim history
    lingarr = LingarrInstance(
        name="ling",
        url="http://lingarr.test",
        api_key_encrypted=SECRET.encrypt_text(scenario.lingarr.api_key),
    )
    session.add(lingarr)
    await session.flush()
    instance = BazarrInstance(
        name="main",
        url="http://bazarr.test",
        api_key_encrypted=SECRET.encrypt_text(scenario.bazarr.api_key),
        lingarr_instance_id=lingarr.id,
    )
    session.add(instance)
    await session.flush()

    for _ in range(SERIES_COUNT):
        series = scenario.seed_series(episode_count=1)
        episode_id = max(scenario.bazarr.episodes)
        session.add(
            Intent(
                bazarr_instance_id=instance.id,
                media_type="episode",
                external_media_id=episode_id,
                sonarr_series_id=series.sonarr_series_id,
                season=1,
                episode_number=1,
                display_title=series.title,
                source_language="en",
                target_language="da",
                state="eligible",
            )
        )
    await session.flush()

    rails = RailsService(session, SECRET, SimulatorGateway(scenario), SseBus())
    _ = await rails.set_activation(instance.id, active=True)
    _ = await rails.set_window_k(instance.id, WINDOW_K)

    def _dispatcher() -> DispatcherService:
        return DispatcherService(
            session,
            SECRET,
            SimulatorGateway(scenario),
            SseBus(),
            lease_seconds=2700,
            backpressure_pending=10_000,  # keep the queue open for the drain
        )

    def _verification() -> VerificationService:
        return VerificationService(
            session,
            SECRET,
            SimulatorGateway(scenario),
            SseBus(),
            max_attempts=4,
            retry_base_seconds=300,
            retry_cap_seconds=21600,
        )

    max_rounds = SERIES_COUNT  # generous ceiling; K=4 drains in ~8
    for _ in range(max_rounds):
        summary = await _dispatcher().run_for_instance(instance)
        # Bounded window (§7.2): never more than the effective K per pass, and
        # headroom keeps it under concurrent_jobs (sim default 4 → K capped 3).
        assert summary.dispatched <= WINDOW_K
        assert len(scenario.bazarr.jobs_pending) <= WINDOW_K
        _ = await scenario.process_jobs()
        assert scenario.bazarr.corrupted_items == []  # §6.4 never tripped
        _ = await _verification().run_for_instance(instance)
        if await _count(session, instance.id, "converged") == SERIES_COUNT:
            break

    assert await _count(session, instance.id, "converged") == SERIES_COUNT
    assert await _count(session, instance.id, "eligible") == 0
    assert scenario.bazarr.corrupted_items == []
