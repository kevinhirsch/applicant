"""Unit tests for the §7 application state machine (legal/illegal transitions)."""

from __future__ import annotations

import pytest

from applicant.core.errors import IllegalStateTransition
from applicant.core.state_machine import (
    TERMINAL_STATES,
    WAITING_STATES,
    ApplicationState,
    allowed_transitions,
    can_transition,
    is_terminal,
    is_waiting,
    transition,
)

S = ApplicationState

LEGAL = [
    (S.DISCOVERED, S.SCORED),
    (S.SCORED, S.DIGESTED),
    (S.DIGESTED, S.APPROVED),
    (S.DIGESTED, S.DECLINED),
    (S.APPROVED, S.SANDBOX_PROVISIONING),
    (S.SANDBOX_PROVISIONING, S.ACCOUNT_PREFILL),
    (S.SANDBOX_PROVISIONING, S.PREFILLING),
    (S.ACCOUNT_PREFILL, S.AWAITING_ACCOUNT_HUMAN_STEP),
    (S.AWAITING_ACCOUNT_HUMAN_STEP, S.PREFILLING),
    (S.PREFILLING, S.BLOCKED_DETECTION),
    (S.PREFILLING, S.BLOCKED_MISSING_ATTR),
    (S.PREFILLING, S.BLOCKED_QUESTION),
    (S.PREFILLING, S.MATERIAL_PREP),
    (S.PREFILLING, S.EMERGENCY_DATA_HANDOFF),
    (S.BLOCKED_DETECTION, S.PREFILLING),
    (S.BLOCKED_MISSING_ATTR, S.PREFILLING),
    (S.BLOCKED_QUESTION, S.PREFILLING),
    (S.MATERIAL_PREP, S.MATERIAL_REVIEW),
    (S.MATERIAL_REVIEW, S.MATERIAL_PREP),
    (S.MATERIAL_REVIEW, S.AWAITING_FINAL_APPROVAL),
    (S.MATERIAL_REVIEW, S.DECLINED),
    (S.AWAITING_FINAL_APPROVAL, S.SUBMITTED_BY_USER),
    (S.AWAITING_FINAL_APPROVAL, S.FINISHED_BY_ENGINE),
    (S.EMERGENCY_DATA_HANDOFF, S.SUBMITTED_BY_USER),
]

ILLEGAL = [
    (S.DISCOVERED, S.APPROVED),  # must be scored + digested first
    (S.SCORED, S.PREFILLING),
    (S.DIGESTED, S.PREFILLING),
    (S.PREFILLING, S.SUBMITTED_BY_USER),  # must pass material + final approval
    (S.MATERIAL_REVIEW, S.SUBMITTED_BY_USER),  # must go via AWAITING_FINAL_APPROVAL
    (S.AWAITING_FINAL_APPROVAL, S.PREFILLING),
    (S.DECLINED, S.APPROVED),  # terminal
    (S.SUBMITTED_BY_USER, S.PREFILLING),  # terminal
]


@pytest.mark.unit
@pytest.mark.parametrize("frm,to", LEGAL)
def test_legal_transitions(frm, to):
    assert can_transition(frm, to)
    assert transition(frm, to) == to


@pytest.mark.unit
@pytest.mark.parametrize("frm,to", ILLEGAL)
def test_illegal_transitions_raise(frm, to):
    assert not can_transition(frm, to)
    with pytest.raises(IllegalStateTransition):
        transition(frm, to)


@pytest.mark.unit
def test_failed_reachable_from_any_non_terminal():
    for state in ApplicationState:
        if is_terminal(state):
            assert not can_transition(state, S.FAILED)
        else:
            assert can_transition(state, S.FAILED)


@pytest.mark.unit
def test_terminal_states_have_no_outgoing():
    for state in TERMINAL_STATES:
        assert allowed_transitions(state) == frozenset()
        assert is_terminal(state)


@pytest.mark.unit
def test_waiting_states_classified():
    for state in WAITING_STATES:
        assert is_waiting(state)
    assert not is_waiting(S.PREFILLING)


@pytest.mark.unit
def test_all_19_states_present():
    assert len(list(ApplicationState)) == 19
