"""Instances API controllers (P1-T4, FR-I1..I5)."""

import time
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from litestar import Controller, delete, get, patch, post
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import DomainValidationError, PerevoditarrError
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.instances.health import (
    check_bazarr_health,
    check_lingarr_health,
)
from perevoditarr.modules.instances.schemas import (
    BazarrCapabilities,
    BazarrInstanceCreate,
    BazarrInstanceRead,
    BazarrInstanceUpdate,
    ConnectionTestRequest,
    ConnectionTestResult,
    LingarrDiscoveryConfirm,
    LingarrDiscoveryResult,
    LingarrInstanceCreate,
    LingarrInstanceRead,
    LingarrInstanceUpdate,
)
from perevoditarr.modules.instances.service import (
    InstancesService,
    bazarr_read,
    lingarr_read,
)
from perevoditarr.modules.integrations.bazarr import (
    detect_capabilities,
)
from perevoditarr.modules.integrations.bazarr import (
    ensure_supported_version as ensure_bazarr_version,
)
from perevoditarr.modules.integrations.lingarr import (
    ensure_supported_version as ensure_lingarr_version,
)


async def provide_instances_service(
    db_session: AsyncSession, auth_runtime: AuthRuntime
) -> InstancesService:
    return InstancesService(db_session, auth_runtime.secret_box)


async def _probe_bazarr(
    gateway: InstanceGateway, url: str, api_key: str
) -> tuple[str, BazarrCapabilities]:
    """Connection test + version gate + capability probe (FR-I1)."""
    client = gateway.bazarr(url.rstrip("/"), api_key)
    status = await client.system_status()
    _ = ensure_bazarr_version(status.bazarr_version)
    probe = detect_capabilities(status.bazarr_version)
    capabilities = BazarrCapabilities(
        translate_returns_job_id=probe.translate_returns_job_id,
        lingarr_receives_episode_id=probe.lingarr_receives_episode_id,
        probed_at=datetime.now(UTC),
    )
    return status.bazarr_version, capabilities


