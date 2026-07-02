"""Plan-preview API (P2-T5): the primary Observe-mode surface (FR-U3).

Read-only — the dispatcher itself arrives with Phase 3. `GET /plan/preview`
answers "what would run next, and why" with explained verdicts and cost
estimates; nothing here writes toward the ecosystem.
"""

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from litestar import Controller, get
from litestar.params import Parameter
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.dispatch.schemas import PlanPreviewResponse
from perevoditarr.modules.dispatch.service import PlanPreviewService
from perevoditarr.modules.instances.gateway import InstanceGateway

# NB: inline Annotated below, not a PEP 695 alias — lazy alias resolution
# hides Parameter constraints from Litestar's signature model (no 400 on
# violation).


async def provide_plan_preview_service(
    db_session: AsyncSession, auth_runtime: AuthRuntime, gateway: InstanceGateway
) -> PlanPreviewService:
    return PlanPreviewService(db_session, auth_runtime.secret_box, gateway)


class DispatchController(Controller):
    path: str = "/plan"
    tags: Sequence[str] | None = ("plan",)

    @get("/preview", operation_id="getPlanPreview")
    async def preview(
        self,
        plan_preview_service: PlanPreviewService,
        bazarr_instance_id: UUID | None = None,
        limit: Annotated[int, Parameter(ge=1, le=100)] = 20,
    ) -> PlanPreviewResponse:
        return await plan_preview_service.preview(
            limit=limit, bazarr_instance_id=bazarr_instance_id
        )
