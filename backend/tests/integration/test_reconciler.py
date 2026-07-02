"""Reconciler in Observe mode end-to-end (P2-T4): supersession from fresh
Bazarr metadata, action-6 annotation, steady-state quiet, unreachable-instance
isolation, startup re-observation (FR-R4), and SSE emission."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import override

import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.app import create_app
from perevoditarr.core.db import build_alchemy_config, metadata
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.discovery import DiscoveryService
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.reconciler import (
    ReconcilerService,
    run_reconciliation,
)
from perevoditarr.modules.intents.service import IntentSeed, IntentsService
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
from tests.conftest import TEST_SECRET
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.bazarr import SimSubtitle
from tests.simulators.scenario import Scenario
from tests.support import as_obj

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


def _json(value: msgspec.Struct) -> dict[str, object]:
    return msgspec.json.decode(msgspec.json.encode(value), type=dict[str, object])


async def _seed_world(session: AsyncSession, scenario: Scenario) -> BazarrInstance:
    """Mirror rows aligned 1:1 with the Bazarr simulator's library, so fresh
    metadata reads see the same world discovery planned from."""
    sim_series = scenario.seed_series(title="Alpha Show", episode_count=1)
    sim_movie = scenario.seed_movie(title="Alpha Movie")
    sim_episode_id = max(scenario.bazarr.episodes)
    secret = SecretBox(TEST_SECRET)
    instance = BazarrInstance(
        name="main",
        url="http://bazarr.test",
        api_key_encrypted=secret.encrypt_text(scenario.bazarr.api_key),
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
                grace_hours_episodes=0,
                grace_hours_movies=0,
            )
        ),
    )
    series = Series(
        bazarr_instance_id=instance.id,
        sonarr_series_id=sim_series.sonarr_series_id,
        title="Alpha Show",
        sort_title="alpha show",
        monitored=True,
    )
    session.add_all([preset, series])
    await session.flush()
    episode = Episode(
        bazarr_instance_id=instance.id,
        series_id=series.id,
        sonarr_series_id=sim_series.sonarr_series_id,
        sonarr_episode_id=sim_episode_id,
        title="Episode 1",
        season=1,
        episode=1,
        monitored=True,
    )
    movie = Movie(
        bazarr_instance_id=instance.id,
        radarr_id=sim_movie.radarr_id,
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
            SyncRun(
                bazarr_instance_id=instance.id,
                kind="wanted",
                status="completed",
                started_at=datetime.now(UTC) - timedelta(minutes=1),
                finished_at=datetime.now(UTC),
            ),
        ]
    )
    await session.commit()
    return instance


async def _discover(
    session: AsyncSession, scenario: Scenario, instance: BazarrInstance
) -> None:
    discovery = DiscoveryService(
        session, SecretBox(TEST_SECRET), SimulatorGateway(scenario), SseBus()
    )
    _ = await discovery.run_for_instance(instance.id)


def _reconciler(
    session: AsyncSession, scenario: Scenario
) -> tuple[ReconcilerService, RecordingBus]:
    bus = RecordingBus()
    service = ReconcilerService(
        session, SecretBox(TEST_SECRET), SimulatorGateway(scenario), bus
    )
    return service, bus


def _appeared_history_row(*, episode_id: int) -> dict[str, object]:
    return {
        "action": 6,
        # Must postdate the intent's creation: the history window (since
        # intent.created_at) is real wall-clock, the sim clock is not.
        "timestamp": datetime.now(UTC).isoformat(),
        "sonarrSeriesId": 1,
        "sonarrEpisodeId": episode_id,
        "language": {
            "name": "Danish",
            "code2": "da",
            "code3": "dax",
            "forced": False,
            "hi": False,
        },
        "subtitles_path": "/subs/e1.da.srt",
        "description": "translated using Lingarr",
        "upgradable": True,
    }


async def test_supersedes_when_subtitle_appears_by_other_means(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_world(session, scenario)
    await _discover(session, scenario, instance)
    episode_id = max(scenario.bazarr.episodes)
    scenario.bazarr.episodes[episode_id].subtitles.append(
        SimSubtitle(code2="da", path="/subs/e1.da.srt")
    )
    reconciler, _ = _reconciler(session, scenario)

    summary = await reconciler.run_for_instance(instance)

    assert summary.examined == 2
    assert summary.superseded_other == 1
    assert summary.superseded_via_translation == 0
    assert summary.unchanged == 1
    row = (
        await session.scalars(select(Intent).where(Intent.media_type == "episode"))
    ).one()
    assert row.state == IntentState.SUPERSEDED.value
    trace = row.decision_trace or []
    assert any(step.get("type") == "evidence_observed" for step in trace)
    event = (
        await session.scalars(
            select(IntentEvent).where(
                IntentEvent.intent_id == row.id,
                IntentEvent.to_state == IntentState.SUPERSEDED.value,
            )
        )
    ).one()
    assert event.actor == "reconciler"
    assert event.reason == "superseded: target subtitle appeared by other means"
    evidence: dict[str, object] = event.evidence or {}
    assert evidence.get("kind") == "reconciliation"
    assert as_obj(evidence.get("metadata")).get("file_backed") is True


async def test_action_6_history_annotates_supersession_as_translation(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_world(session, scenario)
    await _discover(session, scenario, instance)
    episode_id = max(scenario.bazarr.episodes)
    scenario.bazarr.episodes[episode_id].subtitles.append(
        SimSubtitle(code2="da", path="/subs/e1.da.srt")
    )
    scenario.bazarr.episode_history.append(_appeared_history_row(episode_id=episode_id))
    reconciler, _ = _reconciler(session, scenario)

    summary = await reconciler.run_for_instance(instance)

    assert summary.superseded_via_translation == 1
    assert summary.superseded_other == 0
    row = (
        await session.scalars(select(Intent).where(Intent.media_type == "episode"))
    ).one()
    event = (
        await session.scalars(
            select(IntentEvent).where(
                IntentEvent.intent_id == row.id,
                IntentEvent.to_state == IntentState.SUPERSEDED.value,
            )
        )
    ).one()
    assert "via translation" in event.reason
    evidence: dict[str, object] = event.evidence or {}
    assert as_obj(evidence.get("history")).get("translated") is True


async def test_steady_state_pass_writes_nothing(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_world(session, scenario)
    await _discover(session, scenario, instance)
    baseline_events = len((await session.scalars(select(IntentEvent))).all())
    reconciler, _ = _reconciler(session, scenario)

    for _round in range(2):
        summary = await reconciler.run_for_instance(instance)
        assert summary.unchanged == 2
        assert summary.superseded_other == 0
        assert summary.superseded_via_translation == 0

    assert len((await session.scalars(select(IntentEvent))).all()) == baseline_events
    rows = (await session.scalars(select(Intent))).all()
    assert {row.state for row in rows} == {IntentState.ELIGIBLE.value}


async def test_unreachable_instance_never_breaks_the_pass(
    session: AsyncSession, scenario: Scenario, app_settings: AppSettings
) -> None:
    instance = await _seed_world(session, scenario)
    await _discover(session, scenario, instance)
    # Second instance whose api key the simulator rejects: its evidence
    # collection fails mid-pass; isolation must contain it and the healthy
    # instance must still reconcile. A backlog intent forces the client call.
    secret = SecretBox(TEST_SECRET)
    broken = BazarrInstance(
        name="broken",
        url="http://bazarr-broken.test",
        api_key_encrypted=secret.encrypt_text("wrong-key"),
    )
    session.add(broken)
    await session.flush()
    broken_intent, _created = await IntentsService(session).upsert(
        IntentSeed(
            bazarr_instance_id=broken.id,
            media_type="movie",
            external_media_id=999,
            display_title="Broken Movie",
            source_language="en",
            target_language="da",
        )
    )
    # Snapshot ids before expire_all: expired attributes lazy-load and raise
    # under async.
    instance_id = instance.id
    broken_intent_id = broken_intent.id
    episode_id = max(scenario.bazarr.episodes)
    scenario.bazarr.episodes[episode_id].subtitles.append(
        SimSubtitle(code2="da", path="/subs/e1.da.srt")
    )
    bus = RecordingBus()

    await run_reconciliation(
        build_alchemy_config(app_settings),
        SimulatorGateway(scenario),
        secret,
        bus,
    )

    session.expire_all()
    row = (
        await session.scalars(
            select(Intent).where(
                Intent.media_type == "episode",
                Intent.bazarr_instance_id == instance_id,
            )
        )
    ).one()
    assert row.state == IntentState.SUPERSEDED.value
    untouched = await session.get_one(Intent, broken_intent_id)
    assert untouched.state == IntentState.DISCOVERED.value
    # The healthy instance emitted its summary; the broken one only logged.
    topics = [topic for topic, _ in bus.events]
    assert topics.count("intents.reconciled") == 1


async def test_startup_reobservation_supersedes_after_crash(
    app_settings: AppSettings, scenario: Scenario
) -> None:
    # Seed ledger + world, then "crash": the subtitle appears while we are
    # down. Booting the app must re-observe and supersede (FR-R4) before any
    # loop runs (all loop intervals are 0 in tests).
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        instance = await _seed_world(session, scenario)
        await _discover(session, scenario, instance)
    await engine.dispose()

    episode_id = max(scenario.bazarr.episodes)
    scenario.bazarr.episodes[episode_id].subtitles.append(
        SimSubtitle(code2="da", path="/subs/e1.da.srt")
    )

    app: Litestar = create_app(settings=app_settings)
    app.state["gateway"] = SimulatorGateway(scenario)
    with TestClient(app=app):
        pass

    engine = create_async_engine(app_settings.database_url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        row = (
            await session.scalars(select(Intent).where(Intent.media_type == "episode"))
        ).one()
        assert row.state == IntentState.SUPERSEDED.value
        event = (
            await session.scalars(
                select(IntentEvent).where(
                    IntentEvent.intent_id == row.id,
                    IntentEvent.to_state == IntentState.SUPERSEDED.value,
                )
            )
        ).one()
        assert event.actor == "startup"
    await engine.dispose()


async def test_reconcile_emits_sse_summary(
    session: AsyncSession, scenario: Scenario
) -> None:
    instance = await _seed_world(session, scenario)
    await _discover(session, scenario, instance)
    reconciler, bus = _reconciler(session, scenario)

    _ = await reconciler.run_for_instance(instance)

    payload = next(data for topic, data in bus.events if topic == "intents.reconciled")
    assert isinstance(payload, dict)
    assert payload["instanceId"] == str(instance.id)
    assert payload["examined"] == 2
    assert payload["unchanged"] == 2
