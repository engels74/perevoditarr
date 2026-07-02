"""Notifications service integration (P3-T5, FR-X1): route CRUD with URL
masking, event routing + coalescing, test-fire, and the daily digest — driven
with a recording sender so no network is touched."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.db import metadata
from perevoditarr.core.errors import DomainValidationError
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.notifications.coalescer import NotificationCoalescer
from perevoditarr.modules.notifications.events import NotificationMessage
from perevoditarr.modules.notifications.schemas import (
    NotificationRouteCreate,
    NotificationRouteUpdate,
)
from perevoditarr.modules.notifications.service import NotificationsService
from tests.conftest import TEST_SECRET

SECRET = SecretBox(TEST_SECRET)
VALID_URL = "json://localhost"


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    async def __call__(self, url: str, title: str, body: str, notify_type: str) -> bool:
        self.calls.append((url, title, body, notify_type))
        return True


@pytest.fixture
async def session(app_settings: AppSettings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


def _service(
    session: AsyncSession, sender: RecordingSender, *, window: int = 300
) -> NotificationsService:
    return NotificationsService(
        session,
        SECRET,
        NotificationCoalescer(),
        window_seconds=window,
        sender=sender,
    )


async def test_create_masks_url_and_rejects_invalid(session: AsyncSession) -> None:
    service = _service(session, RecordingSender())
    route = await service.create_route(
        NotificationRouteCreate(name="ops", url=VALID_URL, events=["breaker_tripped"])
    )
    assert route.url_masked == "json://***"
    assert route.events == ["breaker_tripped"]

    with pytest.raises(DomainValidationError):
        _ = await service.create_route(
            NotificationRouteCreate(name="bad", url="not-a-valid-url")
        )


async def test_notify_routes_by_subscription_and_coalesces(
    session: AsyncSession,
) -> None:
    sender = RecordingSender()
    service = _service(session, sender, window=300)
    _ = await service.create_route(
        NotificationRouteCreate(name="ops", url=VALID_URL, events=["breaker_tripped"])
    )
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    message = NotificationMessage(event="breaker_tripped", title="t", body="b")

    assert await service.notify(message, now=now) == 1
    # Coalesced within the window.
    assert await service.notify(message, now=now + timedelta(seconds=10)) == 0
    # Allowed again after the window.
    assert await service.notify(message, now=now + timedelta(seconds=400)) == 1
    # An event no route subscribes to reaches nobody.
    other = NotificationMessage(event="cap_reached", title="t", body="b")
    assert await service.notify(other, now=now) == 0
    assert len(sender.calls) == 2


async def test_disabled_route_receives_nothing(session: AsyncSession) -> None:
    sender = RecordingSender()
    service = _service(session, sender)
    route = await service.create_route(
        NotificationRouteCreate(name="ops", url=VALID_URL, events=["breaker_tripped"])
    )
    _ = await service.update_route(route.id, NotificationRouteUpdate(enabled=False))
    assert (
        await service.notify(
            NotificationMessage(event="breaker_tripped", title="t", body="b")
        )
        == 0
    )
    assert sender.calls == []


async def test_test_fire_sends_immediately(session: AsyncSession) -> None:
    sender = RecordingSender()
    service = _service(session, sender)
    route = await service.create_route(
        NotificationRouteCreate(name="ops", url=VALID_URL, events=[])
    )
    result = await service.test_fire(route.id)
    assert result.sent is True
    assert len(sender.calls) == 1


async def test_digest_summarizes_recent_outcomes(session: AsyncSession) -> None:
    sender = RecordingSender()
    service = _service(session, sender)
    _ = await service.create_route(
        NotificationRouteCreate(name="digest", url=VALID_URL, events=["daily_digest"])
    )
    instance = BazarrInstance(
        name="main",
        url="http://bazarr.test",
        api_key_encrypted=SECRET.encrypt_text("k"),
    )
    session.add(instance)
    await session.flush()
    await _outcome(
        session, instance.id, ext_id=1, to_state="converged", media_type="episode"
    )
    await _outcome(
        session, instance.id, ext_id=2, to_state="converged", media_type="movie"
    )
    await _outcome(
        session, instance.id, ext_id=3, to_state="failed", media_type="episode"
    )

    result = await service.send_digest()
    assert result.routes_notified == 1
    assert result.converged == 2
    assert result.failed == 1
    assert result.estimated_characters > 0
    assert len(sender.calls) == 1


async def _outcome(
    session: AsyncSession,
    instance_id: UUID,
    *,
    ext_id: int,
    to_state: str,
    media_type: str,
) -> None:
    intent = Intent(
        bazarr_instance_id=instance_id,
        media_type=media_type,
        external_media_id=ext_id,
        sonarr_series_id=ext_id if media_type == "episode" else None,
        display_title="X",
        source_language="en",
        target_language="da",
        state=to_state,
    )
    session.add(intent)
    await session.flush()
    session.add(
        IntentEvent(
            intent_id=intent.id,
            actor="verification",
            from_state="dispatched",
            to_state=to_state,
            reason="x",
        )
    )
    await session.flush()
