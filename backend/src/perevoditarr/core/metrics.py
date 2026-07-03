"""Prometheus-style metrics endpoint (P4-T3, NFR-6).

A single read-only `/metrics` handler in the standard text exposition format:
intents by lifecycle state, dispatch rates, rail posture (pause + breaker),
library-sync durations, and telemetry stream health. Everything is derived from
durable evidence (the intent ledger, rail_state, sync_run) plus the volatile
telemetry-health registry — no new counters, so it stays restart-safe.

Excluded from auth like /health: a self-hosted Prometheus scraper reaches it on
the internal network; it exposes counts, never secrets (FR-A5).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from litestar import Response, get
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.modules.instances.models import BazarrInstance
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.state_machine import IntentState
from perevoditarr.modules.mirror.models import SyncRun
from perevoditarr.modules.rails.models import RailState
from perevoditarr.modules.rails.repository import dispatch_count_since
from perevoditarr.modules.telemetry import TelemetryHealthRegistry

_DISPATCHED = IntentState.DISPATCHED.value
_BREAKER_CODE: dict[str, int] = {"closed": 0, "half_open": 1, "open": 2}


def escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_metric(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if not labels:
        return f"{name} {value:g}"
    rendered = ",".join(f'{key}="{escape_label(val)}"' for key, val in labels.items())
    return f"{name}{{{rendered}}} {value:g}"


async def collect_metrics(
    session: AsyncSession, telemetry_health: TelemetryHealthRegistry
) -> str:
    now = datetime.now(UTC)
    lines: list[str] = []

    # --- intents by state ---------------------------------------------------
    state_counts = {
        str(state): int(count)
        for state, count in (
            await session.execute(
                select(Intent.state, func.count()).group_by(Intent.state)
            )
        ).tuples()
    }
    lines.append("# HELP perevoditarr_intents Intents by lifecycle state.")
    lines.append("# TYPE perevoditarr_intents gauge")
    for state in IntentState:
        lines.append(
            render_metric(
                "perevoditarr_intents",
                state_counts.get(state.value, 0),
                {"state": state.value},
            )
        )

    # --- dispatch throughput ------------------------------------------------
    total_dispatches = (
        await session.execute(
            select(func.count())
            .select_from(IntentEvent)
            .where(IntentEvent.to_state == _DISPATCHED)
        )
    ).scalar_one()
    lines.append("# HELP perevoditarr_dispatches_total Bazarr translate dispatches.")
    lines.append("# TYPE perevoditarr_dispatches_total counter")
    lines.append(render_metric("perevoditarr_dispatches_total", int(total_dispatches)))
    hour = await dispatch_count_since(session, now - timedelta(hours=1))
    day = await dispatch_count_since(session, now - timedelta(days=1))
    lines.append("# HELP perevoditarr_dispatches_recent Recent dispatches by window.")
    lines.append("# TYPE perevoditarr_dispatches_recent gauge")
    lines.append(
        render_metric("perevoditarr_dispatches_recent", hour, {"window": "hour"})
    )
    lines.append(
        render_metric("perevoditarr_dispatches_recent", day, {"window": "day"})
    )

    # --- rail posture -------------------------------------------------------
    name_rows = (
        await session.execute(select(BazarrInstance.id, BazarrInstance.name))
    ).tuples()
    names = dict(name_rows.all())
    rails = list((await session.scalars(select(RailState))).all())
    lines.append("# HELP perevoditarr_rail_paused Rail pause flag (1 = paused).")
    lines.append("# TYPE perevoditarr_rail_paused gauge")
    lines.append(
        "# HELP perevoditarr_rail_breaker_state 0 closed, 1 half_open, 2 open."
    )
    lines.append("# TYPE perevoditarr_rail_breaker_state gauge")
    for rail in rails:
        scope, labels = _rail_labels(rail, names)
        lines.append(
            render_metric("perevoditarr_rail_paused", 1 if rail.paused else 0, labels)
        )
        if scope == "instance":
            lines.append(
                render_metric(
                    "perevoditarr_rail_breaker_state",
                    _BREAKER_CODE.get(rail.breaker_state, 0),
                    labels,
                )
            )

    # --- library sync durations (last completed per instance) ---------------
    lines.append(
        "# HELP perevoditarr_sync_duration_seconds Last completed sync duration."
    )
    lines.append("# TYPE perevoditarr_sync_duration_seconds gauge")
    for instance_id, seconds in (await _last_sync_durations(session)).items():
        lines.append(
            render_metric(
                "perevoditarr_sync_duration_seconds",
                seconds,
                {"instance": names.get(instance_id, str(instance_id))},
            )
        )

    # --- telemetry stream health -------------------------------------------
    lines.append(
        "# HELP perevoditarr_telemetry_stream_up Telemetry stream live (1 = live)."
    )
    lines.append("# TYPE perevoditarr_telemetry_stream_up gauge")
    for (instance_id, stream), status in telemetry_health.snapshot().items():
        lines.append(
            render_metric(
                "perevoditarr_telemetry_stream_up",
                1 if status.state == "live" else 0,
                {
                    "instance": names.get(instance_id, str(instance_id)),
                    "stream": stream,
                    "state": status.state,
                },
            )
        )

    return "\n".join(lines) + "\n"


def _rail_labels(rail: RailState, names: dict[UUID, str]) -> tuple[str, dict[str, str]]:
    if rail.bazarr_instance_id is None:
        return "global", {"scope": "global"}
    return "instance", {
        "scope": "instance",
        "instance": names.get(rail.bazarr_instance_id, str(rail.bazarr_instance_id)),
    }


async def _last_sync_durations(session: AsyncSession) -> dict[UUID, float]:
    rows = (
        await session.execute(
            select(
                SyncRun.bazarr_instance_id,
                SyncRun.started_at,
                SyncRun.finished_at,
            )
            .where(SyncRun.status == "completed", SyncRun.finished_at.is_not(None))
            .order_by(SyncRun.created_at.desc())
        )
    ).tuples()
    durations: dict[UUID, float] = {}
    for instance_id, started_at, finished_at in rows:
        if instance_id in durations or finished_at is None:
            continue
        durations[instance_id] = max(0.0, (finished_at - started_at).total_seconds())
    return durations


@get(
    "/metrics",
    exclude_from_auth=True,
    media_type="text/plain",
    include_in_schema=False,
)
async def metrics_endpoint(
    db_session: AsyncSession, telemetry_health: TelemetryHealthRegistry
) -> Response[str]:
    body = await collect_metrics(db_session, telemetry_health)
    return Response(
        body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
