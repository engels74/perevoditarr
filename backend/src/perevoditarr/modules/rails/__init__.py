"""Rails module public interface (P3-T1, §8.4 / FR-Q3).

Other modules import only from here: the dispatcher (P3-T2) calls `evaluate`/
`mark_probe`, verification (P3-T3) calls `record_dispatch_result`, the doctor
(P3-T6) reads breaker/window state, and app wiring takes the controller/DI. The
pure evaluation + window logic is safe to import anywhere.
"""

from perevoditarr.modules.rails.controllers import (
    RailsController,
    provide_rails_service,
)
from perevoditarr.modules.rails.evaluation import (
    DEFAULT_BREAKER_FAILURE_THRESHOLD,
    DEFAULT_BREAKER_PROBE_MINUTES,
    BreakerSnapshot,
    RailAllowed,
    RailBlocked,
    RailConfig,
    RailUsage,
    RailVerdict,
    breaker_after_failure,
    breaker_after_success,
    breaker_mark_probe,
    breaker_probe_due,
    evaluate_admission,
)
from perevoditarr.modules.rails.models import RailState
from perevoditarr.modules.rails.schemas import (
    RailsOverview,
    RailStatusDto,
    verdict_dto,
)
from perevoditarr.modules.rails.service import BreakerTransition, RailsService
from perevoditarr.modules.rails.windows import (
    SchedulingWindow,
    decode_windows,
    window_matches,
    window_open_at,
)

__all__ = [
    "DEFAULT_BREAKER_FAILURE_THRESHOLD",
    "DEFAULT_BREAKER_PROBE_MINUTES",
    "BreakerSnapshot",
    "BreakerTransition",
    "RailAllowed",
    "RailBlocked",
    "RailConfig",
    "RailState",
    "RailStatusDto",
    "RailUsage",
    "RailVerdict",
    "RailsController",
    "RailsOverview",
    "RailsService",
    "SchedulingWindow",
    "breaker_after_failure",
    "breaker_after_success",
    "breaker_mark_probe",
    "breaker_probe_due",
    "decode_windows",
    "evaluate_admission",
    "provide_rails_service",
    "verdict_dto",
    "window_matches",
    "window_open_at",
]
