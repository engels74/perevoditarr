"""Intents module public interface (P2-T2).

Other modules import only from here: discovery (P2-T3) uses the seed/upsert
surface, the reconciler (P2-T4) and dispatcher (P3) use transitions and the
§6.5 in-flight probes, planning (P2-T5) reads the backlog, and app wiring
takes the controller/DI. The state machine and trace vocabulary are pure and
safe to import anywhere.
"""

from perevoditarr.modules.intents.collectors import (
    BazarrHistoryCollector,
    BazarrMetadataCollector,
    LingarrRequestCollector,
)
from perevoditarr.modules.intents.controllers import (
    IntentsController,
    provide_discovery_service,
    provide_intents_service,
)
from perevoditarr.modules.intents.discovery import (
    DiscoveryRunSummary,
    DiscoveryService,
)
from perevoditarr.modules.intents.discovery_rules import (
    CandidateDecision,
    ExistingSubtitle,
    NotPlanned,
    Planned,
    WantedCandidate,
    explain_candidate,
)
from perevoditarr.modules.intents.evidence import (
    BacklogOutcome,
    DurableEvidence,
    HistoryEvidence,
    LingarrEvidence,
    LingarrRequestMatch,
    NoChange,
    SubtitlePresence,
    Supersede,
    classify_backlog,
    history_evidence,
    lingarr_evidence_for_episode,
    lingarr_evidence_for_movie,
    subtitle_presence,
)
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.intents.reconciler import (
    ReconcilerService,
    ReconcileRunSummary,
    reconcile_loop,
    run_reconciliation,
)
from perevoditarr.modules.intents.scheduler import discovery_loop, run_discovery
from perevoditarr.modules.intents.schemas import (
    IntentDetail,
    IntentEventRead,
    IntentRead,
)
from perevoditarr.modules.intents.service import (
    IntentMediaType,
    IntentSeed,
    IntentsService,
    intent_read,
)
from perevoditarr.modules.intents.state_machine import (
    BACKLOG_STATES,
    IN_FLIGHT_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalIntentTransition,
    IntentState,
    assert_transition,
    can_transition,
)
from perevoditarr.modules.intents.trace import (
    BlockedByRail,
    Dispatched,
    EvidenceObserved,
    ExclusionMatched,
    GraceEvaluated,
    PriorityAssigned,
    ProfileMatched,
    SkipEvaluated,
    SourceElected,
    TargetMissing,
    TraceStep,
    Withdrawn,
    decode_trace,
    encode_trace,
    render_human,
    render_step,
)

__all__ = [
    "BACKLOG_STATES",
    "IN_FLIGHT_STATES",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "BacklogOutcome",
    "BazarrHistoryCollector",
    "BazarrMetadataCollector",
    "BlockedByRail",
    "CandidateDecision",
    "DiscoveryRunSummary",
    "DiscoveryService",
    "Dispatched",
    "DurableEvidence",
    "EvidenceObserved",
    "ExclusionMatched",
    "ExistingSubtitle",
    "GraceEvaluated",
    "HistoryEvidence",
    "IllegalIntentTransition",
    "Intent",
    "IntentDetail",
    "IntentEvent",
    "IntentEventRead",
    "IntentMediaType",
    "IntentRead",
    "IntentSeed",
    "IntentState",
    "IntentsController",
    "IntentsService",
    "LingarrEvidence",
    "LingarrRequestCollector",
    "LingarrRequestMatch",
    "NoChange",
    "NotPlanned",
    "Planned",
    "PriorityAssigned",
    "ProfileMatched",
    "ReconcileRunSummary",
    "ReconcilerService",
    "SkipEvaluated",
    "SourceElected",
    "SubtitlePresence",
    "Supersede",
    "TargetMissing",
    "TraceStep",
    "WantedCandidate",
    "Withdrawn",
    "assert_transition",
    "can_transition",
    "classify_backlog",
    "decode_trace",
    "discovery_loop",
    "encode_trace",
    "explain_candidate",
    "history_evidence",
    "intent_read",
    "lingarr_evidence_for_episode",
    "lingarr_evidence_for_movie",
    "provide_discovery_service",
    "provide_intents_service",
    "reconcile_loop",
    "render_human",
    "render_step",
    "run_discovery",
    "run_reconciliation",
    "subtitle_presence",
]
