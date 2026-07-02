"""Dispatch module public interface (P2-T5; the dispatcher joins in P3).

Phase 2 scope: the deterministic plan preview — pure planner + estimator over
the ledger and the active preset's simulated rail posture. The priority
scorer lives in the policy module (weights are policy values); this module
consumes the scores the ledger already carries.
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
