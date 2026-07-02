"""Rails service + API integration (P3-T1): usage counted from the durable
dispatch audit trail (restart-safe), pause/resume, breaker record with SSE, and
the dashboard overview endpoint."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import override
from uuid import UUID

import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient
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
from perevoditarr.modules.instances import InstanceGateway
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.policy.models import Preset
from perevoditarr.modules.policy.schemas import RailSettingsDto
from perevoditarr.modules.rails.evaluation import RailAllowed, RailBlocked
from perevoditarr.modules.rails.service import RailsService
from tests.conftest import TEST_SECRET, complete_setup, csrf_headers
from tests.support import as_obj, json_obj

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


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


def _json(value: msgspec.Struct) -> dict[str, object]:
    return msgspec.json.decode(msgspec.json.encode(value), type=dict[str, object])


def _service(session: AsyncSession, bus: SseBus | None = None) -> RailsService:
    gateway = InstanceGateway(HttpClientRegistry())
    return RailsService(
        session, SecretBox(TEST_SECRET), gateway, bus if bus is not None else SseBus()
    )


async def _seed_instance(session: AsyncSession, rails: RailSettingsDto) -> UUID:
    instance = BazarrInstance(
        name="main",
        url="http://bazarr.test",
        api_key_encrypted=SecretBox(TEST_SECRET).encrypt_text("k"),
    )
    session.add(instance)
    session.add(Preset(name="Active", built_in=False, active=True, rails=_json(rails)))
    await session.flush()
    return instance.id


async def _dispatched(
    session: AsyncSession,
    instance_id: UUID,
    *,
    media_type: str = "episode",
    at: datetime,
    external_media_id: int,
) -> None:
    intent = Intent(
        bazarr_instance_id=instance_id,
        media_type=media_type,
        external_media_id=external_media_id,
        sonarr_series_id=external_media_id if media_type == "episode" else None,
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
            created_at=at,
        )
    )
    await session.flush()


async def test_usage_counted_from_dispatch_events_with_rollover(
    session: AsyncSession,
) -> None:
    instance_id = await _seed_instance(session, RailSettingsDto(hourly_cap=2))
    # One dispatch within the hour, one two hours ago: hour=1, day=2.
    await _dispatched(session, instance_id, at=NOW, external_media_id=1)
    await _dispatched(
        session, instance_id, at=NOW - timedelta(hours=2), external_media_id=2
    )
    service = _service(session)
    verdict = await service.evaluate(instance_id, candidate_characters=0, now=NOW)
    assert isinstance(verdict, RailAllowed)  # hour count 1 < cap 2

    status = await service.status(instance_id, now=NOW)
    hourly = next(cap for cap in status.caps if cap.period == "hourly")
    daily = next(cap for cap in status.caps if cap.period == "daily")
    assert hourly.used == 1
    assert daily.used == 2


async def test_hourly_cap_blocks_dispatch(session: AsyncSession) -> None:
    instance_id = await _seed_instance(session, RailSettingsDto(hourly_cap=1))
    await _dispatched(session, instance_id, at=NOW, external_media_id=1)
    verdict = await _service(session).evaluate(
        instance_id, candidate_characters=0, now=NOW
    )
    assert isinstance(verdict, RailBlocked)
    assert verdict.rail == "cap_hourly"


async def test_pause_and_resume(session: AsyncSession) -> None:
    instance_id = await _seed_instance(session, RailSettingsDto())
    service = _service(session)
    _ = await service.pause(instance_id, reason="maintenance")
    blocked = await service.evaluate(instance_id, candidate_characters=0, now=NOW)
    assert isinstance(blocked, RailBlocked)
    assert blocked.rail == "pause"
    _ = await service.resume(instance_id)
    allowed = await service.evaluate(instance_id, candidate_characters=0, now=NOW)
    assert isinstance(allowed, RailAllowed)


async def test_global_pause_blocks_every_instance(session: AsyncSession) -> None:
    instance_id = await _seed_instance(session, RailSettingsDto())
    service = _service(session)
    _ = await service.pause(None, reason="fleet freeze")
    blocked = await service.evaluate(instance_id, candidate_characters=0, now=NOW)
    assert isinstance(blocked, RailBlocked)
    assert blocked.rail == "pause"


async def test_breaker_trips_and_emits_event(session: AsyncSession) -> None:
    instance_id = await _seed_instance(
        session, RailSettingsDto(breaker_failure_threshold=2, breaker_probe_minutes=15)
    )
    bus = RecordingBus()
    service = _service(session, bus)
    first = await service.record_dispatch_result(instance_id, success=False, now=NOW)
    assert first.to_state == "closed"
    second = await service.record_dispatch_result(instance_id, success=False, now=NOW)
    assert second.tripped is True
    assert any(topic == "rails.breaker" for topic, _ in bus.events)

    blocked = await service.evaluate(instance_id, candidate_characters=0, now=NOW)
    assert isinstance(blocked, RailBlocked)
    assert blocked.rail == "breaker"

    # A later success closes it again.
    healed = await service.record_dispatch_result(
        instance_id, success=True, now=NOW + timedelta(hours=1)
    )
    assert healed.closed is True
    allowed = await service.evaluate(
        instance_id, candidate_characters=0, now=NOW + timedelta(hours=1)
    )
    assert isinstance(allowed, RailAllowed)


async def test_scheduling_window_blocks_outside_hours(session: AsyncSession) -> None:
    from perevoditarr.modules.rails.windows import SchedulingWindow

    instance_id = await _seed_instance(session, RailSettingsDto())
    service = _service(session)
    _ = await service.set_windows(
        instance_id, [SchedulingWindow(start="00:00", end="06:00", timezone="UTC")]
    )
    # NOW is 12:00 UTC — outside the 00:00-06:00 window.
    blocked = await service.evaluate(instance_id, candidate_characters=0, now=NOW)
    assert isinstance(blocked, RailBlocked)
    assert blocked.rail == "window"


async def test_rails_overview_endpoint(client: TestClient[Litestar]) -> None:
    complete_setup(client)
    response = client.get("/api/v1/rails/status")
    assert response.status_code == 200, response.text
    body = json_obj(response)
    global_rails = as_obj(body["globalRails"])
    assert global_rails["scope"] == "global"
    assert global_rails["paused"] is False
    assert isinstance(body["instances"], list)


async def test_rails_pause_endpoint(client: TestClient[Litestar]) -> None:
    complete_setup(client)
    response = client.post(
        "/api/v1/rails/pause",
        json={"reason": "manual"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    assert json_obj(response)["paused"] is True
    resumed = client.post("/api/v1/rails/resume", headers=csrf_headers(client))
    assert resumed.status_code == 201, resumed.text
    assert json_obj(resumed)["paused"] is False
