"""Plan-preview service (P2-T5, FR-U3): assembles the snapshot, calls the
pure planner, returns explained DTOs.

Reads only: the eligible backlog through the intents public interface, the
active preset's rail posture through the policy service, and Lingarr
statistics for rolling-actuals estimates (an unreachable Lingarr degrades to
the heuristic — never an error). Nothing here dispatches; rails are simulated
(P3-T1 owns the real counters).
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import PerevoditarrError
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.dispatch.estimation import (
    RollingActuals,
    actuals_from_statistics,
    estimate_intent,
)
from perevoditarr.modules.dispatch.planning import (
    Included,
    Plan,
    PlanCandidate,
    SimulatedRails,
    build_plan,
)
from perevoditarr.modules.dispatch.schemas import (
    PlanGroupDto,
    PlanPreviewResponse,
    plan_item_dto,
    plan_totals_dto,
    rails_dto,
)
from perevoditarr.modules.instances import (
    BazarrInstance,
    InstanceGateway,
    InstancesService,
)
from perevoditarr.modules.intents import (
    Intent,
    IntentState,
    PriorityAssigned,
    ProfileMatched,
    decode_trace,
)
from perevoditarr.modules.intents.repository import backlog_stmt
from perevoditarr.modules.policy import (
    GLOBAL_DEFAULTS,
    PolicyService,
    RailSettingsDto,
)

# Upper bound on backlog rows one preview evaluates; everything inside it
# gets an explained verdict, anything beyond is simply past the horizon.
CANDIDATE_WINDOW = 500


class PlanPreviewService:
    def __init__(
        self, session: AsyncSession, secret_box: SecretBox, gateway: InstanceGateway
    ) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box
        self.gateway: InstanceGateway = gateway
        self.policy: PolicyService = PolicyService(session, secret_box, gateway)

    async def preview(
        self, *, limit: int, bazarr_instance_id: UUID | None = None
    ) -> PlanPreviewResponse:
        now = datetime.now(UTC)
        preset = await self.policy.active_preset()
        if preset is not None:
            rails = _simulated_rails(self.policy.preset_rails(preset))
            preset_dry_run = self.policy.preset_values(preset).dry_run
        else:
            rails = SimulatedRails()
            preset_dry_run = None
        # Preset layer decides the banner; per-item dry-run nuances live in
        # the effective-policy inspector. Absent everywhere ⇒ safe default.
        global_dry_run = GLOBAL_DEFAULTS.dry_run
        dry_run = (
            preset_dry_run
            if preset_dry_run is not None
            else (global_dry_run if global_dry_run is not None else True)
        )

        rows = (
            await self.session.scalars(
                backlog_stmt(bazarr_instance_id)
                .where(Intent.state == IntentState.ELIGIBLE.value)
                .limit(CANDIDATE_WINDOW)
            )
        ).all()
        actuals = await self._actuals_by_instance(
            {row.bazarr_instance_id for row in rows}
        )
        candidates = [
            _candidate(row, actuals.get(row.bazarr_instance_id)) for row in rows
        ]
        plan = build_plan(candidates, rails, limit=limit, reference_time=now)
        return PlanPreviewResponse(
            generated_at=now,
            dry_run=dry_run,
            active_preset=preset.name if preset is not None else None,
            rails=rails_dto(rails),
            limit=limit,
            candidate_window=CANDIDATE_WINDOW,
            items=[plan_item_dto(item) for item in plan.items],
            totals=plan_totals_dto(plan),
            groups=_groups(plan, await self._instance_names()),
        )

    async def _actuals_by_instance(
        self, instance_ids: set[UUID]
    ) -> dict[UUID, RollingActuals | None]:
        """One statistics read per distinct Lingarr; unreachable ⇒ heuristic."""
        instances = InstancesService(self.session, self.secret_box)
        lingarr_actuals: dict[UUID, RollingActuals | None] = {}
        result: dict[UUID, RollingActuals | None] = {}
        for instance in await instances.list_bazarr():
            if instance.id not in instance_ids:
                continue
            lingarr_id = instance.lingarr_instance_id
            if lingarr_id is None:
                result[instance.id] = None
                continue
            if lingarr_id not in lingarr_actuals:
                lingarr_row = await instances.get_lingarr(lingarr_id)
                client = self.gateway.lingarr(
                    lingarr_row.url, instances.lingarr_api_key(lingarr_row)
                )
                try:
                    stats = await client.statistics()
                except PerevoditarrError:
                    lingarr_actuals[lingarr_id] = None
                else:
                    lingarr_actuals[lingarr_id] = actuals_from_statistics(stats)
            result[instance.id] = lingarr_actuals[lingarr_id]
        return result

    async def _instance_names(self) -> dict[UUID, str]:
        rows = (
            await self.session.execute(select(BazarrInstance.id, BazarrInstance.name))
        ).tuples()
        return dict(rows.all())


def _simulated_rails(settings: RailSettingsDto) -> SimulatedRails:
    defaults = SimulatedRails()
    return SimulatedRails(
        dispatch_window_k=(
            settings.dispatch_window_k
            if settings.dispatch_window_k is not None
            else defaults.dispatch_window_k
        ),
        hourly_cap=settings.hourly_cap,
        daily_cap=settings.daily_cap,
        weekly_cap=settings.weekly_cap,
        budget_daily_characters=settings.budget_daily_characters,
    )


def _candidate(row: Intent, actuals: RollingActuals | None) -> PlanCandidate:
    media_type = "episode" if row.media_type == "episode" else "movie"
    steps = decode_trace(row.decision_trace)
    profile_name: str | None = None
    score_components: dict[str, int] | None = None
    for step in steps:
        if isinstance(step, ProfileMatched) and profile_name is None:
            profile_name = step.profile_name
        if isinstance(step, PriorityAssigned):
            score_components = step.components
    return PlanCandidate(
        intent_id=row.id,
        bazarr_instance_id=row.bazarr_instance_id,
        media_type=media_type,
        external_media_id=row.external_media_id,
        sonarr_series_id=row.sonarr_series_id,
        display_title=row.display_title,
        season=row.season,
        episode_number=row.episode_number,
        source_language=row.source_language,
        target_language=row.target_language,
        forced=row.forced,
        hi=row.hi,
        priority=row.priority,
        bumped=row.bumped_at is not None,
        score_components=score_components,
        profile_name=profile_name,
        estimate=estimate_intent(media_type, actuals),
    )


def _groups(plan: Plan, names: dict[UUID, str]) -> list[PlanGroupDto]:
    included: dict[UUID, int] = {}
    held: dict[UUID, int] = {}
    characters: dict[UUID, int] = {}
    order: list[UUID] = []
    for item in plan.items:
        instance_id = item.candidate.bazarr_instance_id
        if instance_id not in order:
            order.append(instance_id)
        if isinstance(item.verdict, Included):
            included[instance_id] = included.get(instance_id, 0) + 1
            characters[instance_id] = (
                characters.get(instance_id, 0) + item.candidate.estimate.characters
            )
        else:
            held[instance_id] = held.get(instance_id, 0) + 1
    return [
        PlanGroupDto(
            bazarr_instance_id=instance_id,
            instance_name=names.get(instance_id, str(instance_id)),
            included=included.get(instance_id, 0),
            held=held.get(instance_id, 0),
            estimated_characters=characters.get(instance_id, 0),
        )
        for instance_id in order
    ]
