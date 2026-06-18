"""Pre-fill-stop boundary (FR-PREFILL-4).

The engine pre-fills every fillable field but **stops and hands off** at
irreducible human steps. It never:

* clicks an account-creating submit,
* solves / bypasses a CAPTCHA / Turnstile / Cloudflare challenge,
* completes email / SMS verification,
* clicks the final submit *unless* the user has explicitly authorized
  friction-free engine submission (FR-PREFILL-5).

This rule is pure: the browser-automation adapter (Phase 2) must call
``ensure_action_allowed`` before performing any click/submit so the boundary
cannot be bypassed by an adapter.
"""

from __future__ import annotations

from enum import Enum

from applicant.core.errors import PrefillBoundaryViolation


class StepKind(str, Enum):
    """Kinds of step the engine may attempt during pre-fill."""

    FILL_FIELD = "fill_field"
    #: Attaching the rendered base résumé to a file ``<input type=file>`` (FR-RESUME-4).
    #: Always allowed — it is a deterministic, idempotent pre-fill step (no submit), so
    #: it sits alongside FILL_FIELD and never trips the hand-off boundary.
    UPLOAD_DOCUMENT = "upload_document"
    NAVIGATE = "navigate"
    SCREENSHOT = "screenshot"
    ACCOUNT_CREATE_SUBMIT = "account_create_submit"
    CAPTCHA = "captcha"
    EMAIL_VERIFY = "email_verify"
    SMS_VERIFY = "sms_verify"
    FINAL_SUBMIT = "final_submit"


#: Steps that are ALWAYS irreducible human steps — the engine must hand off. (The
#: engine cannot safely produce these regardless of any opt-in.)
_IRREDUCIBLE: frozenset[StepKind] = frozenset(
    {
        StepKind.CAPTCHA,
        StepKind.EMAIL_VERIFY,
        StepKind.SMS_VERIFY,
    }
)


def is_irreducible_human_step(step: StepKind) -> bool:
    """True if ``step`` is an UNCONDITIONALLY irreducible human step.

    Note: ``FINAL_SUBMIT`` and ``ACCOUNT_CREATE_SUBMIT`` are *conditionally* allowed —
    see ``ensure_action_allowed`` — so they are not in the unconditional set.
    """
    return step in _IRREDUCIBLE


def ensure_action_allowed(
    step: StepKind,
    *,
    engine_submit_authorized: bool = False,
    automated_accounts_enabled: bool = False,
) -> None:
    """Raise ``PrefillBoundaryViolation`` if the engine may not perform ``step``.

    Args:
        step: the action the engine is about to take.
        engine_submit_authorized: True only when the user has explicitly authorized the
            engine to click the *final* submit (FR-PREFILL-5).
        automated_accounts_enabled: True only when the operator has enabled automated
            account creation (ADR-0004, ``ALLOW_AUTOMATED_ACCOUNTS``). This is
            server-derived config threaded in by the adapter — NEVER a per-request flag.
    """
    if is_irreducible_human_step(step):
        raise PrefillBoundaryViolation(
            f"Engine must hand off at irreducible human step: {step.value}."
        )
    if step is StepKind.ACCOUNT_CREATE_SUBMIT and not automated_accounts_enabled:
        raise PrefillBoundaryViolation(
            "Account creation is not enabled; handing off to the user."
        )
    if step is StepKind.FINAL_SUBMIT and not engine_submit_authorized:
        raise PrefillBoundaryViolation(
            "Final submit requires explicit user authorization."
        )
