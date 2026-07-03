"""Watch score refresh loop (P5-T1).

Periodically pulls activity from every enabled watch source and rebuilds the
`watch_score` cache (the "score cache with TTL" of PRD §11). Best-effort: a
source outage keeps the last cache until its TTL ages it out (ADR-0007). The
loop is disabled when watch_refresh_interval_seconds is 0."""

import asyncio
from datetime import datetime

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.watch.gateway import WatchGateway
from perevoditarr.modules.watch.schemas import WatchRefreshResult
from perevoditarr.modules.watch.service import WatchService

_logger = get_logger()


async def run_watch_refresh(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: WatchGateway,
    secret_box: SecretBox,
    *,
    window_days: int,
    frequent_min_plays: int,
    activity_limit: int,
    now: datetime | None = None,
) -> WatchRefreshResult:
    async with alchemy.get_session() as session:
        service = WatchService(session, secret_box, gateway)
        return await service.refresh(
            window_days=window_days,
            frequent_min_plays=frequent_min_plays,
            activity_limit=activity_limit,
            now=now,
        )


async def watch_refresh_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: WatchGateway,
    secret_box: SecretBox,
    interval_seconds: int,
    *,
    window_days: int,
    frequent_min_plays: int,
    activity_limit: int,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            _ = await run_watch_refresh(
                alchemy,
                gateway,
                secret_box,
                window_days=window_days,
                frequent_min_plays=frequent_min_plays,
                activity_limit=activity_limit,
            )
        except Exception as error:
            _logger.warning("watch refresh loop iteration failed", error=str(error))
