"""Application lifecycle state machine (master spec §7, docs/state-machine.md).

This is a load-bearing invariant of the core: every application's ``status`` moves
only along legal transitions. Illegal transitions raise ``IllegalStateTransition``.
Each step in the real pipeline is an idempotent DBOS step (FR-DUR-1/3); this module
defines *which* moves are legal, not how they are executed.
"""

from __future__ import annotations

from enum import Enum

from applicant.core.errors import IllegalStateTransition


class ApplicationState(str, Enum):
    """All §7 lifecycle states."""

    DISCOVERED = "DISCOVERED"
    SCORED = "SCORED"
    DIGESTED = "DIGESTED"
    DECLINED = "DECLINED"
    APPROVED = "APPROVED"
    SANDBOX_PROVISIONING = "SANDBOX_PROVISIONING"
    ACCOUNT_PREFILL = "ACCOUNT_PREFILL"
    AWAITING_ACCOUNT_HUMAN_STEP = "AWAITING_ACCOUNT_HUMAN_STEP"
    PREFILLING = "PREFILLING"
    BLOCKED_DETECTION = "BLOCKED_DETECTION"
    BLOCKED_MISSING_ATTR = "BLOCKED_MISSING_ATTR"
    BLOCKED_QUESTION = "BLOCKED_QUESTION"
    MATERIAL_PREP = "MATERIAL_PREP"
    MATERIAL_REVIEW = "MATERIAL_REVIEW"
    AWAITING_FINAL_APPROVAL = "AWAITING_FINAL_APPROVAL"
    SUBMITTED_BY_USER = "SUBMITTED_BY_USER"
    FINISHED_BY_ENGINE = "FINISHED_BY_ENGINE"
    EMERGENCY_DATA_HANDOFF = "EMERGENCY_DATA_HANDOFF"
    FAILED = "FAILED"


S = ApplicationState

#: Terminal states — no outgoing transitions (except none).
TERMINAL_STATES: frozenset[ApplicationState] = frozenset(
    {S.DECLINED, S.SUBMITTED_BY_USER, S.FINISHED_BY_ENGINE, S.FAILED}
)

#: User-waiting states — each emits a notification + pending-action and pivots (§7).
WAITING_STATES: frozenset[ApplicationState] = frozenset(
    {
        S.DIGESTED,
        S.AWAITING_ACCOUNT_HUMAN_STEP,
        S.BLOCKED_DETECTION,
        S.BLOCKED_MISSING_ATTR,
        S.BLOCKED_QUESTION,
        S.MATERIAL_REVIEW,
        S.AWAITING_FINAL_APPROVAL,
        S.EMERGENCY_DATA_HANDOFF,
    }
)

#: Legal transition table (from -> set of allowed next states), per §7.
#: ``FAILED`` is reachable from any non-terminal state ("any unrecoverable error").
_TRANSITIONS: dict[ApplicationState, frozenset[ApplicationState]] = {
    S.DISCOVERED: frozenset({S.SCORED}),
    S.SCORED: frozenset({S.DIGESTED}),
    S.DIGESTED: frozenset({S.DECLINED, S.APPROVED}),
    S.APPROVED: frozenset({S.SANDBOX_PROVISIONING}),
    S.SANDBOX_PROVISIONING: frozenset({S.ACCOUNT_PREFILL, S.PREFILLING}),
    S.ACCOUNT_PREFILL: frozenset({S.AWAITING_ACCOUNT_HUMAN_STEP}),
    S.AWAITING_ACCOUNT_HUMAN_STEP: frozenset({S.PREFILLING}),
    S.PREFILLING: frozenset(
        {
            S.BLOCKED_DETECTION,
            S.BLOCKED_MISSING_ATTR,
            S.BLOCKED_QUESTION,
            S.MATERIAL_PREP,
            S.EMERGENCY_DATA_HANDOFF,
        }
    ),
    S.BLOCKED_DETECTION: frozenset({S.PREFILLING}),
    S.BLOCKED_MISSING_ATTR: frozenset({S.PREFILLING}),
    S.BLOCKED_QUESTION: frozenset({S.PREFILLING}),
    S.MATERIAL_PREP: frozenset({S.MATERIAL_REVIEW}),
    S.MATERIAL_REVIEW: frozenset({S.MATERIAL_PREP, S.AWAITING_FINAL_APPROVAL, S.DECLINED}),
    S.AWAITING_FINAL_APPROVAL: frozenset({S.SUBMITTED_BY_USER, S.FINISHED_BY_ENGINE}),
    S.EMERGENCY_DATA_HANDOFF: frozenset({S.SUBMITTED_BY_USER}),
    # Terminal states: no outgoing transitions.
    S.DECLINED: frozenset(),
    S.SUBMITTED_BY_USER: frozenset(),
    S.FINISHED_BY_ENGINE: frozenset(),
    S.FAILED: frozenset(),
}


def is_terminal(state: ApplicationState) -> bool:
    """True if ``state`` has no outgoing transitions."""
    return state in TERMINAL_STATES


def is_waiting(state: ApplicationState) -> bool:
    """True if ``state`` waits on the user (notifies, lands in portal, pivots)."""
    return state in WAITING_STATES


def allowed_transitions(state: ApplicationState) -> frozenset[ApplicationState]:
    """Return the set of states reachable from ``state`` in one legal step.

    ``FAILED`` is always reachable from any non-terminal state (§7: "any
    unrecoverable error -> FAILED").
    """
    base = _TRANSITIONS.get(state, frozenset())
    if is_terminal(state):
        return base
    return base | {S.FAILED}


def can_transition(frm: ApplicationState, to: ApplicationState) -> bool:
    """True iff moving from ``frm`` to ``to`` is permitted by §7."""
    return to in allowed_transitions(frm)


def transition(frm: ApplicationState, to: ApplicationState) -> ApplicationState:
    """Validate and perform a lifecycle transition.

    Returns the new state on success; raises ``IllegalStateTransition`` otherwise.
    """
    if not can_transition(frm, to):
        raise IllegalStateTransition(frm, to)
    return to
