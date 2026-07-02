"""Rails domain service (P3-T1, §8.4 / FR-Q3).

Composes the durable-usage counts (repository), the persisted stateful posture
(`rail_state`: pause + breaker + windows), and the active preset's thresholds
into explained admission verdicts consumed by the dispatcher, plan preview, and
dashboard gauges. Cap/budget usage is per-instance (the §7.2 dispatch decision
is per Bazarr instance); the global scope carries only the operator pause and
fleet-wide usage shown on the dashboard.

Breaker transitions publish `rails.breaker` on the SSE bus (UI plane) and are
returned to the caller so the orchestration layer can forward them to
notifications (P3-T5) — rails stays decoupled from the notifications module.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import msgspec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.dispatch.planning import DEFAULT_DISPATCH_WINDOW_K
from perevoditarr.modules.instances import (
    BazarrInstance,
    InstanceGateway,
    InstancesService,
)
from perevoditarr.modules.policy import PolicyService, RailSettingsDto
from perevoditarr.modules.rails.evaluation import (
    BreakerSnapshot,
    RailConfig,
    RailUsage,
    RailVerdict,
    breaker_after_failure,
    breaker_after_success,
    breaker_mark_probe,
    evaluate_admission,
)
from perevoditarr.modules.rails.models import RailState
from perevoditarr.modules.rails.repository import (
    dispatch_characters_since,
    dispatch_count_since,
)
from perevoditarr.modules.rails.schemas import (
    BudgetGaugeDto,
    CapGaugeDto,
    RailsOverview,
    RailStatusDto,
    breaker_dto,
    window_dto,
)
from perevoditarr.modules.rails.windows import (
    SchedulingWindow,
    decode_windows,
    encode_windows,
    window_open_at,
)


class BreakerTransition(msgspec.Struct, frozen=True, kw_only=True):
    """Result of a recorded dispatch outcome: what the breaker did, for the
    orchestration layer to forward to notifications (P3-T5)."""

    bazarr_instance_id: UUID
    from_state: str
    to_state: str
    consecutive_failures: int

    @property
    def tripped(self) -> bool:
        return self.from_state != "open" and self.to_state == "open"

    @property
    def closed(self) -> bool:
        return self.from_state != "closed" and self.to_state == "closed"


def _aware(value: datetime | None) -> datetime | None:
    # SQLite round-trips drop tzinfo; all stored breaker datetimes are UTC, so
    # normalize on read (matters most after a restart re-reads the row).
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _snapshot(row: RailState) -> BreakerSnapshot:
    state = row.breaker_state
    return BreakerSnapshot(
        state=state if state in ("closed", "open", "half_open") else "closed",
        consecutive_failures=row.breaker_consecutive_failures,
        opened_at=_aware(row.breaker_opened_at),
        last_probe_at=_aware(row.breaker_last_probe_at),
    )


def _apply_snapshot(row: RailState, snapshot: BreakerSnapshot) -> None:
    row.breaker_state = snapshot.state
    row.breaker_consecutive_failures = snapshot.consecutive_failures
    row.breaker_opened_at = snapshot.opened_at
    row.breaker_last_probe_at = snapshot.last_probe_at


class RailsService:
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        gateway: InstanceGateway,
        sse_bus: SseBus,
    ) -> None:
        self.session: AsyncSession = session
        self.sse_bus: SseBus = sse_bus
        self.instances: InstancesService = InstancesService(session, secret_box)
        self.policy: PolicyService = PolicyService(session, secret_box, gateway)
        self._config_cache: RailConfig | None = None

    # ------------------------------------------------------------ config

    async def config(self) -> RailConfig:
        if self._config_cache is None:
            preset = await self.policy.active_preset()
            rails = (
                self.policy.preset_rails(preset)
                if preset is not None
                else RailSettingsDto()
            )
            self._config_cache = _rail_config(rails)
        return self._config_cache

    async def _preset_window_k(self) -> int:
        preset = await self.policy.active_preset()
        if preset is None:
            return DEFAULT_DISPATCH_WINDOW_K
        rails = self.policy.preset_rails(preset)
        return rails.dispatch_window_k or DEFAULT_DISPATCH_WINDOW_K

    async def effective_window_k(self, bazarr_instance_id: UUID) -> int:
        """Per-instance K override (§7.2) falling back to the preset default."""
        row = await self._instance_row(bazarr_instance_id)
        return (
            row.window_k if row.window_k is not None else await self._preset_window_k()
        )

    async def is_dispatch_active(self, bazarr_instance_id: UUID) -> bool:
        return (await self._instance_row(bazarr_instance_id)).dispatch_active

    # ------------------------------------------------------------ rows

    async def _global_row(self) -> RailState:
        row = (
            await self.session.scalars(
                select(RailState).where(RailState.bazarr_instance_id.is_(None))
            )
        ).first()
        if row is None:
            row = RailState(bazarr_instance_id=None)
            self.session.add(row)
            await self.session.flush()
        return row

    async def _instance_row(self, bazarr_instance_id: UUID) -> RailState:
        row = (
            await self.session.scalars(
                select(RailState).where(
                    RailState.bazarr_instance_id == bazarr_instance_id
                )
            )
        ).first()
        if row is None:
            row = RailState(bazarr_instance_id=bazarr_instance_id)
            self.session.add(row)
            await self.session.flush()
        return row

    async def _windows(
        self, instance_row: RailState, global_row: RailState
    ) -> tuple[SchedulingWindow, ...]:
        # Instance windows take precedence; fall back to the global default.
        instance_windows = decode_windows(instance_row.scheduling_windows)
        if instance_windows:
            return instance_windows
        return decode_windows(global_row.scheduling_windows)

    async def _usage(self, bazarr_instance_id: UUID, *, now: datetime) -> RailUsage:
        hour = now - timedelta(hours=1)
        day = now - timedelta(days=1)
        week = now - timedelta(days=7)
        return RailUsage(
            hour_dispatches=await dispatch_count_since(
                self.session, hour, bazarr_instance_id=bazarr_instance_id
            ),
            day_dispatches=await dispatch_count_since(
                self.session, day, bazarr_instance_id=bazarr_instance_id
            ),
            week_dispatches=await dispatch_count_since(
                self.session, week, bazarr_instance_id=bazarr_instance_id
            ),
            day_characters=await dispatch_characters_since(
                self.session, day, bazarr_instance_id=bazarr_instance_id
            ),
        )

    # ------------------------------------------------------------ evaluate

    async def evaluate(
        self,
        bazarr_instance_id: UUID,
        *,
        candidate_characters: int,
        now: datetime | None = None,
    ) -> RailVerdict:
        moment = now if now is not None else datetime.now(UTC)
        global_row = await self._global_row()
        instance_row = await self._instance_row(bazarr_instance_id)
        config = await self.config()
        usage = await self._usage(bazarr_instance_id, now=moment)
        windows = await self._windows(instance_row, global_row)
        return evaluate_admission(
            config,
            usage,
            _snapshot(instance_row),
            paused=global_row.paused or instance_row.paused,
            window_open=window_open_at(windows, moment),
            candidate_characters=candidate_characters,
            now=moment,
        )

    async def mark_probe(
        self, bazarr_instance_id: UUID, *, now: datetime | None = None
    ) -> None:
        """Consume the breaker's half-open probe slot before a probing dispatch,
        so a concurrent evaluation cannot admit a second probe."""
        moment = now if now is not None else datetime.now(UTC)
        row = await self._instance_row(bazarr_instance_id)
        _apply_snapshot(row, breaker_mark_probe(_snapshot(row), now=moment))
        await self.session.commit()

    async def record_dispatch_result(
        self,
        bazarr_instance_id: UUID,
        *,
        success: bool,
        now: datetime | None = None,
    ) -> BreakerTransition:
        """Feed a verified dispatch outcome to the breaker (P3-T3 calls this on
        convergence/provider-failure). Publishes UI events on a state change and
        returns the transition for the notifications bridge."""
        moment = now if now is not None else datetime.now(UTC)
        config = await self.config()
        row = await self._instance_row(bazarr_instance_id)
        before = _snapshot(row)
        after = (
            breaker_after_success()
            if success
            else breaker_after_failure(
                before, config.breaker_failure_threshold, now=moment
            )
        )
        _apply_snapshot(row, after)
        await self.session.commit()
        transition = BreakerTransition(
            bazarr_instance_id=bazarr_instance_id,
            from_state=before.state,
            to_state=after.state,
            consecutive_failures=after.consecutive_failures,
        )
        if before.state != after.state:
            self.sse_bus.publish(
                "rails.breaker",
                {
                    "instanceId": str(bazarr_instance_id),
                    "fromState": before.state,
                    "toState": after.state,
                    "consecutiveFailures": after.consecutive_failures,
                },
            )
        return transition

    # ------------------------------------------------------------ controls

    async def pause(
        self, bazarr_instance_id: UUID | None, *, reason: str | None = None
    ) -> RailStatusDto:
        row = (
            await self._global_row()
            if bazarr_instance_id is None
            else await self._instance_row(bazarr_instance_id)
        )
        row.paused = True
        row.paused_reason = reason
        await self.session.commit()
        self.sse_bus.publish(
            "rails.pause",
            {
                "instanceId": None
                if bazarr_instance_id is None
                else str(row.bazarr_instance_id),
                "paused": True,
            },
        )
        return await self.status(bazarr_instance_id)

    async def resume(self, bazarr_instance_id: UUID | None) -> RailStatusDto:
        row = (
            await self._global_row()
            if bazarr_instance_id is None
            else await self._instance_row(bazarr_instance_id)
        )
        row.paused = False
        row.paused_reason = None
        await self.session.commit()
        self.sse_bus.publish(
            "rails.pause",
            {
                "instanceId": None
                if bazarr_instance_id is None
                else str(row.bazarr_instance_id),
                "paused": False,
            },
        )
        return await self.status(bazarr_instance_id)

    async def set_windows(
        self, bazarr_instance_id: UUID | None, windows: list[SchedulingWindow]
    ) -> RailStatusDto:
        row = (
            await self._global_row()
            if bazarr_instance_id is None
            else await self._instance_row(bazarr_instance_id)
        )
        row.scheduling_windows = encode_windows(windows) if windows else None
        await self.session.commit()
        return await self.status(bazarr_instance_id)

    async def set_activation(
        self, bazarr_instance_id: UUID, *, active: bool
    ) -> RailStatusDto:
        """Explicit Observe -> Active transition per instance (P3-T7, FR-Q1):
        the safe-by-default gate the dispatcher checks before firing."""
        _ = await self.instances.get_bazarr(bazarr_instance_id)
        row = await self._instance_row(bazarr_instance_id)
        row.dispatch_active = active
        await self.session.commit()
        self.sse_bus.publish(
            "rails.activation",
            {"instanceId": str(bazarr_instance_id), "active": active},
        )
        return await self.status(bazarr_instance_id)

    async def set_window_k(
        self, bazarr_instance_id: UUID, window_k: int | None
    ) -> RailStatusDto:
        _ = await self.instances.get_bazarr(bazarr_instance_id)
        row = await self._instance_row(bazarr_instance_id)
        row.window_k = window_k
        await self.session.commit()
        return await self.status(bazarr_instance_id)

    # ------------------------------------------------------------ status

    async def status(
        self, bazarr_instance_id: UUID | None, *, now: datetime | None = None
    ) -> RailStatusDto:
        moment = now if now is not None else datetime.now(UTC)
        if bazarr_instance_id is None:
            return await self._global_status(moment)
        instance = await self.instances.get_bazarr(bazarr_instance_id)
        return await self._instance_status(instance, moment)

    async def overview(self, *, now: datetime | None = None) -> RailsOverview:
        moment = now if now is not None else datetime.now(UTC)
        instances = [
            await self._instance_status(instance, moment)
            for instance in await self.instances.list_bazarr()
            if instance.enabled
        ]
        return RailsOverview(
            generated_at=moment,
            global_rails=await self._global_status(moment),
            instances=instances,
        )

    async def _global_status(self, now: datetime) -> RailStatusDto:
        global_row = await self._global_row()
        config = await self.config()
        usage = await self._usage_global(now=now)
        windows = decode_windows(global_row.scheduling_windows)
        return RailStatusDto(
            scope="global",
            bazarr_instance_id=None,
            instance_name=None,
            dispatch_active=False,
            paused=global_row.paused,
            paused_reason=global_row.paused_reason,
            dispatch_window_k=await self._preset_window_k(),
            window_open=window_open_at(windows, now),
            windows=[window_dto(window) for window in windows],
            breaker=None,
            caps=_cap_gauges(config, usage),
            budget=_budget_gauge(config, usage),
        )

    async def _instance_status(
        self, instance: BazarrInstance, now: datetime
    ) -> RailStatusDto:
        global_row = await self._global_row()
        instance_row = await self._instance_row(instance.id)
        config = await self.config()
        usage = await self._usage(instance.id, now=now)
        windows = await self._windows(instance_row, global_row)
        snapshot = _snapshot(instance_row)
        probe_due_at = _probe_due_at(snapshot, config.breaker_probe_minutes)
        window_k = (
            instance_row.window_k
            if instance_row.window_k is not None
            else await self._preset_window_k()
        )
        return RailStatusDto(
            scope="instance",
            bazarr_instance_id=instance.id,
            instance_name=instance.name,
            dispatch_active=instance_row.dispatch_active,
            paused=global_row.paused or instance_row.paused,
            paused_reason=instance_row.paused_reason or global_row.paused_reason,
            dispatch_window_k=window_k,
            window_open=window_open_at(windows, now),
            windows=[window_dto(window) for window in windows],
            breaker=breaker_dto(snapshot, probe_due_at),
            caps=_cap_gauges(config, usage),
            budget=_budget_gauge(config, usage),
        )

    async def _usage_global(self, *, now: datetime) -> RailUsage:
        hour = now - timedelta(hours=1)
        day = now - timedelta(days=1)
        week = now - timedelta(days=7)
        return RailUsage(
            hour_dispatches=await dispatch_count_since(self.session, hour),
            day_dispatches=await dispatch_count_since(self.session, day),
            week_dispatches=await dispatch_count_since(self.session, week),
            day_characters=await dispatch_characters_since(self.session, day),
        )


def _rail_config(rails: RailSettingsDto) -> RailConfig:
    defaults = RailConfig()
    return RailConfig(
        hourly_cap=rails.hourly_cap,
        daily_cap=rails.daily_cap,
        weekly_cap=rails.weekly_cap,
        budget_daily_characters=rails.budget_daily_characters,
        breaker_failure_threshold=(
            rails.breaker_failure_threshold
            if rails.breaker_failure_threshold is not None
            else defaults.breaker_failure_threshold
        ),
        breaker_probe_minutes=(
            rails.breaker_probe_minutes
            if rails.breaker_probe_minutes is not None
            else defaults.breaker_probe_minutes
        ),
    )


def _probe_due_at(snapshot: BreakerSnapshot, probe_minutes: int) -> datetime | None:
    if snapshot.state != "open":
        return None
    since = snapshot.last_probe_at or snapshot.opened_at
    return since + timedelta(minutes=probe_minutes) if since is not None else None


def _cap_gauges(config: RailConfig, usage: RailUsage) -> list[CapGaugeDto]:
    return [
        CapGaugeDto(
            period="hourly",
            used=usage.hour_dispatches,
            limit=config.hourly_cap,
            blocked=config.hourly_cap is not None
            and usage.hour_dispatches >= config.hourly_cap,
        ),
        CapGaugeDto(
            period="daily",
            used=usage.day_dispatches,
            limit=config.daily_cap,
            blocked=config.daily_cap is not None
            and usage.day_dispatches >= config.daily_cap,
        ),
        CapGaugeDto(
            period="weekly",
            used=usage.week_dispatches,
            limit=config.weekly_cap,
            blocked=config.weekly_cap is not None
            and usage.week_dispatches >= config.weekly_cap,
        ),
    ]


def _budget_gauge(config: RailConfig, usage: RailUsage) -> BudgetGaugeDto | None:
    if config.budget_daily_characters is None:
        return None
    return BudgetGaugeDto(
        used_characters=usage.day_characters,
        limit_characters=config.budget_daily_characters,
        blocked=usage.day_characters >= config.budget_daily_characters,
    )
