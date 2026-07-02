"""Corruption-trap unreachability + crash-safety suites (P3-T3; PRD success
metrics 1 and 5).

The §6.4 empty-array corruption path must be unreachable for Perevoditarr
traffic: the §6.5 invariant keeps at most one dispatch per (instance, series,
pair) in flight, and the pre-dispatch guard blocks on any matching active
Lingarr request. Crash safety is re-observation: after a simulated restart
(fresh in-memory services over the surviving ledger), verification retroactively
converges in-flight intents and the dispatcher never double-dispatches.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
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


def _dispatcher(session: AsyncSession, scenario: Scenario) -> DispatcherService:
    return DispatcherService(
        session,
        SECRET,
        SimulatorGateway(scenario),
        SseBus(),
        lease_seconds=2700,
        backpressure_pending=10,
    )


def _verification(session: AsyncSession, scenario: Scenario) -> VerificationService:
    return VerificationService(
        session,
        SECRET,
        SimulatorGateway(scenario),
        SseBus(),
        max_attempts=4,
        retry_base_seconds=300,
        retry_cap_seconds=21600,
    )


async def _seed_instance(session: AsyncSession, scenario: Scenario) -> BazarrInstance:
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
    return instance


async def _eligible(
    session: AsyncSession,
    instance_id: UUID,
    *,
    series_id: int,
    episode_id: int,
    title: str,
) -> Intent:
    intent = Intent(
        bazarr_instance_id=instance_id,
        media_type="episode",
        external_media_id=episode_id,
        sonarr_series_id=series_id,
        season=1,
        episode_number=1,
        display_title=title,
        source_language="en",
        target_language="da",
        state="eligible",
    )
    session.add(intent)
    await session.flush()
    return intent


async def _activate(
    session: AsyncSession, scenario: Scenario, instance_id: UUID
) -> None:
    rails = RailsService(session, SECRET, SimulatorGateway(scenario), SseBus())
    _ = await rails.set_activation(instance_id, active=True)


async def _states(session: AsyncSession, instance_id: UUID) -> list[str]:
    rows = (
        await session.scalars(
            select(Intent).where(Intent.bazarr_instance_id == instance_id)
        )
    ).all()
    return sorted(row.state for row in rows)


# ---------------------------------------------------------- corruption trap


async def test_invariant_limits_lingarr_requests_per_pair(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha Show", episode_count=2)
    ids = sorted(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    for episode_id in ids:
        _ = await _eligible(
            session,
            instance.id,
            series_id=series.sonarr_series_id,
            episode_id=episode_id,
            title="Alpha Show",
        )
    await _activate(session, scenario, instance.id)

    summary = await _dispatcher(session, scenario).run_for_instance(instance)
    assert summary.dispatched == 1
    assert summary.held_invariant == 1
    # Only one job reaches Bazarr → only one Lingarr request → no dedup collision.
    _ = await scenario.process_jobs()
    assert scenario.bazarr.corrupted_items == []
    active = [r for r in scenario.lingarr.requests.values() if r.title == "Alpha Show"]
    assert len(active) == 1


async def test_active_external_request_blocks_and_never_corrupts(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha Show", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    # An external actor is already translating this show+pair.
    _ = scenario.lingarr.add_request(
        media_id=None,
        title="Alpha Show",
        source_language="en",
        target_language="da",
        media_type="Episode",
        status="InProgress",
    )
    instance = await _seed_instance(session, scenario)
    _ = await _eligible(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_id,
        title="Alpha Show",
    )
    await _activate(session, scenario, instance.id)

    summary = await _dispatcher(session, scenario).run_for_instance(instance)
    assert summary.dispatched == 0
    assert summary.guard_active_lingarr == 1
    _ = await scenario.process_jobs()
    assert scenario.bazarr.corrupted_items == []


async def test_full_two_round_cycle_never_corrupts(
    session: AsyncSession, scenario: Scenario
) -> None:
    # Push the sim clock past real wall-clock so the sim's action-6 history
    # postdates each intent's dispatch time (the lease-window anchor).
    scenario.advance_time(timedelta(days=3650))
    series = scenario.seed_series(title="Alpha Show", episode_count=2)
    ids = sorted(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    for episode_id in ids:
        _ = await _eligible(
            session,
            instance.id,
            series_id=series.sonarr_series_id,
            episode_id=episode_id,
            title="Alpha Show",
        )
    await _activate(session, scenario, instance.id)

    # Round 1: dispatch one, translate it for real, converge it.
    _ = await _dispatcher(session, scenario).run_for_instance(instance)
    _ = await scenario.process_jobs()
    assert scenario.bazarr.corrupted_items == []
    _ = await _verification(session, scenario).run_for_instance(instance)

    # Round 2: the freed pair lets the second episode dispatch; the first
    # request is Completed (not active) so no dedup collision.
    _ = await _dispatcher(session, scenario).run_for_instance(instance)
    _ = await scenario.process_jobs()
    assert scenario.bazarr.corrupted_items == []
    _ = await _verification(session, scenario).run_for_instance(instance)

    assert await _states(session, instance.id) == ["converged", "converged"]
    # Both episodes carry a real translated Danish subtitle.
    for episode_id in ids:
        codes = [s.code2 for s in scenario.bazarr.episodes[episode_id].subtitles]
        assert "da" in codes


# ---------------------------------------------------------- crash safety


async def test_restart_storm_never_double_dispatches(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha Show", episode_count=2)
    ids = sorted(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    for episode_id in ids:
        _ = await _eligible(
            session,
            instance.id,
            series_id=series.sonarr_series_id,
            episode_id=episode_id,
            title="Alpha Show",
        )
    await _activate(session, scenario, instance.id)

    _ = await _dispatcher(session, scenario).run_for_instance(instance)
    assert len(scenario.bazarr.jobs_pending) == 1

    # Restart storm: fresh in-memory services over the surviving ledger, several
    # times. The in-flight intent stays dispatched; nothing new fires.
    for _ in range(3):
        summary = await _dispatcher(session, scenario).run_for_instance(instance)
        assert summary.dispatched == 0
    assert len(scenario.bazarr.jobs_pending) == 1  # no duplicate translate PATCH


async def test_retroactive_convergence_after_restart(
    session: AsyncSession, scenario: Scenario
) -> None:
    scenario.advance_time(timedelta(days=3650))
    series = scenario.seed_series(title="Alpha Show", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    _ = await _eligible(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_id,
        title="Alpha Show",
    )
    await _activate(session, scenario, instance.id)

    _ = await _dispatcher(session, scenario).run_for_instance(instance)
    # The translation completes while Perevoditarr is "down".
    _ = await scenario.process_jobs()
    assert scenario.bazarr.corrupted_items == []

    # Restart: a fresh verification service re-observes and converges.
    summary = await _verification(session, scenario).run_for_instance(instance)
    assert summary.converged == 1
    assert await _states(session, instance.id) == ["converged"]
    # And the dispatcher does not re-dispatch a converged intent.
    redispatch = await _dispatcher(session, scenario).run_for_instance(instance)
    assert redispatch.dispatched == 0
