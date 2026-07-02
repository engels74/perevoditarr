"""Notifications domain service (P3-T5, FR-X1): Apprise fan-out with coalescing.

Routes carry encrypted Apprise URLs; the service decrypts only to send and never
returns/logs plaintext (FR-A5). `notify` fans a message out to every enabled
route subscribed to its event, suppressing per-(route, event) storms via the
coalescer. The digest job summarizes the last day's outcomes. The actual send is
an injectable seam so tests exercise routing/coalescing without the network.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import apprise
from advanced_alchemy.exceptions import NotFoundError as AANotFoundError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from msgspec import UNSET
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import ConflictError, DomainValidationError, NotFoundError
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.dispatch.estimation import (
    HEURISTIC_EPISODE_CHARACTERS,
    HEURISTIC_MOVIE_CHARACTERS,
)
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.state_machine import IntentState
from perevoditarr.modules.notifications.coalescer import NotificationCoalescer
from perevoditarr.modules.notifications.events import NotificationMessage
from perevoditarr.modules.notifications.models import NotificationRoute
from perevoditarr.modules.notifications.schemas import (
    DigestResult,
    NotificationRouteCreate,
    NotificationRouteRead,
    NotificationRouteUpdate,
    TestFireResult,
    mask_url,
)

type NotificationSender = Callable[[str, str, str, str], Awaitable[bool]]

DEFAULT_COALESCE_WINDOW_SECONDS = 300


async def apprise_send(url: str, title: str, body: str, notify_type: str) -> bool:
    """Real send: one Apprise target per route. Returns False on an invalid URL
    or a delivery failure so the caller never treats it as sent."""
    client = apprise.Apprise()
    if not client.add(url):  # pyright: ignore[reportUnknownMemberType]  # apprise is untyped
        return False
    result = await client.async_notify(body=body, title=title, notify_type=notify_type)
    return bool(result)


def _is_valid_apprise_url(url: str) -> bool:
    return bool(apprise.Apprise().add(url))  # pyright: ignore[reportUnknownMemberType]  # apprise is untyped


class NotificationRouteRepository(SQLAlchemyAsyncRepository[NotificationRoute]):
    model_type: type[NotificationRoute] = NotificationRoute


class NotificationsService:
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        coalescer: NotificationCoalescer,
        *,
        window_seconds: int = DEFAULT_COALESCE_WINDOW_SECONDS,
        sender: NotificationSender = apprise_send,
    ) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box
        self.coalescer: NotificationCoalescer = coalescer
        self.window_seconds: int = window_seconds
        self.sender: NotificationSender = sender
        self.routes: NotificationRouteRepository = NotificationRouteRepository(
            session=session
        )

    def _read(self, row: NotificationRoute) -> NotificationRouteRead:
        return NotificationRouteRead(
            id=row.id,
            name=row.name,
            enabled=row.enabled,
            events=list(row.events) if row.events else [],
            url_masked=mask_url(self.secret_box.decrypt_text(row.url_encrypted)),
            created_at=row.created_at,
        )

    # ------------------------------------------------------------ CRUD

    async def list_routes(self) -> list[NotificationRouteRead]:
        rows = await self.routes.list(order_by=[("name", False)])
        return [self._read(row) for row in rows]

    async def create_route(
        self, data: NotificationRouteCreate
    ) -> NotificationRouteRead:
        if not _is_valid_apprise_url(data.url):
            raise DomainValidationError("not a valid Apprise URL")
        await self._ensure_unique_name(data.name)
        row = NotificationRoute(
            name=data.name,
            url_encrypted=self.secret_box.encrypt_text(data.url),
            enabled=data.enabled,
            events=list(data.events),
        )
        self.session.add(row)
        await self.session.commit()
        return self._read(row)

    async def update_route(
        self, route_id: UUID, data: NotificationRouteUpdate
    ) -> NotificationRouteRead:
        row = await self._get(route_id)
        if data.name is not UNSET and data.name != row.name:
            await self._ensure_unique_name(data.name)
            row.name = data.name
        if data.url is not UNSET:
            if not _is_valid_apprise_url(data.url):
                raise DomainValidationError("not a valid Apprise URL")
            row.url_encrypted = self.secret_box.encrypt_text(data.url)
        if data.enabled is not UNSET:
            row.enabled = data.enabled
        if data.events is not UNSET:
            row.events = list(data.events)
        await self.session.commit()
        return self._read(row)

    async def delete_route(self, route_id: UUID) -> None:
        _ = await self._get(route_id)
        _ = await self.routes.delete(route_id)
        await self.session.commit()

    async def _get(self, route_id: UUID) -> NotificationRoute:
        try:
            return await self.routes.get(route_id)
        except AANotFoundError as error:
            raise NotFoundError(f"notification route {route_id} not found") from error

    async def _ensure_unique_name(self, name: str) -> None:
        existing = (
            await self.session.scalars(
                select(NotificationRoute.id).where(NotificationRoute.name == name)
            )
        ).first()
        if existing is not None:
            raise ConflictError(f"a route named {name!r} already exists")

    # ------------------------------------------------------------ send

    async def notify(
        self, message: NotificationMessage, *, now: datetime | None = None
    ) -> int:
        """Fan out to enabled routes subscribed to the event, coalescing per
        (route, event). Returns the number of routes actually sent to."""
        moment = now if now is not None else datetime.now(UTC)
        sent = 0
        for row in await self._subscribed_routes(message.event):
            if not self.coalescer.should_send(
                row.id, message.event, now=moment, window_seconds=self.window_seconds
            ):
                continue
            if await self.sender(
                self.secret_box.decrypt_text(row.url_encrypted),
                message.title,
                message.body,
                message.notify_type,
            ):
                sent += 1
        return sent

    async def _subscribed_routes(self, event: str) -> list[NotificationRoute]:
        rows = await self.routes.list()
        return [row for row in rows if row.enabled and event in (row.events or [])]

    async def test_fire(self, route_id: UUID) -> TestFireResult:
        row = await self._get(route_id)
        sent = await self.sender(
            self.secret_box.decrypt_text(row.url_encrypted),
            "Perevoditarr test notification",
            "If you can read this, this route is configured correctly.",
            "info",
        )
        return TestFireResult(
            route_id=route_id,
            sent=sent,
            detail="delivered" if sent else "delivery failed — check the route URL",
        )

    async def send_digest(self, *, now: datetime | None = None) -> DigestResult:
        moment = now if now is not None else datetime.now(UTC)
        since = moment - timedelta(days=1)
        counts = await self._outcome_counts(since)
        characters = await self._converged_characters(since)
        body = (
            f"Last 24h: {counts['converged']} converged, "
            f"{counts['superseded']} superseded, {counts['failed']} failed.\n"
            f"Estimated translated volume: {characters:,} characters."
        )
        message = NotificationMessage(
            event="daily_digest", title="Perevoditarr daily digest", body=body
        )
        # Digest is scheduled (daily) and must not be swallowed by coalescing.
        routes_notified = 0
        for row in await self._subscribed_routes("daily_digest"):
            if await self.sender(
                self.secret_box.decrypt_text(row.url_encrypted),
                message.title,
                message.body,
                message.notify_type,
            ):
                routes_notified += 1
        return DigestResult(
            generated_at=moment,
            routes_notified=routes_notified,
            converged=counts["converged"],
            superseded=counts["superseded"],
            failed=counts["failed"],
            estimated_characters=characters,
        )

    async def _outcome_counts(self, since: datetime) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(IntentEvent.to_state, func.count())
                .where(
                    IntentEvent.created_at >= since,
                    IntentEvent.to_state.in_(
                        (
                            IntentState.CONVERGED.value,
                            IntentState.SUPERSEDED.value,
                            IntentState.FAILED.value,
                        )
                    ),
                )
                .group_by(IntentEvent.to_state)
            )
        ).tuples()
        counts = {"converged": 0, "superseded": 0, "failed": 0}
        for state, count in rows:
            counts[str(state)] = int(count)
        return counts

    async def _converged_characters(self, since: datetime) -> int:
        rows = (
            await self.session.execute(
                select(Intent.media_type, func.count())
                .select_from(IntentEvent)
                .join(Intent, IntentEvent.intent_id == Intent.id)
                .where(
                    IntentEvent.created_at >= since,
                    IntentEvent.to_state == IntentState.CONVERGED.value,
                )
                .group_by(Intent.media_type)
            )
        ).tuples()
        total = 0
        for media_type, count in rows:
            per = (
                HEURISTIC_EPISODE_CHARACTERS
                if media_type == "episode"
                else HEURISTIC_MOVIE_CHARACTERS
            )
            total += per * int(count)
        return total
