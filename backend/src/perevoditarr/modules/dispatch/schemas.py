"""Plan-preview API DTOs (P2-T5). camelCase on the wire via ApiStruct.

The verdict is a tagged union on the wire too (discriminator `type`), so the
TS client mirrors it as a discriminated union (Conventions). Rail posture is
echoed with the policy module's `RailSettingsDto` — same shape the presets
editor uses.
"""

from datetime import datetime
from typing import Literal, assert_never
from uuid import UUID

from perevoditarr.core.schemas import ApiStruct
from perevoditarr.modules.dispatch.estimation import VolumeEstimate
from perevoditarr.modules.dispatch.planning import (
    HeldByBudget,
    HeldByCap,
    HeldByInvariant,
    HeldByLimit,
    HeldByWindow,
    Included,
    Plan,
    PlanItem,
    SimulatedRails,
)
from perevoditarr.modules.policy import RailSettingsDto


class VolumeEstimateDto(ApiStruct):
    lines: int
    characters: int
    basis: Literal["actuals", "heuristic"]


class IncludedVerdictDto(ApiStruct, tag="included"):
    position: int


class HeldVerdictDto(ApiStruct, tag="held"):
    rail: str  # invariant | window | cap_* | budget | limit
    detail: str


class PlanItemDto(ApiStruct):
    intent_id: UUID
    bazarr_instance_id: UUID
    media_type: Literal["episode", "movie"]
    external_media_id: int
    sonarr_series_id: int | None
    display_title: str
    season: int | None
    episode_number: int | None
    source_language: str
    target_language: str
    forced: bool
    hi: bool
    priority: int
    bumped: bool
    profile_name: str | None
    score_components: dict[str, int] | None
    estimate: VolumeEstimateDto
    verdict: IncludedVerdictDto | HeldVerdictDto


class PlanTotalsDto(ApiStruct):
    evaluated: int
    included: int
    held: int
    estimated_lines: int
    estimated_characters: int


class PlanGroupDto(ApiStruct):
    """Grouping metadata (FR-U3): per-instance rollup of the plan."""

    bazarr_instance_id: UUID
    instance_name: str
    included: int
    held: int
    estimated_characters: int


class PlanPreviewResponse(ApiStruct):
    generated_at: datetime
    # Preset-layer dry-run flag: in Observe mode the preview is the primary
    # surface and nothing dispatches regardless (Phase 2 has no dispatcher).
    dry_run: bool
    active_preset: str | None
    rails: RailSettingsDto
    limit: int
    candidate_window: int  # how many backlog rows were evaluated at most
    items: list[PlanItemDto]
    totals: PlanTotalsDto
    groups: list[PlanGroupDto]


def estimate_dto(estimate: VolumeEstimate) -> VolumeEstimateDto:
    return VolumeEstimateDto(
        lines=estimate.lines, characters=estimate.characters, basis=estimate.basis
    )


def _verdict_dto(item: PlanItem) -> IncludedVerdictDto | HeldVerdictDto:
    match item.verdict:
        case Included(position=position):
            return IncludedVerdictDto(position=position)
        case (
            HeldByInvariant(rail=rail, detail=detail)
            | HeldByWindow(rail=rail, detail=detail)
            | HeldByCap(rail=rail, detail=detail)
            | HeldByBudget(rail=rail, detail=detail)
        ):
            return HeldVerdictDto(rail=rail, detail=detail)
        case HeldByLimit(detail=detail):
            return HeldVerdictDto(rail="limit", detail=detail)
    # Compile-time exhaustiveness: adding a PlanVerdict variant without a
    # DTO arm fails basedpyright here (mirrors trace.render_step); `verdict`
    # narrows to Never only when every variant returned above.
    assert_never(item.verdict)


def plan_item_dto(item: PlanItem) -> PlanItemDto:
    candidate = item.candidate
    return PlanItemDto(
        intent_id=candidate.intent_id,
        bazarr_instance_id=candidate.bazarr_instance_id,
        media_type=candidate.media_type,
        external_media_id=candidate.external_media_id,
        sonarr_series_id=candidate.sonarr_series_id,
        display_title=candidate.display_title,
        season=candidate.season,
        episode_number=candidate.episode_number,
        source_language=candidate.source_language,
        target_language=candidate.target_language,
        forced=candidate.forced,
        hi=candidate.hi,
        priority=candidate.priority,
        bumped=candidate.bumped,
        profile_name=candidate.profile_name,
        score_components=candidate.score_components,
        estimate=estimate_dto(candidate.estimate),
        verdict=_verdict_dto(item),
    )


def rails_dto(rails: SimulatedRails) -> RailSettingsDto:
    return RailSettingsDto(
        dispatch_window_k=rails.dispatch_window_k,
        hourly_cap=rails.hourly_cap,
        daily_cap=rails.daily_cap,
        weekly_cap=rails.weekly_cap,
        budget_daily_characters=rails.budget_daily_characters,
    )


def plan_totals_dto(plan: Plan) -> PlanTotalsDto:
    return PlanTotalsDto(
        evaluated=plan.totals.evaluated,
        included=plan.totals.included,
        held=plan.totals.held,
        estimated_lines=plan.totals.estimated_lines,
        estimated_characters=plan.totals.estimated_characters,
    )