class InstancesController(Controller):
    path: str = "/instances"
    tags: Sequence[str] | None = ("instances",)

    # --- listing ----------------------------------------------------------

    @get("/bazarr", operation_id="listBazarrInstances")
    async def list_bazarr(
        self, instances_service: InstancesService
    ) -> list[BazarrInstanceRead]:
        return [bazarr_read(i) for i in await instances_service.list_bazarr()]

    @get("/lingarr", operation_id="listLingarrInstances")
    async def list_lingarr(
        self, instances_service: InstancesService
    ) -> list[LingarrInstanceRead]:
        return [lingarr_read(i) for i in await instances_service.list_lingarr()]

    # --- Bazarr CRUD (registration is version-gated, FR-I1) ---------------

    @post("/bazarr", operation_id="createBazarrInstance")
    async def create_bazarr(
        self,
        data: BazarrInstanceCreate,
        instances_service: InstancesService,
        gateway: InstanceGateway,
    ) -> BazarrInstanceRead:
        version, capabilities = await _probe_bazarr(gateway, data.url, data.api_key)
        instance = await instances_service.create_bazarr(
            data, version=version, capabilities=capabilities
        )
        return bazarr_read(instance)

    @patch("/bazarr/{instance_id:uuid}", operation_id="updateBazarrInstance")
    async def update_bazarr(
        self,
        instance_id: UUID,
        data: BazarrInstanceUpdate,
        instances_service: InstancesService,
    ) -> BazarrInstanceRead:
        return bazarr_read(await instances_service.update_bazarr(instance_id, data))

    @delete("/bazarr/{instance_id:uuid}", operation_id="deleteBazarrInstance")
    async def delete_bazarr(
        self, instance_id: UUID, instances_service: InstancesService
    ) -> None:
        await instances_service.delete_bazarr(instance_id)

    # --- Lingarr CRUD -----------------------------------------------------

    @post("/lingarr", operation_id="createLingarrInstance")
    async def create_lingarr(
        self,
        data: LingarrInstanceCreate,
        instances_service: InstancesService,
        gateway: InstanceGateway,
    ) -> LingarrInstanceRead:
        client = gateway.lingarr(data.url.rstrip("/"), data.api_key)
        info = await client.version()
        version = info.current_version
        if version is not None and not info.is_development:
            _ = ensure_lingarr_version(version)
        instance = await instances_service.create_lingarr(data, version=version)
        return lingarr_read(instance)

    @patch("/lingarr/{instance_id:uuid}", operation_id="updateLingarrInstance")
    async def update_lingarr(
        self,
        instance_id: UUID,
        data: LingarrInstanceUpdate,
        instances_service: InstancesService,
    ) -> LingarrInstanceRead:
        return lingarr_read(await instances_service.update_lingarr(instance_id, data))

    @delete("/lingarr/{instance_id:uuid}", operation_id="deleteLingarrInstance")
    async def delete_lingarr(
        self, instance_id: UUID, instances_service: InstancesService
    ) -> None:
        await instances_service.delete_lingarr(instance_id)

    # --- connection test (dry validation, nothing persisted) ---------------

    @post("/test", operation_id="testInstanceConnection")
    async def test_connection(
        self, data: ConnectionTestRequest, gateway: InstanceGateway
    ) -> ConnectionTestResult:
        started = time.monotonic()
        try:
            if data.kind == "bazarr":
                if not data.api_key:
                    raise DomainValidationError("apiKey is required for Bazarr")
                client = gateway.bazarr(data.url.rstrip("/"), data.api_key)
                status = await client.system_status()
                version = status.bazarr_version
                supported = True
                try:
                    _ = ensure_bazarr_version(version)
                except PerevoditarrError:
                    supported = False
            else:
                lingarr = gateway.lingarr(data.url.rstrip("/"), data.api_key)
                info = await lingarr.version()
                version = info.current_version
                supported = True
                if version is not None and not info.is_development:
                    try:
                        _ = ensure_lingarr_version(version)
                    except PerevoditarrError:
                        supported = False
        except DomainValidationError:
            raise
        except PerevoditarrError as error:
            return ConnectionTestResult(reachable=False, error=str(error))
        return ConnectionTestResult(
            reachable=True,
            version=version,
            version_supported=supported,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )

    # --- Lingarr auto-discovery from Bazarr settings (FR-I2) ---------------

    @get(
        "/bazarr/{instance_id:uuid}/lingarr-discovery",
        operation_id="discoverLingarr",
    )
    async def discover_lingarr(
        self,
        instance_id: UUID,
        instances_service: InstancesService,
        gateway: InstanceGateway,
    ) -> LingarrDiscoveryResult:
        instance = await instances_service.get_bazarr(instance_id)
        client = gateway.bazarr(
            instance.url, instances_service.bazarr_api_key(instance)
        )
        settings = await client.system_settings()
        translator = settings.translator
        if (
            translator is None
            or translator.translator_type != "lingarr"
            or not translator.lingarr_url
        ):
            return LingarrDiscoveryResult(configured=False)
        return LingarrDiscoveryResult(
            configured=True,
            url=translator.lingarr_url,
            has_api_key=bool(translator.lingarr_token),
        )

    @post(
        "/bazarr/{instance_id:uuid}/lingarr-discovery/confirm",
        operation_id="confirmLingarrDiscovery",
    )
    async def confirm_lingarr_discovery(
        self,
        instance_id: UUID,
        data: LingarrDiscoveryConfirm,
        instances_service: InstancesService,
        gateway: InstanceGateway,
    ) -> LingarrInstanceRead:
        instance = await instances_service.get_bazarr(instance_id)
        client = gateway.bazarr(
            instance.url, instances_service.bazarr_api_key(instance)
        )
        settings = await client.system_settings()
        translator = settings.translator
        if (
            translator is None
            or translator.translator_type != "lingarr"
            or not translator.lingarr_url
        ):
            raise DomainValidationError(
                "this Bazarr instance has no Lingarr configured (Settings → Subtitles → Translating)"
            )
        lingarr_client = gateway.lingarr(
            translator.lingarr_url.rstrip("/"), translator.lingarr_token or None
        )
        info = await lingarr_client.version()
        if info.current_version is not None and not info.is_development:
            _ = ensure_lingarr_version(info.current_version)
        lingarr = await instances_service.create_lingarr(
            LingarrInstanceCreate(
                name=data.name,
                url=translator.lingarr_url,
                api_key=translator.lingarr_token or None,
            ),
            version=info.current_version,
        )
        _ = await instances_service.update_bazarr(
            instance_id, BazarrInstanceUpdate(lingarr_instance_id=lingarr.id)
        )
        return lingarr_read(lingarr)

    # --- health -------------------------------------------------------------

    @post(
        "/bazarr/{instance_id:uuid}/health-check",
        operation_id="runBazarrHealthCheck",
    )
    async def bazarr_health_check(
        self,
        instance_id: UUID,
        instances_service: InstancesService,
        gateway: InstanceGateway,
        sse_bus: SseBus,
    ) -> BazarrInstanceRead:
        instance = await instances_service.get_bazarr(instance_id)
        health = await check_bazarr_health(
            gateway, instance.url, instances_service.bazarr_api_key(instance)
        )
        await instances_service.store_bazarr_snapshot(
            instance_id, health=health, version=health.version
        )
        sse_bus.publish(
            "instances.health",
            {"kind": "bazarr", "id": str(instance_id), "status": health.status},
        )
        return bazarr_read(await instances_service.get_bazarr(instance_id))

    @post(
        "/lingarr/{instance_id:uuid}/health-check",
        operation_id="runLingarrHealthCheck",
    )
    async def lingarr_health_check(
        self,
        instance_id: UUID,
        instances_service: InstancesService,
        gateway: InstanceGateway,
        sse_bus: SseBus,
    ) -> LingarrInstanceRead:
        instance = await instances_service.get_lingarr(instance_id)
        health = await check_lingarr_health(
            gateway, instance.url, instances_service.lingarr_api_key(instance)
        )
        await instances_service.store_lingarr_snapshot(
            instance_id, health=health, version=health.version
        )
        sse_bus.publish(
            "instances.health",
            {"kind": "lingarr", "id": str(instance_id), "status": health.status},
        )
        return lingarr_read(await instances_service.get_lingarr(instance_id))
