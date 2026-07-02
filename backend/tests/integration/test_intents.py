"""Intent ledger end-to-end (P2-T2): natural-key idempotence, evented
transitions, §6.5 in-flight lookups, backlog ordering, and the read API."""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.db import metadata
from perevoditarr.core.errors import DomainValidationError
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.service import IntentSeed, IntentsService
from perevoditarr.modules.intents.state_machine import (
    IllegalIntentTransition,
    IntentState,
)
from perevoditarr.modules.intents.trace import (
    GraceEvaluated,
    PriorityAssigned,
    ProfileMatched,
    SourceElected,
    TargetMissing,
    TraceStep,
)
from tests.conftest import complete_setup
from tests.support import as_list, as_obj, json_obj

TRACE: tuple[TraceStep, ...] = (
    ProfileMatched(profile_name="Anime", layer="profile"),
    TargetMissing(language="da"),
    SourceElected(chosen="en", considered=("ja",)),
    GraceEvaluated(passed=True),
    PriorityAssigned(score=3),
)


@pytest.fixture
async def session(app_settings: AppSettings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


async def _seed_instance(session: AsyncSession, name: str = "main") -> UUID:
    row = BazarrInstance(
        name=name, url=f"http://{name}.bazarr.test", api_key_encrypted=b"k"
    )
    session.add(row)
    await session.commit()
    return row.id


def _episode_seed(
    instance_id: UUID,
    *,
    episode_id: int = 101,
    series_id: int = 11,
    source: str = "en",
    target: str = "da",
    priority: int = 0,
    trace: tuple[TraceStep, ...] = (),
) -> IntentSeed:
    return IntentSeed(
        bazarr_instance_id=instance_id,
        media_type="episode",
        external_media_id=episode_id,
        sonarr_series_id=series_id,
        season=1,
        episode_number=episode_id % 100,
        display_title="Alpha Show",
        source_language=source,
        target_language=target,
        priority=priority,
        trace=trace,
    )


async def _event_count(session: AsyncSession, intent_id: UUID) -> int:
    return (
        await session.execute(
            select(func.count(IntentEvent.id)).where(IntentEvent.intent_id == intent_id)
        )
    ).scalar_one()


async def test_upsert_with_known_row_skips_lookup_and_refreshes(
    session: AsyncSession,
) -> None:
    # Discovery's batched path: the caller supplies the batch-loaded row and
    # defers the commit; no per-item SELECT, no duplicate, fields refresh.
    instance_id = await _seed_instance(session)
    service = IntentsService(session)
    first, created = await service.upsert(_episode_seed(instance_id, priority=1))
    assert created

    refreshed, created_again = await service.upsert(
        _episode_seed(instance_id, priority=7),
        existing_row=first,
        skip_lookup=True,
        commit=False,
    )
    await session.commit()
    assert not created_again
    assert refreshed.id == first.id
    assert refreshed.priority == 7
    total = (await session.execute(select(func.count(Intent.id)))).scalar_one()
    assert total == 1


async def test_skip_lookup_conflict_surfaces_integrity_error(
    session: AsyncSession,
) -> None:
    # The residual cross-process race: a writer created the row between the
    # batch map load and the insert. skip_lookup inserts blind, the natural
    # key rejects it, and the error type is exactly what discovery's batch
    # safety net catches (rollback + defer to next pass).
    instance_id = await _seed_instance(session)
    service = IntentsService(session)
    _ = await service.upsert(_episode_seed(instance_id))

    with pytest.raises(IntegrityError):
        _ = await service.upsert(
            _episode_seed(instance_id), skip_lookup=True, commit=False
        )
    await session.rollback()
    total = (await session.execute(select(func.count(Intent.id)))).scalar_one()
    assert total == 1


async def test_upsert_is_idempotent_on_natural_key(session: AsyncSession) -> None:
    instance_id = await _seed_instance(session)
    service = IntentsService(session)

    first, created = await service.upsert(
        _episode_seed(instance_id, priority=1, trace=TRACE)
    )
    assert created
    again, created_again = await service.upsert(
        _episode_seed(instance_id, priority=9, source="de")
    )
    assert not created_again
    assert again.id == first.id
    assert again.priority == 9
    assert again.source_language == "de"  # re-election updates, never duplicates

    total = (await session.execute(select(func.count(Intent.id)))).scalar_one()
    assert total == 1
    # Exactly one creation event: (none) → discovered.
    assert await _event_count(session, first.id) == 1
    event = (
        await session.scalars(
            select(IntentEvent).where(IntentEvent.intent_id == first.id)
        )
    ).one()
    assert event.from_state is None
    assert event.to_state == "discovered"
    assert event.actor == "discovery"


async def test_upsert_episode_requires_series_id(session: AsyncSession) -> None:
    instance_id = await _seed_instance(session)
    service = IntentsService(session)
    seed = IntentSeed(
        bazarr_instance_id=instance_id,
        media_type="episode",
        external_media_id=1,
        display_title="X",
        source_language="en",
        target_language="da",
    )
    with pytest.raises(DomainValidationError):
        _ = await service.upsert(seed)


async def test_transitions_write_events_and_reject_illegal(
    session: AsyncSession,
) -> None:
    instance_id = await _seed_instance(session)
    service = IntentsService(session)
    intent, _ = await service.upsert(_episode_seed(instance_id))

    _ = await service.transition(
        intent, IntentState.ELIGIBLE, actor="reconciler", reason="grace passed"
    )
    assert intent.state == "eligible"
    assert await _event_count(session, intent.id) == 2

    with pytest.raises(IllegalIntentTransition):
        _ = await service.transition(
            intent, IntentState.CONVERGED, actor="reconciler", reason="nope"
        )
    assert intent.state == "eligible"  # unchanged
    assert await _event_count(session, intent.id) == 2  # no audit row leaked

    lease = datetime(2026, 7, 2, 15, 0, tzinfo=UTC)
    _ = await service.transition(
        intent,
        IntentState.DISPATCHED,
        actor="dispatcher",
        reason="slot free",
        lease_expires_at=lease,
    )
    assert intent.lease_expires_at is not None
    _ = await service.transition(
        intent,
        IntentState.CONVERGED,
        actor="reconciler",
        reason="subtitle present, history action 6 in lease",
        evidence={"history_action": 6},
    )
    assert intent.state == "converged"
    assert intent.lease_expires_at is None  # terminal clears the lease
    assert await _event_count(session, intent.id) == 4

    # Terminal intents are left untouched by re-discovery.
    same, created = await service.upsert(_episode_seed(instance_id, priority=42))
    assert not created
    assert same.id == intent.id
    assert same.priority != 42


async def test_backlog_orders_bumped_then_priority(session: AsyncSession) -> None:
    instance_id = await _seed_instance(session)
    service = IntentsService(session)
    low, _ = await service.upsert(
        _episode_seed(instance_id, episode_id=1, series_id=1, priority=1)
    )
    _high, _ = await service.upsert(
        _episode_seed(instance_id, episode_id=2, series_id=2, priority=5)
    )
    _mid, _ = await service.upsert(
        _episode_seed(instance_id, episode_id=3, series_id=3, priority=3)
    )
    low.bumped_at = datetime.now(UTC)  # manual bump-to-front (FR-Q4)
    await session.commit()

    page = await service.backlog()
    assert page.total == 3
    assert [item.priority for item in page.items] == [1, 5, 3]
    assert page.items[0].bumped_at is not None


async def test_in_flight_lookups_honor_65_granularity(
    session: AsyncSession,
) -> None:
    instance_id = await _seed_instance(session)
    other_instance_id = await _seed_instance(session, name="fourk")
    service = IntentsService(session)

    episode, _ = await service.upsert(
        _episode_seed(instance_id, episode_id=101, series_id=11)
    )
    _ = await service.transition(episode, IntentState.ELIGIBLE, actor="t", reason="t")
    _ = await service.transition(episode, IntentState.DISPATCHED, actor="t", reason="t")
    movie, _ = await service.upsert(
        IntentSeed(
            bazarr_instance_id=instance_id,
            media_type="movie",
            external_media_id=77,
            display_title="Alpha Movie",
            source_language="en",
            target_language="da",
        )
    )
    _ = await service.transition(movie, IntentState.ELIGIBLE, actor="t", reason="t")
    _ = await service.transition(movie, IntentState.DISPATCHED, actor="t", reason="t")
    # A second episode of the same show on the same pair, NOT dispatched:
    # must not trip the probe (only in-flight counts).
    _idle, _ = await service.upsert(
        _episode_seed(instance_id, episode_id=102, series_id=11)
    )

    assert await service.has_in_flight_series_pair(instance_id, 11, "en", "da")
    assert not await service.has_in_flight_series_pair(instance_id, 11, "en", "sv")
    assert not await service.has_in_flight_series_pair(instance_id, 12, "en", "da")
    assert not await service.has_in_flight_series_pair(
        other_instance_id, 11, "en", "da"
    )
    assert await service.has_in_flight_movie_pair(instance_id, 77, "en", "da")
    assert not await service.has_in_flight_movie_pair(instance_id, 78, "en", "da")
    assert not await service.has_in_flight_movie_pair(instance_id, 77, "en", "sv")

    in_flight = await service.in_flight(bazarr_instance_id=instance_id)
    assert in_flight.total == 2


async def test_history_filters(session: AsyncSession) -> None:
    instance_id = await _seed_instance(session)
    service = IntentsService(session)
    episode, _ = await service.upsert(_episode_seed(instance_id))
    _ = await service.transition(episode, IntentState.SUPERSEDED, actor="t", reason="t")
    _movie, _ = await service.upsert(
        IntentSeed(
            bazarr_instance_id=instance_id,
            media_type="movie",
            external_media_id=77,
            display_title="Alpha Movie",
            source_language="en",
            target_language="sv",
        )
    )

    everything = await service.history()
    assert everything.total == 2
    superseded = await service.history(states=[IntentState.SUPERSEDED])
    assert [item.id for item in superseded.items] == [episode.id]
    movies = await service.history(media_type="movie")
    assert movies.total == 1
    swedish = await service.history(target_language="sv")
    assert swedish.total == 1
    nothing = await service.history(created_before=datetime(2000, 1, 1, tzinfo=UTC))
    assert nothing.total == 0
    assert (await service.history(bazarr_instance_id=uuid4())).total == 0


# ------------------------------------------------------------ read API


@pytest.fixture
def api_client(app: Litestar) -> Iterator[TestClient[Litestar]]:
    with TestClient(app=app) as test_client:
        complete_setup(test_client)
        yield test_client


async def test_api_list_backlog_and_detail(
    api_client: TestClient[Litestar], session: AsyncSession
) -> None:
    instance_id = await _seed_instance(session)
    service = IntentsService(session)
    intent, _ = await service.upsert(
        _episode_seed(instance_id, priority=3, trace=TRACE)
    )
    _ = await service.transition(
        intent, IntentState.ELIGIBLE, actor="reconciler", reason="grace passed"
    )

    listed = json_obj(api_client.get("/api/v1/intents"))
    assert listed["total"] == 1
    assert listed["limit"] == 50
    assert listed["offset"] == 0
    item = as_obj(as_list(listed["items"])[0])
    assert item["state"] == "eligible"
    assert item["mediaType"] == "episode"
    assert item["displayTitle"] == "Alpha Show"
    assert "profile *Anime*" in str(item["traceRendered"])

    backlog = json_obj(api_client.get("/api/v1/intents/backlog"))
    assert backlog["total"] == 1
    in_flight = json_obj(api_client.get("/api/v1/intents/in-flight"))
    assert in_flight["total"] == 0

    filtered = json_obj(api_client.get("/api/v1/intents?states=superseded"))
    assert filtered["total"] == 0
    bad_state = api_client.get("/api/v1/intents?states=bogus")
    assert bad_state.status_code == 422

    detail = json_obj(api_client.get(f"/api/v1/intents/{intent.id}"))
    intent_body = as_obj(detail["intent"])
    assert intent_body["id"] == str(intent.id)
    steps = as_list(detail["traceSteps"])
    assert steps[0] == "profile *Anime*"
    events = as_list(detail["events"])
    assert len(events) == 2
    first_event = as_obj(events[0])
    assert first_event["fromState"] is None
    assert first_event["toState"] == "discovered"

    missing = api_client.get(f"/api/v1/intents/{uuid4()}")
    assert missing.status_code == 404


def test_api_pagination_bounds_enforced(api_client: TestClient[Litestar]) -> None:
    # Regression: Parameter(ge/le) metadata hidden in PEP 695 `type` aliases is
    # invisible to Litestar's signature model, silently disabling these bounds.
    for path in (
        "/api/v1/intents",
        "/api/v1/intents/backlog",
        "/api/v1/intents/in-flight",
    ):
        # 400 = Litestar's own query-param validation (as in plan-preview's
        # test); 422 is reserved for domain validation errors.
        assert api_client.get(f"{path}?limit=0").status_code == 400
        assert api_client.get(f"{path}?limit=501").status_code == 400
        assert api_client.get(f"{path}?offset=-1").status_code == 400
        assert api_client.get(f"{path}?limit=500&offset=0").status_code == 200


def test_api_requires_auth(app: Litestar) -> None:
    with TestClient(app=app) as anonymous:
        complete_setup(anonymous)
        anonymous.cookies.clear()
        response = anonymous.get("/api/v1/intents")
        assert response.status_code == 401
