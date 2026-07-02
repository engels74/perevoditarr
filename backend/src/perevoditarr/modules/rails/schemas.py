"""Rails API DTOs (P3-T1). camelCase on the wire via ApiStruct/ApiRequest.

`RailStatusDto` powers the dashboard/queue gauges (live cap/budget/window/
breaker state with explanations); the verdict DTO mirrors the pure evaluation
tagged union as a discriminated union for the TS client.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import msgspec

from perevoditarr.core.schemas import ApiRequest, ApiStruct
from perevoditarr.modules.rails.evaluation import (
    BreakerSnapshot,
    RailAllowed,
    RailBlocked,
    RailVerdict,
)
from perevoditarr.modules.rails.windows import SchedulingWindow

type RailScope = Literal["global", "instance"]

HourMinute = Annotated[str, msgspec.Meta(pattern=r"^([01]?\d|2[0-3]):[0-5]\d$|^24:00$")]
Weekday = Annotated[int, msgspec.Meta(ge=0, le=6)]


class SchedulingWindowDto(ApiStruct):
    days: list[Weekday]
    start: str
    end: str
    timezone: str


class SchedulingWindowInput(ApiRequest):
    days: Annotated[list[Weekday], msgspec.Meta(max_length=7)] = msgspec.field(
        default_factory=list
    )
    start: HourMinute = "00:00"
    end: HourMinute = "24:00"
    timezone: Annotated[str, msgspec.Meta(min_length=1, max_length=64)] = "UTC"


class BreakerDto(ApiStruct):
    state: Literal["closed", "open", "half_open"]
    consecutive_failures: int
    opened_at: datetime | None = None
    last_probe_at: datetime | None = None
    probe_due_at: datetime | None = None


class CapGaugeDto(ApiStruct):
    period: Literal["hourly", "daily", "weekly"]
    used: int
    limit: int | None
    blocked: bool


class BudgetGaugeDto(ApiStruct):
    used_characters: int
    limit_characters: int | None
    blocked: bool


class RailStatusDto(ApiStruct):
    scope: RailScope
    bazarr_instance_id: UUID | None
    instance_name: str | None
    # Safe-by-default: an instance dispatches only after explicit activation.
    dispatch_active: bool
    paused: bool
    paused_reason: str | None
    dispatch_window_k: int
    window_open: bool
    windows: list[SchedulingWindowDto]
    breaker: BreakerDto | None
    caps: list[CapGaugeDto]
    budget: BudgetGaugeDto | None


class RailsOverview(ApiStruct):
    """Dashboard payload: the global posture plus every enabled instance."""

    generated_at: datetime
    global_rails: RailStatusDto
    instances: list[RailStatusDto]


class RailAllowedDto(ApiStruct, tag="allowed"):
    breaker_probe: bool


class RailBlockedDto(ApiStruct, tag="blocked"):
    rail: str
    detail: str
    resets_at: datetime | None = None


class PauseRequest(ApiRequest):
    reason: Annotated[str, msgspec.Meta(max_length=256)] | None = None


class WindowsUpdate(ApiRequest):
    windows: Annotated[list[SchedulingWindowInput], msgspec.Meta(max_length=32)] = (
        msgspec.field(default_factory=list)
    )


class WindowKUpdate(ApiRequest):
    # None clears the override and falls back to the preset default.
    window_k: Annotated[int, msgspec.Meta(ge=1, le=16)] | None = None


def breaker_dto(snapshot: BreakerSnapshot, probe_due_at: datetime | None) -> BreakerDto:
    return BreakerDto(
        state=snapshot.state,
        consecutive_failures=snapshot.consecutive_failures,
        opened_at=snapshot.opened_at,
        last_probe_at=snapshot.last_probe_at,
        probe_due_at=probe_due_at,
    )


def window_dto(window: SchedulingWindow) -> SchedulingWindowDto:
    return SchedulingWindowDto(
        days=list(window.days),
        start=window.start,
        end=window.end,
        timezone=window.timezone,
    )


def window_from_input(data: SchedulingWindowInput) -> SchedulingWindow:
    return SchedulingWindow(
        days=tuple(data.days), start=data.start, end=data.end, timezone=data.timezone
    )


def verdict_dto(verdict: RailVerdict) -> RailAllowedDto | RailBlockedDto:
    match verdict:
        case RailAllowed(breaker_probe=breaker_probe):
            return RailAllowedDto(breaker_probe=breaker_probe)
        case RailBlocked(rail=rail, detail=detail, resets_at=resets_at):
            return RailBlockedDto(rail=rail, detail=detail, resets_at=resets_at)
