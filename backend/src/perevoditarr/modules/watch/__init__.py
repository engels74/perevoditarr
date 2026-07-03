"""Watch integrations module public interface (P5-T1, FR-X2/FR-Q5).

Other modules import only from here (PRD §2.2). Discovery consumes
`WatchScoreIndex`; the app wires the controller, gateway, and refresh loop.
"""

from perevoditarr.modules.watch.controllers import (
    WatchController,
    provide_watch_service,
)
from perevoditarr.modules.watch.gateway import WatchGateway, provide_watch_gateway
from perevoditarr.modules.watch.models import WatchScore, WatchSource
from perevoditarr.modules.watch.scheduler import run_watch_refresh, watch_refresh_loop
from perevoditarr.modules.watch.service import (
    WATCH_SCORE_TTL_SECONDS,
    WatchService,
    load_watch_index,
    watch_source_read,
)
from perevoditarr.modules.watch.signal import (
    AggregatedSignal,
    WatchScoreIndex,
    aggregate_activity,
)

__all__ = [
    "WATCH_SCORE_TTL_SECONDS",
    "AggregatedSignal",
    "WatchController",
    "WatchGateway",
    "WatchScore",
    "WatchScoreIndex",
    "WatchService",
    "WatchSource",
    "aggregate_activity",
    "load_watch_index",
    "provide_watch_gateway",
    "provide_watch_service",
    "run_watch_refresh",
    "watch_refresh_loop",
    "watch_source_read",
]
