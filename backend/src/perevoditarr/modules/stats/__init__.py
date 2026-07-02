"""Statistics & budget-reconciliation module public interface (P4-T1, FR-U8).

App wiring takes the controller/DI and the two background jobs (rollup + budget
reconciliation); rails imports `effective_actuals` to correct its budget usage
with reconciled Lingarr statistics.
"""

from perevoditarr.modules.stats.controllers import (
    StatsController,
    provide_stats_service,
)
from perevoditarr.modules.stats.models import (
    LingarrActuals,
    StatsDaily,
    StatsLanguageDaily,
)
from perevoditarr.modules.stats.reconciliation import (
    budget_reconcile_loop,
    effective_actuals,
    run_budget_reconciliation,
    upsert_actuals,
)
from perevoditarr.modules.stats.rollup import (
    run_stats_backfill,
    run_stats_rollup,
    stats_rollup_loop,
)
from perevoditarr.modules.stats.service import StatsService

__all__ = [
    "LingarrActuals",
    "StatsController",
    "StatsDaily",
    "StatsLanguageDaily",
    "StatsService",
    "budget_reconcile_loop",
    "effective_actuals",
    "provide_stats_service",
    "run_budget_reconciliation",
    "run_stats_backfill",
    "run_stats_rollup",
    "stats_rollup_loop",
    "upsert_actuals",
]
