"""Telemetry API (P3-T4): stream-health snapshot for the UI degradation
indicator. Read-only; the live streams themselves run in the app lifespan."""

from collections.abc import Sequence
from datetime import UTC, datetime

from litestar import Controller, get
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.security import SecretBox
from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.instances import InstancesService
from perevoditarr.modules.telemetry.health import TelemetryHealthRegistry
from perevoditarr.modules.telemetry.schemas import (
    InstanceTelemetryDto,
    TelemetryHealthResponse,
    stream_dto,
)


class TelemetryHealthService:
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        health: TelemetryHealthRegistry,
    ) -> None:
        self.instances: InstancesService = InstancesService(session, secret_box)
        self.health: TelemetryHealthRegistry = health

    async def overview(self) -> TelemetryHealthResponse:
        rows: list[InstanceTelemetryDto] = []
        for instance in await self.instances.list_bazarr():
            if not instance.enabled:
                continue
            streams = [
                stream_dto(
                    "bazarr_socketio",
                    self.health.get(instance.id, "bazarr_socketio"),
                )
            ]
            if instance.lingarr_instance_id is not None:
                streams.append(
                    stream_dto(
                        "lingarr_signalr",
                        self.health.get(instance.id, "lingarr_signalr"),
                    )
                )
            rows.append(
                InstanceTelemetryDto(
                    bazarr_instance_id=instance.id,
                    instance_name=instance.name,
                    streams=streams,
                )
            )
        return TelemetryHealthResponse(generated_at=datetime.now(UTC), instances=rows)


async def provide_telemetry_health_service(
    db_session: AsyncSession,
    auth_runtime: AuthRuntime,
    telemetry_health: TelemetryHealthRegistry,
) -> TelemetryHealthService:
    return TelemetryHealthService(db_session, auth_runtime.secret_box, telemetry_health)


class TelemetryController(Controller):
    path: str = "/telemetry"
    tags: Sequence[str] | None = ("telemetry",)

    @get("/health", operation_id="getTelemetryHealth")
    async def health(
        self, telemetry_health_service: TelemetryHealthService
    ) -> TelemetryHealthResponse:
        return await telemetry_health_service.overview()
