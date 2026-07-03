"""Stats domain service (P4-T1, FR-U8): assemble the dashboard overview from
the rollup tables and the reconciled Lingarr actuals.

All aggregation is a cheap fold over pre-rolled daily rows — no request-time
scan of the `intent_event` audit trail (the plan's efficiency requirement).
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.modules.dispatch.estimation import (
    HEURISTIC_EPISODE_CHARACTERS,
    HEURISTIC_MOVIE_CHARACTERS,
)
from perevoditarr.modules.instances.models import LingarrInstance
from perevoditarr.modules.stats.models import LingarrActuals, StatsDaily
from perevoditarr.modules.stats.repository import (
    actuals_rows,
    daily_rows,
    language_baseline,
    language_rows,
)
from perevoditarr.modules.stats.schemas import (
    BudgetActualsDto,
    CoveragePointDto,
    CoverageSeriesDto,
    FailureClassDto,
    StatsOverviewResponse,
    StatsTotalsDto,
    ThroughputPointDto,
)

DEFAULT_RANGE_DAYS = 30

_FAILURE_CLASSES: tuple[str, ...] = (
    "transient",
    "environmental",
    "provider",
    "poison",
)


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    async def overview(
        self,
        *,
        days: int = DEFAULT_RANGE_DAYS,
        bazarr_instance_id: UUID | None = None,
        now: datetime | None = None,
    ) -> StatsOverviewResponse:
        moment = (now if now is not None else datetime.now(UTC)).astimezone(UTC)
        until = moment.date()
        since = until - timedelta(days=max(0, days - 1))
        rows = await daily_rows(
            self.session,
            since=since,
            until=until,
            bazarr_instance_id=bazarr_instance_id,
        )
        totals = _totals(rows)
        return StatsOverviewResponse(
            generated_at=moment,
            since=since,
            until=until,
            bazarr_instance_id=bazarr_instance_id,
            totals=totals,
            throughput=_throughput(rows),
            failure_classes=_failure_classes(totals),
            coverage=await self._coverage(
                since=since, until=until, bazarr_instance_id=bazarr_instance_id
            ),
            budget=await self.budget(),
        )

    async def _coverage(
        self, *, since: date, until: date, bazarr_instance_id: UUID | None
    ) -> list[CoverageSeriesDto]:
        rows = await language_rows(
            self.session,
            since=since,
            until=until,
            bazarr_instance_id=bazarr_instance_id,
        )
        baseline = await language_baseline(
            self.session, before=since, bazarr_instance_id=bazarr_instance_id
        )
        per_language: dict[str, dict[date, int]] = {}
        for row in rows:
            per_language.setdefault(row.target_language, {})[row.day] = (
                per_language.setdefault(row.target_language, {}).get(row.day, 0)
                + row.converged
            )
        series: list[CoverageSeriesDto] = []
        for language in sorted(set(per_language) | set(baseline)):
            days_map = per_language.get(language, {})
            cumulative = baseline.get(language, 0)
            points: list[CoveragePointDto] = []
            for day in sorted(days_map):
                converged = days_map[day]
                cumulative += converged
                points.append(
                    CoveragePointDto(
                        day=day, converged=converged, cumulative=cumulative
                    )
                )
            series.append(
                CoverageSeriesDto(
                    target_language=language, total=cumulative, points=points
                )
            )
        return series

    async def budget(self) -> list[BudgetActualsDto]:
        names = await self._lingarr_names()
        result: list[BudgetActualsDto] = []
        for row in await actuals_rows(self.session):
            result.append(_budget_dto(row, names.get(row.lingarr_instance_id, "")))
        result.sort(key=lambda dto: dto.instance_name)
        return result

    async def _lingarr_names(self) -> dict[UUID, str]:
        rows = (
            await self.session.execute(select(LingarrInstance.id, LingarrInstance.name))
        ).tuples()
        return dict(rows.all())


def _totals(rows: list[StatsDaily]) -> StatsTotalsDto:
    dispatched = converged = superseded = failed = 0
    converged_characters = duration_total = duration_samples = 0
    transient = environmental = provider = poison = 0
    for row in rows:
        dispatched += row.dispatched
        converged += row.converged
        superseded += row.superseded
        failed += row.failed
        converged_characters += row.converged_characters
        duration_total += row.duration_seconds_total
        duration_samples += row.duration_samples
        transient += row.failed_transient
        environmental += row.failed_environmental
        provider += row.failed_provider
        poison += row.failed_poison
    return StatsTotalsDto(
        dispatched=dispatched,
        converged=converged,
        superseded=superseded,
        failed=failed,
        converged_characters=converged_characters,
        mean_duration_seconds=(
            duration_total / duration_samples if duration_samples > 0 else None
        ),
        failed_transient=transient,
        failed_environmental=environmental,
        failed_provider=provider,
        failed_poison=poison,
    )


def _throughput(rows: list[StatsDaily]) -> list[ThroughputPointDto]:
    by_day: dict[date, ThroughputPointDto] = {}
    for row in rows:
        point = by_day.get(row.day)
        if point is None:
            by_day[row.day] = ThroughputPointDto(
                day=row.day,
                dispatched=row.dispatched,
                converged=row.converged,
                superseded=row.superseded,
                failed=row.failed,
            )
        else:
            point.dispatched += row.dispatched
            point.converged += row.converged
            point.superseded += row.superseded
            point.failed += row.failed
    return [by_day[day] for day in sorted(by_day)]


def _failure_classes(totals: StatsTotalsDto) -> list[FailureClassDto]:
    counts = {
        "transient": totals.failed_transient,
        "environmental": totals.failed_environmental,
        "provider": totals.failed_provider,
        "poison": totals.failed_poison,
    }
    total = totals.failed
    return [
        FailureClassDto(
            failure_class=name,
            count=counts[name],
            rate=(counts[name] / total if total > 0 else 0.0),
        )
        for name in _FAILURE_CLASSES
    ]


def _budget_dto(row: LingarrActuals, name: str) -> BudgetActualsDto:
    return BudgetActualsDto(
        lingarr_instance_id=row.lingarr_instance_id,
        instance_name=name,
        has_actuals=row.sample_files > 0,
        sample_files=row.sample_files,
        lines_per_file=row.lines_per_file,
        characters_per_file=row.characters_per_file,
        total_files=row.total_files,
        total_characters=row.total_characters,
        captured_at=row.captured_at,
        heuristic_characters_episode=HEURISTIC_EPISODE_CHARACTERS,
        heuristic_characters_movie=HEURISTIC_MOVIE_CHARACTERS,
    )
