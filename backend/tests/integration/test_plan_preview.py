"""Plan preview end-to-end (P2-T5): discovery → scored backlog → explained,
deterministic preview; per-profile weight overrides with visible provenance."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

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

from perevoditarr.core.db import metadata
from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.dispatch.schemas import HeldVerdictDto, IncludedVerdictDto
from perevoditarr.modules.dispatch.service import PlanPreviewService
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.discovery import DiscoveryService
from perevoditarr.modules.intents.models import Intent
from perevoditarr.modules.mirror.models import (
    Episode,
    Movie,
    Series,
    Subtitle,
    SyncRun,
    WantedSubtitle,
)
from perevoditarr.modules.policy.models import (
    Preset,
    ProfileAssignment,
    TranslationProfile,
)
from perevoditarr.modules.policy.resolver import PolicyValues, PriorityWeights
from perevoditarr.modules.policy.schemas import RailSettingsDto
from tests.conftest import TEST_SECRET, complete_setup
from tests.support import as_list, as_obj, json_obj

LONG_AGO = datetime.now(UTC) - timedelta(days=30)


@pytest.fixture
async def session(app_settings: AppSettings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


@pytest.fixture
def api_client(app: Litestar) -> Iterator[TestClient[Litestar]]:
    with TestClient(app=app) as test_client:
        complete_setup(test_client)
        yield test_client


def _json(value: msgspec.Struct) -> dict[str, object]:
    return msgspec.json.decode(msgspec.json.encode(value), type=dict[str, object])


def _services(session: AsyncSession) -> tuple[DiscoveryService, PlanPreviewService]:
    gateway = InstanceGateway(HttpClientRegistry())
    secret_box = SecretBox(TEST_SECRET)
    return (
        DiscoveryService(session, secret_box, gateway, SseBus()),
        PlanPreviewService(session, secret_box, gateway),
    )


async def _seed_world(
    session: AsyncSession, *, rails: RailSettingsDto | None = None
) -> UUID:
    """One instance, active preset (grace 0, target `da`), a continuing series
    with two wanted episodes (same en->da pair — the §6.5 case), one movie."""
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
                grace_hours_episodes=0,
                grace_hours_movies=0,
            )
        ),
        rails=_json(rails) if rails is not None else None,
    )
    series = Series(
        bazarr_instance_id=instance.id,
        sonarr_series_id=11,
        title="Alpha Show",
        sort_title="alpha show",
        monitored=True,
        ended=False,  # continuing ⇒ scorer bonus ⇒ episodes outrank the movie
    )
    session.add_all([preset, series])
    await session.flush()
    episodes = [
        Episode(
            bazarr_instance_id=instance.id,
            series_id=series.id,
            sonarr_series_id=11,
            sonarr_episode_id=100 + number,
            title=f"Episode {number}",
            season=1,
            episode=number,
            monitored=True,
        )
        for number in (1, 2)
    ]
    movie = Movie(
        bazarr_instance_id=instance.id,
        radarr_id=7,
        title="Alpha Movie",
        sort_title="alpha movie",
        monitored=True,
    )
    session.add_all([*episodes, movie])
    await session.flush()
    rows: list[object] = [
        Subtitle(
            bazarr_instance_id=instance.id,
            movie_id=movie.id,
            language="en",
            file_path="/subs/alpha-movie.en.srt",
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
    for episode in episodes:
        rows.append(
            Subtitle(
                bazarr_instance_id=instance.id,
                episode_id=episode.id,
                language="en",
                file_path=f"/subs/alpha-s01e{episode.episode}.en.srt",
            )
        )
        rows.append(
            WantedSubtitle(
                bazarr_instance_id=instance.id,
                episode_id=episode.id,
                language="da",
                first_seen_at=LONG_AGO,
                last_seen_at=datetime.now(UTC),
            )
        )
    session.add_all(rows)
    await session.commit()
    return instance.id


async def test_preview_explains_inclusions_and_invariant_holds(
    session: AsyncSession,
) -> None:
    instance_id = await _seed_world(session, rails=RailSettingsDto(dispatch_window_k=5))
    discovery, preview = _services(session)
    _ = await discovery.run_for_instance(instance_id)

    response = await preview.preview(limit=10)

    assert response.active_preset == "Test posture"
    assert response.dry_run is True  # global default: preset never set it
    assert response.totals.evaluated == 3
    # Two episodes share (instance, series, en->da): §6.5 holds the second.
    assert response.totals.included == 2
    assert response.totals.held == 1
    held = [
        item
        for item in response.items
        if isinstance(item.verdict, HeldVerdictDto) and item.verdict.rail == "invariant"
    ]
    assert len(held) == 1
    assert held[0].media_type == "episode"
    included = [
        item for item in response.items if isinstance(item.verdict, IncludedVerdictDto)
    ]
    assert {item.media_type for item in included} == {"episode", "movie"}
    # No Lingarr configured ⇒ heuristic estimates, labeled as such.
    assert all(item.estimate.basis == "heuristic" for item in response.items)
    assert response.totals.estimated_characters > 0
    # Scorer provenance rides along for the UI.
    assert all(item.score_components is not None for item in included)
    groups = response.groups
    assert len(groups) == 1
    assert groups[0].instance_name == "main"
    assert groups[0].included == 2


async def test_preview_simulates_preset_rail_posture(session: AsyncSession) -> None:
    instance_id = await _seed_world(session, rails=RailSettingsDto(dispatch_window_k=1))
    discovery, preview = _services(session)
    _ = await discovery.run_for_instance(instance_id)

    response = await preview.preview(limit=10)

    assert response.rails.dispatch_window_k == 1
    assert response.totals.included == 1
    rails_hit = {
        item.verdict.rail
        for item in response.items
        if isinstance(item.verdict, HeldVerdictDto)
    }
    assert "window" in rails_hit


async def test_preview_is_deterministic_across_calls(session: AsyncSession) -> None:
    instance_id = await _seed_world(session)
    discovery, preview = _services(session)
    _ = await discovery.run_for_instance(instance_id)

    first = await preview.preview(limit=10)
    second = await preview.preview(limit=10)

    # generated_at differs; everything the plan *says* must not.
    assert msgspec.json.encode(first.items) == msgspec.json.encode(second.items)
    assert msgspec.json.encode(first.totals) == msgspec.json.encode(second.totals)


async def test_profile_weight_override_reorders_with_provenance(
    session: AsyncSession,
) -> None:
    instance_id = await _seed_world(session)
    discovery, preview = _services(session)
    _ = await discovery.run_for_instance(instance_id)

    baseline = await preview.preview(limit=10)
    # Continuing-series bonus puts an episode ahead of the movie by default.
    assert baseline.items[0].media_type == "episode"

    profile = TranslationProfile(
        name="Movies first",
        values=_json(PolicyValues(priority_weights=PriorityWeights(movie_base=500))),
    )
    session.add(profile)
    await session.flush()
    session.add(
        ProfileAssignment(
            profile_id=profile.id,
            bazarr_instance_id=instance_id,
            scope_type="instance",
            scope_key="",
        )
    )
    await session.commit()
    _ = await discovery.run_for_instance(instance_id)  # steady-state rescore

    reordered = await preview.preview(limit=10)
    assert reordered.items[0].media_type == "movie"

    movie_intent = (
        await session.scalars(select(Intent).where(Intent.media_type == "movie"))
    ).one()
    steps = movie_intent.decision_trace or []
    priority_steps = [s for s in steps if s.get("type") == "priority_assigned"]
    assert len(priority_steps) == 1
    assert priority_steps[0].get("weights_layer") == "profile"
    score = priority_steps[0].get("score")
    assert isinstance(score, int) and score >= 500


async def test_preview_api_shape_and_auth(
    api_client: TestClient[Litestar], session: AsyncSession
) -> None:
    instance_id = await _seed_world(session)
    discovery, _ = _services(session)
    _ = await discovery.run_for_instance(instance_id)

    body = json_obj(api_client.get("/api/v1/plan/preview?limit=2"))
    assert body["activePreset"] == "Test posture"
    assert body["dryRun"] is True
    assert body["limit"] == 2
    totals = as_obj(body["totals"])
    assert totals["evaluated"] == 3
    assert totals["included"] == 2
    items = as_list(body["items"])
    first = as_obj(items[0])
    verdict = as_obj(first["verdict"])
    assert verdict["type"] == "included"
    assert verdict["position"] == 1
    estimate = as_obj(first["estimate"])
    assert estimate["basis"] == "heuristic"
    held_types = {
        as_obj(as_obj(item)["verdict"])["type"]
        for item in items
        if as_obj(as_obj(item)["verdict"])["type"] != "included"
    }
    assert held_types == {"held"}

    filtered = json_obj(
        api_client.get(f"/api/v1/plan/preview?bazarr_instance_id={instance_id}")
    )
    assert as_obj(filtered["totals"])["evaluated"] == 3

    bad_limit = api_client.get("/api/v1/plan/preview?limit=0")
    assert bad_limit.status_code == 400

    api_client.cookies.clear()
    unauthorized = api_client.get("/api/v1/plan/preview")
    assert unauthorized.status_code == 401
