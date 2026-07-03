"""Watch-integration controller (P5-T1): admin CRUD + test + refresh.

Reads are open to any authenticated user (viewers included); every mutation is
admin-only via require_admin (defense in depth on top of the router role guard).
"""

from collections.abc import Sequence
from uuid import UUID

from litestar import Controller, delete, get, patch, post
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.auth.security import AuthRuntime, require_admin
from perevoditarr.modules.watch.gateway import WatchGateway
from perevoditarr.modules.watch.schemas import (
    WatchRefreshResult,
    WatchSourceCreate,
    WatchSourceRead,
    WatchSourceTestRequest,
    WatchSourceTestResult,
    WatchSourceUpdate,
)
from perevoditarr.modules.watch.service import WatchService, watch_source_read


async def provide_watch_service(
    db_session: AsyncSession, auth_runtime: AuthRuntime, watch_gateway: WatchGateway
) -> WatchService:
    return WatchService(db_session, auth_runtime.secret_box, watch_gateway)


class WatchController(Controller):
    path: str = "/watch"
    tags: Sequence[str] | None = ("watch",)

    @get("/sources", operation_id="listWatchSources")
    async def list_sources(self, watch_service: WatchService) -> list[WatchSourceRead]:
        return [watch_source_read(row) for row in await watch_service.list_sources()]

    @post("/sources", guards=[require_admin], operation_id="createWatchSource")
    async def create_source(
        self, data: WatchSourceCreate, watch_service: WatchService
    ) -> WatchSourceRead:
        return watch_source_read(await watch_service.create_source(data))

    @patch(
        "/sources/{source_id:uuid}",
        guards=[require_admin],
        operation_id="updateWatchSource",
    )
    async def update_source(
        self, source_id: UUID, data: WatchSourceUpdate, watch_service: WatchService
    ) -> WatchSourceRead:
        return watch_source_read(await watch_service.update_source(source_id, data))

    @delete(
        "/sources/{source_id:uuid}",
        guards=[require_admin],
        operation_id="deleteWatchSource",
    )
    async def delete_source(self, source_id: UUID, watch_service: WatchService) -> None:
        await watch_service.delete_source(source_id)

    @post("/sources/test", guards=[require_admin], operation_id="testWatchSource")
    async def test_source(
        self, data: WatchSourceTestRequest, watch_service: WatchService
    ) -> WatchSourceTestResult:
        return await watch_service.test_config(
            source_type=data.source_type,
            url=data.url,
            credential=data.credential,
            config=data.config,
        )

    @post(
        "/sources/{source_id:uuid}/health",
        guards=[require_admin],
        operation_id="checkWatchSourceHealth",
    )
    async def check_health(
        self, source_id: UUID, watch_service: WatchService
    ) -> WatchSourceRead:
        return watch_source_read(await watch_service.check_health(source_id))

    @post("/refresh", guards=[require_admin], operation_id="refreshWatchScores")
    async def refresh(
        self, watch_service: WatchService, app_settings: AppSettings
    ) -> WatchRefreshResult:
        return await watch_service.refresh(
            window_days=app_settings.watch_recent_window_days,
            frequent_min_plays=app_settings.watch_frequent_min_plays,
            activity_limit=app_settings.watch_activity_limit,
        )
