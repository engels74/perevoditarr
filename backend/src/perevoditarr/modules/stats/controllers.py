"""Stats API controllers (P4-T1, FR-U8): read-only dashboard surface."""

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from litestar import Controller, get
from litestar.params import Parameter
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.modules.stats.schemas import (
    BudgetActualsDto,
    StatsOverviewResponse,
)
from perevoditarr.modules.stats.service import StatsService


async def provide_stats_service(db_session: AsyncSession) -> StatsService:
    return StatsService(db_session)


class StatsController(Controller):
    path: str = "/stats"
    tags: Sequence[str] | None = ("stats",)

    @get("/overview", operation_id="getStatsOverview")
    async def overview(
        self,
        stats_service: StatsService,
        days: Annotated[int, Parameter(ge=1, le=365)] = 30,
        bazarr_instance_id: Annotated[
            UUID | None, Parameter(query="bazarrInstanceId")
        ] = None,
    ) -> StatsOverviewResponse:
        return await stats_service.overview(
            days=days, bazarr_instance_id=bazarr_instance_id
        )

    @get("/budget", operation_id="getStatsBudget")
    async def budget(self, stats_service: StatsService) -> list[BudgetActualsDto]:
        return await stats_service.budget()
