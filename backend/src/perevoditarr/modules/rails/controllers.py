"""Rails API (P3-T1, FR-Q3): status gauges + pause/resume + window config.

Read endpoints feed the dashboard/queue gauges; the pause/resume and window
mutations persist rail posture (global or per-instance). Dispatch happens in
the background loop (P3-T2); nothing here writes toward the ecosystem.
"""

from collections.abc import Sequence
from uuid import UUID

from litestar import Controller, get, post, put
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.sse import SseBus
from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.instances import InstanceGateway
from perevoditarr.modules.rails.schemas import (
    PauseRequest,
    RailsOverview,
    RailStatusDto,
    WindowKUpdate,
    WindowsUpdate,
    window_from_input,
)
from perevoditarr.modules.rails.service import RailsService


async def provide_rails_service(
    db_session: AsyncSession,
    auth_runtime: AuthRuntime,
    gateway: InstanceGateway,
    sse_bus: SseBus,
) -> RailsService:
    return RailsService(db_session, auth_runtime.secret_box, gateway, sse_bus)


class RailsController(Controller):
    path: str = "/rails"
    tags: Sequence[str] | None = ("rails",)

    @get("/status", operation_id="getRailsOverview")
    async def overview(self, rails_service: RailsService) -> RailsOverview:
        return await rails_service.overview()

    @post("/pause", operation_id="pauseRailsGlobal")
    async def pause_global(
        self, rails_service: RailsService, data: PauseRequest
    ) -> RailStatusDto:
        return await rails_service.pause(None, reason=data.reason)

    @post("/resume", operation_id="resumeRailsGlobal")
    async def resume_global(self, rails_service: RailsService) -> RailStatusDto:
        return await rails_service.resume(None)

    @put("/windows", operation_id="setRailsWindowsGlobal")
    async def set_global_windows(
        self, rails_service: RailsService, data: WindowsUpdate
    ) -> RailStatusDto:
        return await rails_service.set_windows(
            None, [window_from_input(window) for window in data.windows]
        )

    @get("/{bazarr_instance_id:uuid}", operation_id="getInstanceRails")
    async def instance_status(
        self, bazarr_instance_id: UUID, rails_service: RailsService
    ) -> RailStatusDto:
        return await rails_service.status(bazarr_instance_id)

    @post("/{bazarr_instance_id:uuid}/pause", operation_id="pauseInstanceRails")
    async def pause_instance(
        self,
        bazarr_instance_id: UUID,
        rails_service: RailsService,
        data: PauseRequest,
    ) -> RailStatusDto:
        return await rails_service.pause(bazarr_instance_id, reason=data.reason)

    @post("/{bazarr_instance_id:uuid}/resume", operation_id="resumeInstanceRails")
    async def resume_instance(
        self, bazarr_instance_id: UUID, rails_service: RailsService
    ) -> RailStatusDto:
        return await rails_service.resume(bazarr_instance_id)

    @put("/{bazarr_instance_id:uuid}/windows", operation_id="setInstanceRailsWindows")
    async def set_instance_windows(
        self,
        bazarr_instance_id: UUID,
        rails_service: RailsService,
        data: WindowsUpdate,
    ) -> RailStatusDto:
        return await rails_service.set_windows(
            bazarr_instance_id, [window_from_input(window) for window in data.windows]
        )

    @post("/{bazarr_instance_id:uuid}/activate", operation_id="activateInstanceRails")
    async def activate_instance(
        self, bazarr_instance_id: UUID, rails_service: RailsService
    ) -> RailStatusDto:
        return await rails_service.set_activation(bazarr_instance_id, active=True)

    @post(
        "/{bazarr_instance_id:uuid}/deactivate",
        operation_id="deactivateInstanceRails",
    )
    async def deactivate_instance(
        self, bazarr_instance_id: UUID, rails_service: RailsService
    ) -> RailStatusDto:
        return await rails_service.set_activation(bazarr_instance_id, active=False)

    @put("/{bazarr_instance_id:uuid}/window-k", operation_id="setInstanceWindowK")
    async def set_instance_window_k(
        self,
        bazarr_instance_id: UUID,
        rails_service: RailsService,
        data: WindowKUpdate,
    ) -> RailStatusDto:
        return await rails_service.set_window_k(bazarr_instance_id, data.window_k)
