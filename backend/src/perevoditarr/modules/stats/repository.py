"""Stats read queries (P4-T1): indexed range scans over the rollup tables, so
the dashboard never re-aggregates the audit trail at request time."""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.modules.stats.models import (
    LingarrActuals,
    StatsDaily,
    StatsLanguageDaily,
)


async def daily_rows(
    session: AsyncSession,
    *,
    since: date,
    until: date,
    bazarr_instance_id: UUID | None = None,
) -> list[StatsDaily]:
    stmt = (
        select(StatsDaily)
        .where(StatsDaily.day >= since, StatsDaily.day <= until)
        .order_by(StatsDaily.day)
    )
    if bazarr_instance_id is not None:
        stmt = stmt.where(StatsDaily.bazarr_instance_id == bazarr_instance_id)
    return list((await session.scalars(stmt)).all())


async def language_rows(
    session: AsyncSession,
    *,
    since: date,
    until: date,
    bazarr_instance_id: UUID | None = None,
) -> list[StatsLanguageDaily]:
    stmt = (
        select(StatsLanguageDaily)
        .where(StatsLanguageDaily.day >= since, StatsLanguageDaily.day <= until)
        .order_by(StatsLanguageDaily.day)
    )
    if bazarr_instance_id is not None:
        stmt = stmt.where(StatsLanguageDaily.bazarr_instance_id == bazarr_instance_id)
    return list((await session.scalars(stmt)).all())


async def actuals_rows(session: AsyncSession) -> list[LingarrActuals]:
    return list((await session.scalars(select(LingarrActuals))).all())


async def language_baseline(
    session: AsyncSession,
    *,
    before: date,
    bazarr_instance_id: UUID | None = None,
) -> dict[str, int]:
    """Converged-per-target-language totals strictly before `before`, so an
    in-range coverage trend can start from the true cumulative baseline."""
    stmt = (
        select(
            StatsLanguageDaily.target_language,
            func.coalesce(func.sum(StatsLanguageDaily.converged), 0),
        )
        .where(StatsLanguageDaily.day < before)
        .group_by(StatsLanguageDaily.target_language)
    )
    if bazarr_instance_id is not None:
        stmt = stmt.where(StatsLanguageDaily.bazarr_instance_id == bazarr_instance_id)
    return {
        str(language): int(total)
        for language, total in (await session.execute(stmt)).tuples()
    }
