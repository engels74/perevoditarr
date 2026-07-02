"""Discovery engine end-to-end (P2-T3): idempotent seeding, eligible
advancement, withdrawal on wanted disappearance, and SSE emission."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import override
from uuid import UUID

import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.db import metadata
from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.discovery import DiscoveryService
from perevoditarr.modules.intents.discovery_rules import NotPlanned, Planned
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.state_machine import IntentState
from perevoditarr.modules.mirror.models import (
    Episode,
    Movie,
    Series,
    Subtitle,
    SyncRun,
    WantedSubtitle,
)
from perevoditarr.modules.policy.models import Preset
from perevoditarr.modules.policy.resolver import PolicyValues
from tests.conftest import TEST_SECRET, complete_setup

LONG_AGO = datetime.now(UTC) - timedelta(days=30)


class RecordingBus(SseBus):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, object]] = []

    @override
    def publish(self, topic: str, data: object) -> None:
        self.events.append((topic, data))
        super().publish(topic, data)


@pytest.fixture
async def session(app_settings: AppSettings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


def _service(session: AsyncSession) -> tuple[DiscoveryService, RecordingBus]:
    bus = RecordingBus()
    gateway = InstanceGateway(HttpClientRegistry())
    return DiscoveryService(session, SecretBox(TEST_SECRET), gateway, bus), bus


def _json(value: msgspec.Struct) -> dict[str, object]:
    return msgspec.json.decode(msgspec.json.encode(value), type=dict[str, object])


async def _seed_world(
    session: AsyncSession,
    *,
    grace_hours: int = 0,
    with_completed_pass: bool = True,
) -> UUID:
    instance = BazarrInstance(
        name="main", url="http://bazarr.test", api_key_encrypted=b"k"
    )
    session.add(instance)
    await session.flush()
    preset = Preset(
        name="Test posture",
        built_in=False,
        active=True,
        values=_json(
            PolicyValues(
                target_languages=["da"],
                source_preferences=["en"],
                grace_hours_episodes=grace_hours,
                grace_hours_movies=grace_hours,
            )
        ),
    )
    series = Series(
        bazarr_instance_id=instance.id,
        sonarr_series_id=11,
        title="Alpha Show",
        sort_title="alpha show",
        monitored=True,
    )
    session.add_all([preset, series])
    await session.flush()
    episode = Episode(
        bazarr_instance_id=instance.id,
        series_id=series.id,
        sonarr_series_id=11,
        sonarr_episode_id=101,
        title="Pilot",
        season=1,
        episode=1,
        monitored=True,
    )
    movie = Movie(
        bazarr_instance_id=instance.id,
        radarr_id=7,
        title="Alpha Movie",
        sort_title="alpha movie",
        monitored=True,
    )
    session.add_all([episode, movie])
    await session.flush()
    session.add_all(
        [
            Subtitle(
                bazarr_instance_id=instance.id,
                episode_id=episode.id,
                language="en",
                file_path="/subs/alpha-s01e01.en.srt",
            ),
            Subtitle(
                bazarr_instance_id=instance.id,
                movie_id=movie.id,
                language="en",
                file_path="/subs/alpha-movie.en.srt",
            ),
            WantedSubtitle(
                bazarr_instance_id=instance.id,
                episode_id=episode.id,
                language="da",
                first_seen_at=LONG_AGO,
                last_seen_at=datetime.now(UTC),
            ),
            WantedSubtitle(
                bazarr_instance_id=instance.id,
                movie_id=movie.id,
                language="da",
                first_seen_at=LONG_AGO,
                last_seen_at=datetime.now(UTC),
            ),
        ]
    )
    if with_completed_pass:
        session.add(
            SyncRun(
                bazarr_instance_id=instance.id,
                kind="wanted",
                status="completed",
                started_at=datetime.now(UTC) - timedelta(minutes=1),
                finished_at=datetime.now(UTC),
            )
        )
    await session.commit()
    return instance.id


async def test_discovery_plans_and_advances_to_eligible(
    session: AsyncSession,
) -> None:
    instance_id = await _seed_world(session)
    discovery, _ = _service(session)
    summary = await discovery.run_for_instance(instance_id)

    assert summary.evaluated == 2
    assert summary.planned == 2
    assert summary.created == 2
    assert summary.advanced_to_eligible == 2
    rows = (await session.scalars(select(Intent))).all()
    assert {row.state for row in rows} == {IntentState.ELIGIBLE.value}
    assert {row.media_type for row in rows} == {"episode", "movie"}
    assert all(row.source_language == "en" for row in rows)
    events = (await session.scalars(select(IntentEvent))).all()
    # Per intent: creation (∅→discovered) + discovered→eligible.
    assert len(events) == 4


async def test_discovery_is_idempotent(session: AsyncSession) -> None:
    instance_id = await _seed_world(session)
    discovery, _ = _service(session)
    _ = await discovery.run_for_instance(instance_id)
    first_events = len((await session.scalars(select(IntentEvent))).all())

    again = await discovery.run_for_instance(instance_id)

    assert again.created == 0
    assert again.withdrawn == 0
    rows = (await session.scalars(select(Intent))).all()
    assert len(rows) == 2
    # Steady state: no new audit rows, no state churn.
    assert len((await session.scalars(select(IntentEvent))).all()) == first_events


async def test_wanted_disappearance_withdraws(session: AsyncSession) -> None:
    instance_id = await _seed_world(session)
    discovery, _ = _service(session)
    _ = await discovery.run_for_instance(instance_id)

    _ = await session.execute(
        delete(WantedSubtitle).where(WantedSubtitle.episode_id.is_not(None))
    )
    await session.commit()
    summary = await discovery.run_for_instance(instance_id)

    assert summary.withdrawn == 1
    episode_intent = (
        await session.scalars(select(Intent).where(Intent.media_type == "episode"))
    ).one()
    assert episode_intent.state == IntentState.SUPERSEDED.value
    trace = episode_intent.decision_trace or []
    assert any(step.get("type") == "withdrawn" for step in trace)
    movie_intent = (
        await session.scalars(select(Intent).where(Intent.media_type == "movie"))
    ).one()
    assert movie_intent.state == IntentState.ELIGIBLE.value


async def test_no_withdrawal_without_a_completed_wanted_pass(
    session: AsyncSession,
) -> None:
    instance_id = await _seed_world(session, with_completed_pass=False)
    discovery, _ = _service(session)
    _ = await discovery.run_for_instance(instance_id)

    _ = await session.execute(delete(WantedSubtitle))
    await session.commit()
    summary = await discovery.run_for_instance(instance_id)

    # An empty wanted table without a completed pass proves nothing (FR-R4).
    assert summary.withdrawn == 0
    rows = (await session.scalars(select(Intent))).all()
    assert {row.state for row in rows} == {IntentState.ELIGIBLE.value}


async def test_grace_pending_candidates_are_not_upserted(
    session: AsyncSession,
) -> None:
    instance_id = await _seed_world(session, grace_hours=24 * 365)
    discovery, _ = _service(session)
    summary = await discovery.run_for_instance(instance_id)

    assert summary.planned == 0
    assert summary.not_planned.get("grace_pending") == 2
    assert (await session.scalars(select(Intent))).all() == []


async def test_discovery_emits_sse_summary(session: AsyncSession) -> None:
    instance_id = await _seed_world(session)
    discovery, bus = _service(session)
    _ = await discovery.run_for_instance(instance_id)

    topics = [topic for topic, _ in bus.events]
    assert "intents.discovered" in topics
    payload = next(data for topic, data in bus.events if topic == "intents.discovered")
    assert isinstance(payload, dict)
    assert payload["instanceId"] == str(instance_id)
    assert payload["created"] == 2


# ---------------------------------------------------------------- explainer


async def test_explain_wanted_planned(session: AsyncSession) -> None:
    instance_id = await _seed_world(session)
    discovery, _ = _service(session)
    decision = await discovery.explain_wanted(
        instance_id,
        media_type="episode",
        external_media_id=101,
        language="da",
        forced=False,
        hi=False,
    )
    assert isinstance(decision, Planned)
    assert decision.source_language == "en"
    assert decision.trace


async def test_explain_wanted_grace_pending(session: AsyncSession) -> None:
    instance_id = await _seed_world(session, grace_hours=24 * 365)
    discovery, _ = _service(session)
    decision = await discovery.explain_wanted(
        instance_id,
        media_type="movie",
        external_media_id=7,
        language="da",
        forced=False,
        hi=False,
    )
    assert isinstance(decision, NotPlanned)
    assert decision.reason == "grace_pending"


async def test_explain_wanted_not_wanted(session: AsyncSession) -> None:
    instance_id = await _seed_world(session)
    discovery, _ = _service(session)
    decision = await discovery.explain_wanted(
        instance_id,
        media_type="movie",
        external_media_id=999,
        language="da",
        forced=False,
        hi=False,
    )
    assert decision is None


@pytest.fixture
def api_client(app: Litestar) -> Iterator[TestClient[Litestar]]:
    with TestClient(app=app) as test_client:
        complete_setup(test_client)
        yield test_client


def _explain_url(instance_id: UUID, query: str) -> str:
    return f"/api/v1/intents/explain?bazarr_instance_id={instance_id}&{query}"


async def test_api_explain_candidate(
    api_client: TestClient[Litestar], session: AsyncSession
) -> None:
    instance_id = await _seed_world(session)
    planned = api_client.get(
        _explain_url(
            instance_id, "media_type=episode&external_media_id=101&language=da"
        )
    )
    assert planned.status_code == 200
    body: dict[str, object] = msgspec.json.decode(
        planned.content, type=dict[str, object]
    )
    assert body["outcome"] == "planned"
    assert body["sourceLanguage"] == "en"
    assert body["traceSteps"]
    assert "source `en`" in str(body["traceRendered"])

    missing = api_client.get(
        _explain_url(instance_id, "media_type=movie&external_media_id=999&language=da")
    )
    assert missing.status_code == 200
    outcome: dict[str, object] = msgspec.json.decode(
        missing.content, type=dict[str, object]
    )
    assert outcome["outcome"] == "not_wanted"
