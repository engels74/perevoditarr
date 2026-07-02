"""Item timeline + Lingarr pass-through actions (P4-T2, FR-V4/FR-X3).

Timeline stitches the durable planes (intent events + Bazarr action-6 history +
matching Lingarr request records + pass-through audit) into one chronological
stream, degrading gracefully when an upstream is unreachable. Pass-through
actions map 1:1 to Lingarr and are always audit-logged.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.db import metadata
from perevoditarr.core.errors import DomainValidationError, UpstreamError
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.intents.models import Intent, IntentEvent, PassthroughAction
from perevoditarr.modules.intents.passthrough import PassthroughService
from perevoditarr.modules.intents.schemas import (
    TimelineBazarrHistoryEntry,
    TimelineIntentEventEntry,
    TimelineLingarrRequestEntry,
    TimelinePassthroughEntry,
)
from perevoditarr.modules.intents.timeline import TimelineService
from tests.conftest import TEST_SECRET
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.scenario import Scenario

SECRET = SecretBox(TEST_SECRET)
NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


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


async def _seed(session: AsyncSession, scenario: Scenario) -> Intent:
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
    intent = Intent(
        bazarr_instance_id=instance.id,
        media_type="episode",
        external_media_id=101,
        sonarr_series_id=5,
        display_title="The Show",
        source_language="en",
        target_language="da",
        state="converged",
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
            created_at=NOW,
        )
    )
    await session.flush()
    return intent


def _timeline_service(session: AsyncSession, scenario: Scenario) -> TimelineService:
    return TimelineService(session, SECRET, SimulatorGateway(scenario))


def _passthrough_service(
    session: AsyncSession, scenario: Scenario
) -> PassthroughService:
    return PassthroughService(session, SECRET, SimulatorGateway(scenario))


async def test_timeline_stitches_all_durable_sources(
    session: AsyncSession, scenario: Scenario
) -> None:
    intent = await _seed(session, scenario)
    # Matching Lingarr request (§6.5: show title + pair, episode media type).
    _ = scenario.lingarr.add_request(
        media_id=None,
        title="The Show",
        source_language="en",
        target_language="da",
        media_type="Episode",
        status="Completed",
    )
    # Bazarr action-6 translation history for this episode.
    scenario.bazarr.episode_history.append(
        {
            "action": 6,
            "timestamp": NOW.isoformat(),
            "sonarrSeriesId": 5,
            "sonarrEpisodeId": 101,
            "seriesTitle": "The Show",
            "description": "da subtitle translated",
            "language": {"code2": "da", "name": "Danish"},
        }
    )
    # A prior pass-through action recorded in the audit trail.
    session.add(
        PassthroughAction(
            intent_id=intent.id,
            lingarr_request_id=1,
            action="retry",
            actor="user:admin",
            status="ok",
            detail=None,
            created_at=NOW,
        )
    )
    await session.commit()

    result = await _timeline_service(session, scenario).timeline(intent.id)
    assert result.bazarr_history_available is True
    assert result.lingarr_available is True
    kinds = {type(entry) for entry in result.entries}
    assert TimelineIntentEventEntry in kinds
    assert TimelineBazarrHistoryEntry in kinds
    assert TimelineLingarrRequestEntry in kinds
    assert TimelinePassthroughEntry in kinds


async def test_timeline_degrades_when_lingarr_unlinked(
    session: AsyncSession, scenario: Scenario
) -> None:
    intent = await _seed(session, scenario)
    instance = await session.get(BazarrInstance, intent.bazarr_instance_id)
    assert instance is not None
    instance.lingarr_instance_id = None  # unlink Lingarr
    await session.commit()

    result = await _timeline_service(session, scenario).timeline(intent.id)
    assert result.lingarr_available is False
    # The intent's own events are always present.
    assert any(isinstance(entry, TimelineIntentEventEntry) for entry in result.entries)


async def test_passthrough_cancel_is_applied_and_audited(
    session: AsyncSession, scenario: Scenario
) -> None:
    intent = await _seed(session, scenario)
    await session.commit()
    record = scenario.lingarr.add_request(
        media_id=None,
        title="The Show",
        source_language="en",
        target_language="da",
        media_type="Episode",
        status="Pending",
    )

    result = await _passthrough_service(session, scenario).act(
        intent.id, record.id, "cancel", actor="user:admin"
    )
    assert result.status == "ok"
    assert result.action == "cancel"
    assert result.actor == "user:admin"
    # Lingarr actually applied it.
    assert scenario.lingarr.requests[record.id].status == "Cancelled"
    # The audit row persisted.
    rows = (
        await session.scalars(
            select(PassthroughAction).where(PassthroughAction.intent_id == intent.id)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].action == "cancel"


async def test_passthrough_rejects_unknown_action(
    session: AsyncSession, scenario: Scenario
) -> None:
    intent = await _seed(session, scenario)
    await session.commit()
    with pytest.raises(DomainValidationError):
        _ = await _passthrough_service(session, scenario).act(
            intent.id, 1, "explode", actor="user:admin"
        )


async def test_passthrough_missing_request_errors_without_audit(
    session: AsyncSession, scenario: Scenario
) -> None:
    intent = await _seed(session, scenario)
    await session.commit()
    with pytest.raises(UpstreamError):
        _ = await _passthrough_service(session, scenario).act(
            intent.id, 999, "cancel", actor="user:admin"
        )
    rows = (
        await session.scalars(
            select(PassthroughAction).where(PassthroughAction.intent_id == intent.id)
        )
    ).all()
    assert len(rows) == 0
