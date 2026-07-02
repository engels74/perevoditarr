"""State machine table coverage (P2-T2): every legal edge passes, every
other pair raises, and the lifecycle groups stay consistent."""

from itertools import pairwise

import pytest

from perevoditarr.modules.intents.state_machine import (
    BACKLOG_STATES,
    IN_FLIGHT_STATES,
    MANUAL_TRANSITIONS,
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalIntentTransition,
    IntentState,
    assert_manual_transition,
    assert_transition,
    can_manual_transition,
    can_transition,
)

ALL_STATES = tuple(IntentState)
LEGAL_EDGES = [
    (from_state, to_state)
    for from_state, targets in TRANSITIONS.items()
    for to_state in sorted(targets)
]
ILLEGAL_EDGES = [
    (from_state, to_state)
    for from_state in ALL_STATES
    for to_state in ALL_STATES
    if to_state not in TRANSITIONS[from_state]
]


def test_table_covers_every_state() -> None:
    assert set(TRANSITIONS) == set(IntentState)


@pytest.mark.parametrize(("from_state", "to_state"), LEGAL_EDGES)
def test_legal_transitions_pass(from_state: IntentState, to_state: IntentState) -> None:
    assert can_transition(from_state, to_state)
    assert_transition(from_state, to_state)  # must not raise


@pytest.mark.parametrize(("from_state", "to_state"), ILLEGAL_EDGES)
def test_illegal_transitions_raise(
    from_state: IntentState, to_state: IntentState
) -> None:
    assert not can_transition(from_state, to_state)
    with pytest.raises(IllegalIntentTransition) as excinfo:
        assert_transition(from_state, to_state)
    assert excinfo.value.from_state is from_state
    assert excinfo.value.to_state is to_state


def test_prd_lifecycle_path_is_legal() -> None:
    # discovered → eligible → dispatched → failed → retry_eligible → eligible
    chain = [
        IntentState.DISCOVERED,
        IntentState.ELIGIBLE,
        IntentState.DISPATCHED,
        IntentState.FAILED,
        IntentState.RETRY_ELIGIBLE,
        IntentState.ELIGIBLE,
    ]
    for from_state, to_state in pairwise(chain):
        assert_transition(from_state, to_state)


def test_terminal_states_have_no_exits() -> None:
    assert {
        IntentState.CONVERGED,
        IntentState.SUPERSEDED,
        IntentState.QUARANTINED,
    } == TERMINAL_STATES
    for state in TERMINAL_STATES:
        assert not TRANSITIONS[state]


def test_lifecycle_groups_are_disjoint_and_complete() -> None:
    groups = (BACKLOG_STATES, IN_FLIGHT_STATES, TERMINAL_STATES)
    combined: set[IntentState] = set()
    for group in groups:
        assert not (combined & group)
        combined |= group
    # failed sits in no group: it resolves to retry_eligible or quarantined.
    assert set(IntentState) - combined == {IntentState.FAILED}


def test_supersede_reachable_from_every_non_terminal_state() -> None:
    # PRD §7.1: a subtitle appearing by other means supersedes the goal at
    # any point before terminality.
    for state in set(IntentState) - TERMINAL_STATES:
        assert can_transition(state, IntentState.SUPERSEDED)


def test_manual_retry_reeligibilizes_quarantined_and_needs_attention() -> None:
    # FR-R6: operator retry re-eligibilizes both a quarantined intent and a
    # needs-attention (failed) intent — an edge automation never takes (failed
    # only auto-moves to retry_eligible/quarantined/superseded).
    for source in (IntentState.QUARANTINED, IntentState.FAILED):
        assert can_manual_transition(source, IntentState.ELIGIBLE)
        assert_manual_transition(source, IntentState.ELIGIBLE)  # must not raise
        assert not can_transition(source, IntentState.ELIGIBLE)  # auto path forbids it


def test_manual_transitions_never_overlap_the_auto_table() -> None:
    # Manual edges must stay disjoint from TRANSITIONS so they never leak into
    # any automated process.
    for source, targets in MANUAL_TRANSITIONS.items():
        assert not (targets & TRANSITIONS[source])


def test_manual_transition_rejects_unlisted_source() -> None:
    with pytest.raises(IllegalIntentTransition):
        assert_manual_transition(IntentState.DISPATCHED, IntentState.ELIGIBLE)
