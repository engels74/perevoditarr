"""Doctor service: context assembly, run persistence, SSE completion (P1-T6)."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import msgspec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from perevoditarr.core.errors import PerevoditarrError
from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.doctor.checks import all_checks
from perevoditarr.modules.doctor.framework import (
    BazarrContext,
    DoctorContext,
    Finding,
    LingarrContext,
    WatchSourceContext,
)
from perevoditarr.modules.doctor.models import DoctorFinding, DoctorRun
from perevoditarr.modules.doctor.schemas import DoctorFindingRead, DoctorRunRead
from perevoditarr.modules.instances import InstanceGateway, InstancesService
from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.instances.schemas import BazarrCapabilities
from perevoditarr.modules.mirror.models import SyncRun
from perevoditarr.modules.policy import PolicyService
from perevoditarr.modules.rails.models import RailState
from perevoditarr.modules.telemetry import TelemetryHealthRegistry
from perevoditarr.modules.watch import WatchGateway, WatchService

type DoctorTrigger = Literal["manual", "scheduled", "contextual"]


def _decode_capabilities(
    raw: dict[str, object] | None,
) -> BazarrCapabilities | None:
    if raw is None:
        return None
    try:
        return msgspec.convert(raw, type=BazarrCapabilities)
    except msgspec.ValidationError:
        return None


def finding_read(row: DoctorFinding) -> DoctorFindingRead:
    return DoctorFindingRead(
        id=row.id,
        check_id=row.check_id,
        severity=row.severity,
        message=row.message,
        explanation=row.explanation,
        fix_guidance=row.fix_guidance,
        bazarr_instance_id=row.bazarr_instance_id,
        lingarr_instance_id=row.lingarr_instance_id,
        data=row.data,
    )


def run_read(run: DoctorRun, findings: list[DoctorFinding]) -> DoctorRunRead:
    return DoctorRunRead(
        id=run.id,
        trigger=run.trigger,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary=run.summary,
        findings=[finding_read(f) for f in findings],
    )


class DoctorService:
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        gateway: InstanceGateway,
        sse_bus: SseBus,
        *,
        forward_auth_misconfigured: bool = False,
        telemetry_health: TelemetryHealthRegistry | None = None,
    ) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box
        self.gateway: InstanceGateway = gateway
        self.sse_bus: SseBus = sse_bus
        self.forward_auth_misconfigured: bool = forward_auth_misconfigured
        self.telemetry_health: TelemetryHealthRegistry | None = telemetry_health

    # ------------------------------------------------------- context

    async def _lingarr_context(self, instance: BazarrInstance) -> LingarrContext | None:
        instances = InstancesService(self.session, self.secret_box)
        if instance.lingarr_instance_id is None:
            return None
        lingarr_row = await instances.get_lingarr(instance.lingarr_instance_id)
        client = self.gateway.lingarr(
            lingarr_row.url, instances.lingarr_api_key(lingarr_row)
        )
        try:
            info = await client.version()
            settings = await client.doctor_settings()
        except PerevoditarrError:
            return LingarrContext(
                instance_id=lingarr_row.id,
                url=lingarr_row.url,
                version=lingarr_row.version,
                reachable=False,
            )
        return LingarrContext(
            instance_id=lingarr_row.id,
            url=lingarr_row.url,
            version=info.current_version or lingarr_row.version,
            reachable=True,
            settings=settings,
        )

    async def _mirror_freshness(
        self, instance_id: UUID
    ) -> tuple[bool, datetime | None]:
        last = (
            await self.session.scalars(
                select(SyncRun)
                .where(
                    SyncRun.bazarr_instance_id == instance_id,
                    SyncRun.status == "completed",
                )
                .order_by(SyncRun.started_at.desc())
                .limit(1)
            )
        ).first()
        if last is None:
            return False, None
        return True, last.finished_at

    async def _default_window_k(self) -> int:
        policy = PolicyService(self.session, self.secret_box, self.gateway)
        preset = await policy.active_preset()
        if preset is None:
            return 2
        return policy.preset_rails(preset).dispatch_window_k or 2

    async def _rail_snapshot(
        self, instance_id: UUID, default_k: int
    ) -> tuple[int, str, int]:
        """Read-only rail snapshot (N4): never creates a rail_state row."""
        row = (
            await self.session.scalars(
                select(RailState).where(RailState.bazarr_instance_id == instance_id)
            )
        ).first()
        if row is None:
            return default_k, "closed", 0
        window_k = row.window_k if row.window_k is not None else default_k
        state = (
            row.breaker_state
            if row.breaker_state in ("closed", "open", "half_open")
            else "closed"
        )
        return window_k, state, row.breaker_consecutive_failures

    async def build_context(self) -> DoctorContext:
        instances_service = InstancesService(self.session, self.secret_box)
        default_k = await self._default_window_k()
        contexts: list[BazarrContext] = []
        for instance in await instances_service.list_bazarr():
            if not instance.enabled:
                continue
            client = self.gateway.bazarr(
                instance.url, instances_service.bazarr_api_key(instance)
            )
            synced_ever, last_sync = await self._mirror_freshness(instance.id)
            window_k, breaker_state, breaker_failures = await self._rail_snapshot(
                instance.id, default_k
            )
            base = BazarrContext(
                instance_id=instance.id,
                name=instance.name,
                url=instance.url,
                version=instance.version,
                capabilities=_decode_capabilities(instance.capabilities),
                mirror_synced_ever=synced_ever,
                last_sync_finished_at=last_sync,
                dispatch_window_k=window_k,
                breaker_state=breaker_state,
                breaker_consecutive_failures=breaker_failures,
                telemetry_streams=(
                    {
                        stream: status.state
                        for stream, status in self.telemetry_health.for_instance(
                            instance.id
                        ).items()
                    }
                    if self.telemetry_health is not None
                    else {}
                ),
            )
            try:
                status = await client.system_status()
                settings = await client.system_settings()
                profiles = await client.languages_profiles()
            except PerevoditarrError:
                contexts.append(base)
                continue
            base.reachable = True
            base.version = status.bazarr_version
            base.settings = settings
            base.profiles = profiles
            base.lingarr = await self._lingarr_context(instance)
            contexts.append(base)
        policy = PolicyService(self.session, self.secret_box, self.gateway)
        return DoctorContext(
            now=datetime.now(UTC),
            instances=contexts,
            forward_auth_misconfigured=self.forward_auth_misconfigured,
            translation_profiles=list(await policy.profile_summaries()),
            watch_sources=await self._watch_contexts(),
        )

    async def _watch_contexts(self) -> list[WatchSourceContext]:
        watch = WatchService(
            self.session, self.secret_box, WatchGateway(self.gateway.registry)
        )
        contexts: list[WatchSourceContext] = []
        for source in await watch.list_sources():
            reachable = False
            detail: str | None = None
            if source.enabled:
                # Read-only probe (N4): never persists a health snapshot here.
                probe = await watch.probe_source(source)
                reachable = probe.reachable
                detail = probe.detail
            contexts.append(
                WatchSourceContext(
                    source_id=source.id,
                    name=source.name,
                    source_type=source.source_type,
                    enabled=source.enabled,
                    reachable=reachable,
                    detail=detail,
                )
            )
        return contexts

    # ------------------------------------------------------------ runs

    async def run(self, trigger: DoctorTrigger) -> DoctorRunRead:
        run = DoctorRun(trigger=trigger, status="running", started_at=datetime.now(UTC))
        self.session.add(run)
        await self.session.commit()

        findings: list[Finding] = []
        try:
            context = await self.build_context()
            for check in all_checks():
                findings.extend(check.run(context))
        except Exception:
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            await self.session.commit()
            raise

        rows = [
            DoctorFinding(
                run_id=run.id,
                check_id=finding.check_id,
                severity=finding.severity,
                bazarr_instance_id=finding.bazarr_instance_id,
                lingarr_instance_id=finding.lingarr_instance_id,
                message=finding.message,
                explanation=finding.explanation,
                fix_guidance=finding.fix_guidance,
                data=finding.data,
            )
            for finding in findings
        ]
        self.session.add_all(rows)
        summary = {
            "info": sum(1 for f in findings if f.severity == "info"),
            "warn": sum(1 for f in findings if f.severity == "warn"),
            "critical": sum(1 for f in findings if f.severity == "critical"),
        }
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        run.summary = summary
        await self.session.commit()

        self.sse_bus.publish(
            "doctor.completed", {"runId": str(run.id), "summary": summary}
        )
        return run_read(run, rows)

    async def latest(
        self, *, bazarr_instance_id: UUID | None = None
    ) -> DoctorRunRead | None:
        run = (
            await self.session.scalars(
                select(DoctorRun)
                .where(DoctorRun.status == "completed")
                .options(selectinload(DoctorRun.findings))
                .order_by(DoctorRun.started_at.desc())
                .limit(1)
            )
        ).first()
        if run is None:
            return None
        findings = [
            f
            for f in run.findings
            if bazarr_instance_id is None
            or f.bazarr_instance_id == bazarr_instance_id
            or f.bazarr_instance_id is None
        ]
        return run_read(run, findings)
