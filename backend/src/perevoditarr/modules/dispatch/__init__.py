"""Dispatch module public interface.

Two layers live here. The *pure/preview* surface — the deterministic planner
(P2-T5) + estimator over the ledger and the active preset's rail posture — is
re-exported here and safely consumed by other modules (including rails, which
reads the sizing heuristics and default window K). The *orchestration* leaf —
`DispatcherService` (P3-T2) and its scheduler — depends on rails and is imported
directly from `dispatch.dispatcher` / `dispatch.scheduler` by app wiring, so this
package's `__init__` stays free of the rails dependency (no import cycle).
"""

from perevoditarr.modules.dispatch.controllers import (
    DispatchController,
    provide_plan_preview_service,
)
from perevoditarr.modules.dispatch.estimation import (
    RollingActuals,
    VolumeEstimate,
    actuals_from_statistics,
    estimate_intent,
)
from perevoditarr.modules.dispatch.planning import (
    HeldByBudget,
    HeldByCap,
    HeldByInvariant,
    HeldByLimit,
    HeldByWindow,
    Included,
    Plan,
    PlanCandidate,
    PlanItem,
    PlanTotals,
    PlanVerdict,
    SimulatedRails,
    build_plan,
)
from perevoditarr.modules.dispatch.schemas import PlanPreviewResponse
from perevoditarr.modules.dispatch.service import PlanPreviewService

__all__ = [
    "DispatchController",
    "HeldByBudget",
    "HeldByCap",
    "HeldByInvariant",
    "HeldByLimit",
    "HeldByWindow",
    "Included",
    "Plan",
    "PlanCandidate",
    "PlanItem",
    "PlanPreviewResponse",
    "PlanPreviewService",
    "PlanTotals",
    "PlanVerdict",
    "RollingActuals",
    "SimulatedRails",
    "VolumeEstimate",
    "actuals_from_statistics",
    "build_plan",
    "estimate_intent",
    "provide_plan_preview_service",
]
