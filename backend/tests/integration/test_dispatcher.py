"""Dispatcher end-to-end (P3-T2): bounded window, the non-configurable §6.5
scheduling invariant, the FR-Q2 pre-dispatch guard (supersede on appeared
target, hold on active Lingarr request — the §6.4 trap guard), rail blocks,
backpressure, and the safe-by-default activation gate. Driven against the
in-process Bazarr/Lingarr simulators."""

from collections.abc import AsyncIterator
from typing import override
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
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.intents.models import Intent
from perevoditarr.modules.rails.service import RailsService
from tests.conftest import TEST_SECRET
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.bazarr import SimJob, SimSubtitle
from tests.simulators.scenario import Scenario

SECRET = SecretBox(TEST_SECRET)


class RecordingBus(SseBus):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, object]] = []

    @override
    def publish(self, topic: str, data: object) -> None:
        self.events.append((topic, data))
        super().publish(topic, data)


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


async def _eligible_episode(
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


def _dispatcher(
    session: AsyncSession, scenario: Scenario
) -> tuple[DispatcherService, RecordingBus]:
    bus = RecordingBus()
    service = DispatcherService(
        session,
        SECRET,
        SimulatorGateway(scenario),
        bus,
        lease_seconds=2700,
        backpressure_pending=10,
    )
    return service, bus


async def _activate(
    session: AsyncSession, scenario: Scenario, instance_id: UUID
) -> None:
    rails = RailsService(session, SECRET, SimulatorGateway(scenario), SseBus())
    _ = await rails.set_activation(instance_id, active=True)


async def _reload(session: AsyncSession, intent_id: UUID) -> Intent:
    return (await session.scalars(select(Intent).where(Intent.id == intent_id))).one()


async def test_scheduling_invariant_holds_one_per_series_pair(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha Show", episode_count=2)
    episode_ids = sorted(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    first = await _eligible_episode(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_ids[0],
        title="Alpha Show",
    )
    _ = await _eligible_episode(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_ids[1],
        title="Alpha Show",
    )
    await _activate(session, scenario, instance.id)
    service, bus = _dispatcher(session, scenario)

    summary = await service.run_for_instance(instance)

    # §6.5: two episodes of one show on the same pair are indistinguishable in
    # Lingarr — exactly one may be in flight.
    assert summary.dispatched == 1
    assert summary.held_invariant == 1
    assert len(scenario.bazarr.jobs_pending) == 1
    assert any(topic == "intents.dispatched" for topic, _ in bus.events)
    dispatched = await _reload(session, first.id)
    assert dispatched.state == "dispatched"
    assert dispatched.lease_expires_at is not None


async def test_distinct_series_both_dispatch_within_window(
    session: AsyncSession, scenario: Scenario
) -> None:
    series_a = scenario.seed_series(title="Alpha", episode_count=1)
    series_b = scenario.seed_series(title="Beta", episode_count=1)
    ids = sorted(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    _ = await _eligible_episode(
        session,
        instance.id,
        series_id=series_a.sonarr_series_id,
        episode_id=ids[0],
        title="Alpha",
    )
    _ = await _eligible_episode(
        session,
        instance.id,
        series_id=series_b.sonarr_series_id,
        episode_id=ids[1],
        title="Beta",
    )
    await _activate(session, scenario, instance.id)
    service, _ = _dispatcher(session, scenario)

    summary = await service.run_for_instance(instance)
    assert summary.dispatched == 2  # window K=2, different series


async def test_window_k_override_caps_dispatch(
    session: AsyncSession, scenario: Scenario
) -> None:
    series_a = scenario.seed_series(title="Alpha", episode_count=1)
    series_b = scenario.seed_series(title="Beta", episode_count=1)
    ids = sorted(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    _ = await _eligible_episode(
        session,
        instance.id,
        series_id=series_a.sonarr_series_id,
        episode_id=ids[0],
        title="Alpha",
    )
    _ = await _eligible_episode(
        session,
        instance.id,
        series_id=series_b.sonarr_series_id,
        episode_id=ids[1],
        title="Beta",
    )
    rails = RailsService(session, SECRET, SimulatorGateway(scenario), SseBus())
    _ = await rails.set_activation(instance.id, active=True)
    _ = await rails.set_window_k(instance.id, 1)
    service, _ = _dispatcher(session, scenario)

    summary = await service.run_for_instance(instance)
    assert summary.dispatched == 1


async def test_guard_supersedes_when_target_already_present(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    # Target appeared by other means between discovery and dispatch.
    scenario.bazarr.episodes[episode_id].subtitles.append(
        SimSubtitle(code2="da", path="/subs/alpha.da.srt")
    )
    instance = await _seed_instance(session, scenario)
    intent = await _eligible_episode(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_id,
        title="Alpha",
    )
    await _activate(session, scenario, instance.id)
    service, _ = _dispatcher(session, scenario)

    summary = await service.run_for_instance(instance)
    assert summary.dispatched == 0
    assert summary.guard_superseded == 1
    assert len(scenario.bazarr.jobs_pending) == 0
    assert (await _reload(session, intent.id)).state == "superseded"


async def test_guard_holds_on_active_lingarr_request(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha Show", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    # An external actor already has an active Lingarr request at §6.5 identity;
    # dispatching now would trip the §6.4 corruption trap.
    _ = scenario.lingarr.add_request(
        media_id=None,
        title="Alpha Show",
        source_language="en",
        target_language="da",
        media_type="Episode",
        status="InProgress",
    )
    instance = await _seed_instance(session, scenario)
    intent = await _eligible_episode(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_id,
        title="Alpha Show",
    )
    await _activate(session, scenario, instance.id)
    service, _ = _dispatcher(session, scenario)

    summary = await service.run_for_instance(instance)
    assert summary.dispatched == 0
    assert summary.guard_active_lingarr == 1
    assert len(scenario.bazarr.jobs_pending) == 0
    assert (await _reload(session, intent.id)).state == "eligible"


async def test_inactive_instance_dispatches_nothing(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    _ = await _eligible_episode(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_id,
        title="Alpha",
    )
    # Not activated: safe-by-default Observe.
    service, _ = _dispatcher(session, scenario)

    summary = await service.run_for_instance(instance)
    assert summary.inactive is True
    assert summary.dispatched == 0


async def test_paused_instance_holds_on_rails(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    _ = await _eligible_episode(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_id,
        title="Alpha",
    )
    rails = RailsService(session, SECRET, SimulatorGateway(scenario), SseBus())
    _ = await rails.set_activation(instance.id, active=True)
    _ = await rails.pause(instance.id, reason="freeze")
    service, _ = _dispatcher(session, scenario)

    summary = await service.run_for_instance(instance)
    assert summary.dispatched == 0
    assert summary.held_rail == 1


async def test_backpressure_holds_top_up(
    session: AsyncSession, scenario: Scenario
) -> None:
    series = scenario.seed_series(title="Alpha", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    instance = await _seed_instance(session, scenario)
    _ = await _eligible_episode(
        session,
        instance.id,
        series_id=series.sonarr_series_id,
        episode_id=episode_id,
        title="Alpha",
    )
    await _activate(session, scenario, instance.id)
    # Bazarr's pending queue is already deep (§6.2 backpressure).
    for job_id in range(10):
        scenario.bazarr.jobs_pending.append(
            SimJob(job_id=job_id, job_name="sync", status="pending")
        )
    service, _ = _dispatcher(session, scenario)

    summary = await service.run_for_instance(instance)
    assert summary.backpressure_held is True
    assert summary.dispatched == 0
