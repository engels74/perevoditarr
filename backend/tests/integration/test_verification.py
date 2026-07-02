"""Verification & failure handling end-to-end (P3-T3): convergence from durable
evidence, the Lingarr failure fast-path with breaker feed, environmental parking
(needs-attention), quarantine at the attempt ceiling, and retry promotion after
backoff. Driven against the in-process simulators."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.rails.models import RailState
from perevoditarr.modules.rails.service import RailsService
from tests.conftest import TEST_SECRET
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.bazarr import SimSubtitle
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


def _gateway(scenario: Scenario) -> SimulatorGateway:
    return SimulatorGateway(scenario)


def _verification(session: AsyncSession, scenario: Scenario) -> VerificationService:
    return VerificationService(
        session,
        SECRET,
        _gateway(scenario),
        SseBus(),
        max_attempts=4,
        retry_base_seconds=300,
        retry_cap_seconds=21600,
    )


async def _dispatch_one(
    session: AsyncSession, scenario: Scenario, instance: BazarrInstance
) -> Intent:
    series = scenario.seed_series(title="Alpha Show", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    intent = Intent(
        bazarr_instance_id=instance.id,
        media_type="episode",
        external_media_id=episode_id,
        sonarr_series_id=series.sonarr_series_id,
        season=1,
        episode_number=1,
        display_title="Alpha Show",
        source_language="en",
        target_language="da",
        state="eligible",
    )
    session.add(intent)
    await session.flush()
    rails = RailsService(session, SECRET, _gateway(scenario), SseBus())
    _ = await rails.set_activation(instance.id, active=True)
    dispatcher = DispatcherService(
        session,
        SECRET,
        _gateway(scenario),
        SseBus(),
        lease_seconds=2700,
        backpressure_pending=10,
    )
    summary = await dispatcher.run_for_instance(instance)
    assert summary.dispatched == 1
    return await _reload(session, intent.id)


async def _reload(session: AsyncSession, intent_id: UUID) -> Intent:
    return (await session.scalars(select(Intent).where(Intent.id == intent_id))).one()


def _real_history_row(scenario: Scenario, episode_id: int) -> dict[str, object]:
    series_id = scenario.bazarr.episodes[episode_id].sonarr_series_id
    return {
        "action": 6,
        # Real wall-clock so it postdates the intent's dispatch (the lease-window
        # anchor is the DB `updated_at`, which is real time, not the sim clock).
        "timestamp": datetime.now(UTC).isoformat(),
        "sonarrSeriesId": series_id,
        "sonarrEpisodeId": episode_id,
        "language": {"name": "Danish", "code2": "da", "forced": False, "hi": False},
        "subtitles_path": "/subs/da.srt",
        "description": "translated using Lingarr",
        "upgradable": True,
    }


async def test_converges_from_metadata_plus_history(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_instance(session, scenario)
    intent = await _dispatch_one(session, scenario, instance)
    episode_id = intent.external_media_id
    # The translated subtitle appears + a translation action-6 lands in-window.
    scenario.bazarr.episodes[episode_id].subtitles.append(
        SimSubtitle(code2="da", path="/subs/da.srt")
    )
    scenario.bazarr.episode_history.append(_real_history_row(scenario, episode_id))

    summary = await _verification(session, scenario).run_for_instance(instance)
    assert summary.converged == 1
    assert (await _reload(session, intent.id)).state == "converged"


async def test_present_without_our_translation_supersedes(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_instance(session, scenario)
    intent = await _dispatch_one(session, scenario, instance)
    # Subtitle appears but with no translation history entry — arrived by other
    # means (indexer/manual), so it supersedes rather than converges (FR-V3).
    scenario.bazarr.episodes[intent.external_media_id].subtitles.append(
        SimSubtitle(code2="da", path="/subs/da.srt")
    )
    summary = await _verification(session, scenario).run_for_instance(instance)
    assert summary.superseded == 1
    assert (await _reload(session, intent.id)).state == "superseded"


async def test_provider_failure_retries_and_feeds_breaker(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_instance(session, scenario)
    intent = await _dispatch_one(session, scenario, instance)
    _ = scenario.lingarr.add_request(
        media_id=None,
        title="Alpha Show",
        source_language="en",
        target_language="da",
        media_type="Episode",
        status="Failed",
    )
    summary = await _verification(session, scenario).run_for_instance(instance)
    assert summary.retry_scheduled == 1
    assert (await _reload(session, intent.id)).state == "retry_eligible"
    rail = (
        await session.scalars(
            select(RailState).where(RailState.bazarr_instance_id == instance.id)
        )
    ).one()
    assert rail.breaker_consecutive_failures == 1


async def test_environmental_failure_parks_needs_attention(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_instance(session, scenario)
    intent = await _dispatch_one(session, scenario, instance)
    request = scenario.lingarr.add_request(
        media_id=None,
        title="Alpha Show",
        source_language="en",
        target_language="da",
        media_type="Episode",
        status="Failed",
    )
    request.error_message = "Source subtitle file not found"
    summary = await _verification(session, scenario).run_for_instance(instance)
    assert summary.needs_attention == 1
    # Parked as `failed` (needs-attention), NOT retry_eligible — no retry burn.
    assert (await _reload(session, intent.id)).state == "failed"
    rail = (
        await session.scalars(
            select(RailState).where(RailState.bazarr_instance_id == instance.id)
        )
    ).first()
    # Environmental failures never feed the breaker.
    assert rail is None or rail.breaker_consecutive_failures == 0


async def test_quarantines_at_attempt_ceiling(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_instance(session, scenario)
    series = scenario.seed_series(title="Alpha", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    intent = Intent(
        bazarr_instance_id=instance.id,
        media_type="episode",
        external_media_id=episode_id,
        sonarr_series_id=series.sonarr_series_id,
        season=1,
        episode_number=1,
        display_title="Alpha",
        source_language="en",
        target_language="da",
        state="dispatched",
        lease_expires_at=datetime.now(UTC) - timedelta(hours=1),  # expired
    )
    session.add(intent)
    await session.flush()
    for _ in range(4):  # attempts at the ceiling
        session.add(
            IntentEvent(
                intent_id=intent.id,
                actor="dispatcher",
                from_state="eligible",
                to_state="dispatched",
                reason="dispatched",
            )
        )
    await session.flush()

    summary = await _verification(session, scenario).run_for_instance(instance)
    assert summary.quarantined == 1
    assert (await _reload(session, intent.id)).state == "quarantined"


async def test_retry_promotion_after_backoff(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_instance(session, scenario)
    series = scenario.seed_series(title="Alpha", episode_count=1)
    episode_id = max(scenario.bazarr.episodes)
    intent = Intent(
        bazarr_instance_id=instance.id,
        media_type="episode",
        external_media_id=episode_id,
        sonarr_series_id=series.sonarr_series_id,
        season=1,
        episode_number=1,
        display_title="Alpha",
        source_language="en",
        target_language="da",
        state="retry_eligible",
    )
    session.add(intent)
    await session.flush()
    # A pass well after the backoff window promotes it back to eligible.
    later = datetime.now(UTC) + timedelta(hours=2)
    summary = await _verification(session, scenario).run_for_instance(
        instance, now=later
    )
    assert summary.retries_promoted == 1
    assert (await _reload(session, intent.id)).state == "eligible"
