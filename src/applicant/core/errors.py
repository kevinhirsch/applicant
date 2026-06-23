"""Domain exceptions. Raised by the pure core to signal rule violations.

These are framework-agnostic; the delivery layer maps them to HTTP responses.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain-level errors."""


class IllegalStateTransition(DomainError):
    """An application lifecycle transition not permitted by the §7 state machine."""

    def __init__(self, frm: object, to: object) -> None:
        super().__init__(f"Illegal application state transition: {frm} -> {to}")
        self.frm = frm
        self.to = to


class TruthfulnessViolation(DomainError):
    """Generated material would fabricate a qualification/title/date/skill.

    FR-RESUME-2, NFR-TRUTH-1 — the truthfulness guardrail is a hard invariant.
    """


class SensitiveFieldViolation(DomainError):
    """An EEO/demographic field was about to be AI-guessed (FR-ATTR-6)."""


class ConfirmationRequired(DomainError):
    """An integral change was attempted without explicit user confirmation (FR-FB-3)."""


class ReviewRequired(DomainError):
    """Generated material would be submitted without passing the review gate (FR-RESUME-8)."""


class PrefillBoundaryViolation(DomainError):
    """The engine attempted an irreducible human step (FR-PREFILL-4).

    e.g. clicking an account-creating submit, solving a CAPTCHA, completing
    email/SMS verification, or clicking the final submit without authorization.
    """


class ComputerUseBlocked(DomainError):
    """A desktop (computer-use) action is forbidden by the core guards (FR-CUA-5/6).

    Raised when a desktop action hits a hard block — a dangerous key combo or ``type``
    pattern (``curl … | bash``, ``sudo rm -rf /``, a fork bomb, lock/log-out/empty-trash
    combos, FR-CUA-5) or an attempt to type a secret/credential (FR-CUA-6). These are
    denied server-side regardless of approval state; the prompt is never the gate.

    The pre-fill stop-boundary (account-create/CAPTCHA/verify/final-submit, FR-CUA-3) is
    enforced by RE-USING ``PrefillBoundaryViolation`` so computer use INHERITS that gate.
    """


class OnboardingIncomplete(DomainError):
    """Automated work was attempted before onboarding completed (FR-ONBOARD-2)."""


class LLMNotConfigured(DomainError):
    """A gated capability was used before the LLM was configured (FR-UI-5, FR-OOBE-1)."""


class NotFound(DomainError):
    """A requested entity (campaign, document, posting, ...) does not exist.

    Maps to HTTP 404 at the delivery edge. Raised by services in place of plain
    ``KeyError``/``ValueError`` for not-found lookups so the global handler can
    return a canonical 404 instead of a leaked 500.
    """


class InvalidInput(DomainError):
    """A request carried an invalid/unrecognized value (bad kind/mode/enum).

    Maps to HTTP 422 at the delivery edge. Raised in place of a plain
    ``ValueError`` for client-supplied bad input so it never leaks a 500.
    """
