"""Budget reconciliation (P4-T1, FR-U8): pull Lingarr's own statistics and
persist rolling per-file actuals, correcting the conservative volume heuristics
that feed the estimator (P2-T5) and the budget rails (P3-T1).

Lingarr owns provider-level truth (§6.7), so its statistics API is authoritative
for how many characters/lines a translated file actually cost. We snapshot the
latest averages per Lingarr instance; an unreachable Lingarr degrades to the
heuristic — never an error (same posture as the plan preview).
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import PerevoditarrError
from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.dispatch.estimation import (
    RollingActuals,
    actuals_from_statistics,
)
from perevoditarr.modules.instances import (
    BazarrInstance,
    InstanceGateway,
    InstancesService,
)
from perevoditarr.modules.integrations.lingarr.schemas import LingarrStatistics
from perevoditarr.modules.stats.models import LingarrActuals

_logger = get_logger()


async def latest_actuals(
    session: AsyncSession, *, lingarr_instance_id: UUID
) -> LingarrActuals | None:
    return (
        await session.scalars(
            select(LingarrActuals).where(
                LingarrActuals.lingarr_instance_id == lingarr_instance_id
            )
        )
    ).first()


def _rolling(row: LingarrActuals) -> RollingActuals | None:
    if row.sample_files <= 0:
        return None
    return RollingActuals(
        sample_files=row.sample_files,
        lines_per_file=row.lines_per_file,
        characters_per_file=row.characters_per_file,
    )


async def effective_actuals(
    session: AsyncSession, *, bazarr_instance_id: UUID
) -> RollingActuals | None:
    """Reconciled actuals for a Bazarr instance's Lingarr, or None when there is
    no linked Lingarr / no snapshot yet (caller falls back to the heuristic)."""
    lingarr_id = (
        await session.scalars(
            select(BazarrInstance.lingarr_instance_id).where(
                BazarrInstance.id == bazarr_instance_id
            )
        )
    ).first()
    if lingarr_id is None:
        return None
    row = await latest_actuals(session, lingarr_instance_id=lingarr_id)
    return _rolling(row) if row is not None else None


async def upsert_actuals(
    session: AsyncSession,
    *,
    lingarr_instance_id: UUID,
    stats: LingarrStatistics,
    now: datetime | None = None,
) -> LingarrActuals:
    moment = now if now is not None else datetime.now(UTC)
    actuals = actuals_from_statistics(stats)
    row = await latest_actuals(session, lingarr_instance_id=lingarr_instance_id)
    if row is None:
        row = LingarrActuals(lingarr_instance_id=lingarr_instance_id)
        session.add(row)
    row.sample_files = actuals.sample_files if actuals is not None else 0
    row.lines_per_file = actuals.lines_per_file if actuals is not None else 0.0
    row.characters_per_file = (
        actuals.characters_per_file if actuals is not None else 0.0
    )
    row.total_files = stats.total_files_translated
    row.total_lines = stats.total_lines_translated
    row.total_characters = stats.total_characters_translated
    row.captured_at = moment
    await session.commit()
    return row


async def run_budget_reconciliation(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    *,
    now: datetime | None = None,
) -> int:
    """Refresh the actuals snapshot for every enabled Lingarr instance. Returns
    the number of instances successfully reconciled; per-instance failures never
    cascade (an unreachable Lingarr keeps the last snapshot / heuristic)."""
    reconciled = 0
    async with alchemy.get_session() as session:
        instances = InstancesService(session, secret_box)
        for lingarr in await instances.list_lingarr():
            if not lingarr.enabled:
                continue
            try:
                client = gateway.lingarr(
                    lingarr.url, instances.lingarr_api_key(lingarr)
                )
                stats = await client.statistics()
                _ = await upsert_actuals(
                    session,
                    lingarr_instance_id=lingarr.id,
                    stats=stats,
                    now=now,
                )
                reconciled += 1
            except PerevoditarrError as error:
                await session.rollback()
                _logger.info(
                    "budget reconciliation skipped (Lingarr unreachable)",
                    instance=lingarr.name,
                    error=str(error),
                )
            except Exception as error:
                await session.rollback()
                _logger.warning(
                    "budget reconciliation failed",
                    instance=lingarr.name,
                    error=str(error),
                )
    return reconciled


async def budget_reconcile_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    interval_seconds: int,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            _ = await run_budget_reconciliation(alchemy, gateway, secret_box)
        except Exception as error:
            _logger.warning("budget reconcile loop iteration failed", error=str(error))
