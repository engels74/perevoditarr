"""Doctor API controllers (P1-T6)."""

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from litestar import Controller, get, post
from litestar.params import Parameter
from litestar.status_codes import HTTP_200_OK
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.sse import SseBus
from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.doctor.schemas import DoctorRunRead
from perevoditarr.modules.doctor.service import DoctorService
from perevoditarr.modules.instances import InstanceGateway


async def provide_doctor_service(
    db_session: AsyncSession,
    auth_runtime: AuthRuntime,
    gateway: InstanceGateway,
    sse_bus: SseBus,
) -> DoctorService:
    forward = auth_runtime.forward_auth
    return DoctorService(
        db_session,
        auth_runtime.secret_box,
        gateway,
        sse_bus,
        forward_auth_misconfigured=(
            forward is not None
            and forward.enabled
            and not auth_runtime.trusted_networks
        ),
    )


class DoctorController(Controller):
    path: str = "/doctor"
    tags: Sequence[str] | None = ("doctor",)

    @post("/run", status_code=HTTP_200_OK, operation_id="runDoctor")
    async def run(self, doctor_service: DoctorService) -> DoctorRunRead:
        return await doctor_service.run("manual")

    @get("/latest", operation_id="getLatestDoctorRun")
    async def latest(
        self,
        doctor_service: DoctorService,
        bazarr_instance_id: Annotated[
            UUID | None, Parameter(query="bazarrInstanceId")
        ] = None,
    ) -> DoctorRunRead | None:
        return await doctor_service.latest(bazarr_instance_id=bazarr_instance_id)
