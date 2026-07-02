"""Notifications API (P3-T5, FR-X1): route CRUD, test-fire, on-demand digest.

The coalescer is a process singleton shared with the background forwarders
(rails breaker, quarantine, doctor) — injected here as a cached dependency.
"""

from collections.abc import Sequence
from uuid import UUID

from litestar import Controller, delete, get, patch, post
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.notifications.coalescer import NotificationCoalescer
from perevoditarr.modules.notifications.schemas import (
    DigestResult,
    NotificationRouteCreate,
    NotificationRouteRead,
    NotificationRouteUpdate,
    TestFireResult,
)
from perevoditarr.modules.notifications.service import NotificationsService


async def provide_notifications_service(
    db_session: AsyncSession,
    auth_runtime: AuthRuntime,
    notification_coalescer: NotificationCoalescer,
) -> NotificationsService:
    return NotificationsService(
        db_session, auth_runtime.secret_box, notification_coalescer
    )


class NotificationsController(Controller):
    path: str = "/notifications"
    tags: Sequence[str] | None = ("notifications",)

    @get("/routes", operation_id="listNotificationRoutes")
    async def list_routes(
        self, notifications_service: NotificationsService
    ) -> list[NotificationRouteRead]:
        return await notifications_service.list_routes()

    @post("/routes", operation_id="createNotificationRoute")
    async def create_route(
        self,
        notifications_service: NotificationsService,
        data: NotificationRouteCreate,
    ) -> NotificationRouteRead:
        return await notifications_service.create_route(data)

    @patch("/routes/{route_id:uuid}", operation_id="updateNotificationRoute")
    async def update_route(
        self,
        route_id: UUID,
        notifications_service: NotificationsService,
        data: NotificationRouteUpdate,
    ) -> NotificationRouteRead:
        return await notifications_service.update_route(route_id, data)

    @delete("/routes/{route_id:uuid}", operation_id="deleteNotificationRoute")
    async def delete_route(
        self, route_id: UUID, notifications_service: NotificationsService
    ) -> None:
        await notifications_service.delete_route(route_id)

    @post("/routes/{route_id:uuid}/test", operation_id="testNotificationRoute")
    async def test_route(
        self, route_id: UUID, notifications_service: NotificationsService
    ) -> TestFireResult:
        return await notifications_service.test_fire(route_id)

    @post("/digest", operation_id="sendNotificationDigest")
    async def send_digest(
        self, notifications_service: NotificationsService
    ) -> DigestResult:
        return await notifications_service.send_digest()
