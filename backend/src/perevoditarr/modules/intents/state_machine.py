"""Intent lifecycle state machine (P2-T2, PRD §7.1): pure domain logic.

The transition table is the single normative definition of the lifecycle:

    discovered → eligible → dispatched → converged
                                       → superseded
                                       → failed → retry_eligible | quarantined

plus the bookkeeping edges Observe mode needs (PRD §7.1 re-observation):
eligible may demote back to discovered when conditions no longer hold, any
pre-terminal state may supersede when the subtitle appears by other means or
the want disappears, and retry_eligible re-enters eligible.

Deliberately imports nothing from sqlalchemy/litestar/httpx — unit-testable
in isolation. State changes are only ever applied through the intents
service, which pairs every transition with an `intent_event` row.
"""

from collections.abc import Mapping
from enum import StrEnum


class IntentState(StrEnum):
    DISCOVERED = "discovered"
    ELIGIBLE = "eligible"
    DISPATCHED = "dispatched"
    CONVERGED = "converged"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    RETRY_ELIGIBLE = "retry_eligible"
    QUARANTINED = "quarantined"


TRANSITIONS: Mapping[IntentState, frozenset[IntentState]] = {
    IntentState.DISCOVERED: frozenset(
        {IntentState.ELIGIBLE, IntentState.SUPERSEDED},
    ),
    IntentState.ELIGIBLE: frozenset(
        {IntentState.DISCOVERED, IntentState.DISPATCHED, IntentState.SUPERSEDED},
    ),
    IntentState.DISPATCHED: frozenset(
        {IntentState.CONVERGED, IntentState.SUPERSEDED, IntentState.FAILED},
    ),
    IntentState.FAILED: frozenset(
        {IntentState.RETRY_ELIGIBLE, IntentState.QUARANTINED, IntentState.SUPERSEDED},
    ),
    IntentState.RETRY_ELIGIBLE: frozenset(
        {IntentState.ELIGIBLE, IntentState.SUPERSEDED},
    ),
    # Terminal: converged/superseded goals are met; quarantine release is a
    # deliberate manual action deferred to Phase 3 (FR-R6).
    IntentState.CONVERGED: frozenset(),
    IntentState.SUPERSEDED: frozenset(),
    IntentState.QUARANTINED: frozenset(),
}

BACKLOG_STATES: frozenset[IntentState] = frozenset(
    {IntentState.DISCOVERED, IntentState.ELIGIBLE, IntentState.RETRY_ELIGIBLE},
)
IN_FLIGHT_STATES: frozenset[IntentState] = frozenset({IntentState.DISPATCHED})
TERMINAL_STATES: frozenset[IntentState] = frozenset(
    state for state, targets in TRANSITIONS.items() if not targets
)


class IllegalIntentTransition(Exception):
    """Raised on any transition the table does not allow.

    Plain Exception (not PerevoditarrError) to keep this module free of
    transport imports; Phase 3's manual-action endpoints wrap it into an
    HTTP-mapped conflict at the controller boundary.
    """

    def __init__(self, from_state: IntentState, to_state: IntentState) -> None:
        super().__init__(f"illegal intent transition {from_state} → {to_state}")
        self.from_state: IntentState = from_state
        self.to_state: IntentState = to_state


def can_transition(from_state: IntentState, to_state: IntentState) -> bool:
    return to_state in TRANSITIONS[from_state]


def assert_transition(from_state: IntentState, to_state: IntentState) -> None:
    if not can_transition(from_state, to_state):
        raise IllegalIntentTransition(from_state, to_state)
