"""Capability allowlist / registry (FR-HARVEST-CAPREG).

Every engine operation exposed through the proxy boundary (``/api/applicant/*``) must
have an entry here.  The registry is frozen at import time — no mutations at runtime.

Each :class:`Capability` carries three safety flags:

``mutates_application``
    The operation can modify a job application's state (prefilling forms, recording
    outcomes, etc.).  When ``True``, ``needs_human_review`` MUST also be ``True``
    unless the entry appears in :data:`REVIEW_EXEMPTIONS` with explicit reasoning.

``needs_human_review``
    A human must explicitly approve before (or as part of) the operation.

``exposes_sensitive``
    The response may contain data that should be treated as sensitive (credentials,
    PII, private profile data, etc.).

Invariant enforced by the drift test
(``tests/unit/test_capability_registry_drift.py``):

    mutates_application=True  →  needs_human_review=True
    UNLESS the capability name is listed in REVIEW_EXEMPTIONS.
"""

from __future__ import annotations

from typing import NamedTuple


class Capability(NamedTuple):
    """Immutable descriptor for one engine-exposed operation."""

    name: str
    mutates_application: bool
    needs_human_review: bool
    exposes_sensitive: bool


# ---------------------------------------------------------------------------
# Exemptions: operations that mutate an application but do NOT require prior
# human review.  Each entry must carry a non-empty rationale string.
# ---------------------------------------------------------------------------
REVIEW_EXEMPTIONS: dict[str, str] = {
    "prefill.resume_account_step": (
        "Resuming a parked pre-fill after the user completed a human-only account-creation "
        "step.  The user's physical presence at the live session IS the review act; the "
        "engine merely continues filling form fields that were already authorized (FR-PREFILL-4)."
    ),
    "prefill.resume_detection_step": (
        "Resuming a pre-fill that was blocked by an anti-bot detection page.  The user "
        "cleared the challenge in the live session, which constitutes the review; the "
        "engine continues from the cleared checkpoint (FR-PREFILL-6)."
    ),
    "prefill.continue_two_factor": (
        "Continuing a Google 2-factor auth hand-off.  The on-device 2FA approval IS the "
        "user review signal — the engine proceeds only after the user explicitly approves "
        "on their device (ADR-0004)."
    ),
    "sandbox.open_session": (
        "Provisioning a sandbox session creates infrastructure, not an application mutation. "
        "The session is the human-controlled environment; the application state changes "
        "only via subsequent human or engine-authorised actions (FR-SANDBOX-2)."
    ),
    "sandbox.authorize_takeover": (
        "Handing live control to the user is a capability grant to the human, not an "
        "autonomous application mutation (FR-SANDBOX-3)."
    ),
    "outcomes.detect_submission": (
        "Heuristic auto-detection of a submission that the user already performed in the "
        "live session.  The human act (clicking submit) is the review; detection merely "
        "records it (FR-LOG-4)."
    ),
    "digest.approve": (
        "The user's explicit approve action on a digested role IS the human review — this "
        "endpoint delivers that decision, it is not the engine acting autonomously (FR-DIG-3)."
    ),
    "digest.decline": (
        "The user's explicit decline action IS the human review — feedback is mandatory "
        "on this path (FR-DIG-5, FR-FB-1)."
    ),
    "pending_actions.resolve": (
        "Resolving a pending action signals that the user has acted; the user interaction "
        "IS the review.  The engine records the resolution, it does not act autonomously "
        "(FR-UI-3)."
    ),
    "attributes.upsert": (
        "User-directed attribute edits (via the chat, onboarding, or attribute UI) carry "
        "the user's explicit intent as the review.  Integral changes additionally require "
        "confirm=True (the confirmation gate, FR-FB-3), which is enforced in core."
    ),
    "criteria.edit": (
        "User-initiated criteria edit; the submission of the form IS the human review. "
        "Integral changes go through the confirmation gate (FR-FB-3)."
    ),
    "credentials.bank": (
        "Storing a credential in the vault is a user-directed act; the user's submission "
        "is the review signal (FR-VAULT-2)."
    ),
    "credentials.capture": (
        "Auto-capturing credentials the user typed during live account creation; the typing "
        "action in the live session is the user-review act (FR-VAULT-2)."
    ),
    "documents.set_aggressiveness": (
        "The truthful-framing aggressiveness dial is a preference knob with no direct "
        "application-state mutation; it shapes future generation only.  The UI ships the "
        "control grayed (FR-UI-2, FR-RESUME-9)."
    ),
    "documents.set_banned_phrases": (
        "Updating the banned-phrase list is a preference edit, not a direct application "
        "mutation; it affects future generation artifacts, not existing ones (FR-RESUME-5)."
    ),
    "feedback.submit": (
        "Free-text / survey feedback is a user-driven data contribution that flows into "
        "the learning loop.  The act of submitting is itself the user's review "
        "(FR-FB-1/2)."
    ),
    "campaigns.create": (
        "Creating a campaign creates campaign infrastructure, not a job application.  "
        "No application state is mutated (FR-CRIT-4)."
    ),
}

# ---------------------------------------------------------------------------
# The registry — a frozenset of Capability tuples.
# ---------------------------------------------------------------------------
_REGISTRY: frozenset[Capability] = frozenset(
    {
        # ---- Application submission / final-submit -------------------------
        Capability(
            name="remote.submit_self",
            mutates_application=True,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="remote.authorize_engine_finish",
            mutates_application=True,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="remote.request_final_approval",
            mutates_application=True,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        # ---- Pre-fill / form-fill -----------------------------------------
        Capability(
            name="prefill.resume_account_step",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="prefill.resume_detection_step",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="prefill.continue_two_factor",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        # ---- Sandbox / live session ---------------------------------------
        Capability(
            name="sandbox.open_session",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="sandbox.authorize_takeover",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="sandbox.list_sessions",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="sandbox.view_url",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Resume tailoring / generation --------------------------------
        Capability(
            name="documents.generate_cover_letter",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.generate_screening_answer",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.generate_deferred_essay",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.render_redline",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.approve",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.approve_variant",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.decline",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.ensure_submittable",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.list_for_application",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.list_variants",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.set_aggressiveness",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.set_banned_phrases",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.get_banned_phrases",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.open_review",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="documents.submit_turn",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        # ---- Job discovery / search ---------------------------------------
        Capability(
            name="discovery.run",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Digest / status check ----------------------------------------
        Capability(
            name="digest.get",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="digest.deliver",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="digest.get_email",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="digest.approve",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="digest.decline",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="digest.set_presence",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Research -----------------------------------------------------
        Capability(
            name="research.run",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="research.budget",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Pending actions ----------------------------------------------
        Capability(
            name="pending_actions.list",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="pending_actions.resolve",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        # ---- Notifications ------------------------------------------------
        Capability(
            name="notifications.list",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="notifications.mark_seen",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Outcomes -----------------------------------------------------
        Capability(
            name="outcomes.detect_submission",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="outcomes.mark_submitted",
            mutates_application=True,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        Capability(
            name="outcomes.list",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Credentials (vault) ------------------------------------------
        Capability(
            name="credentials.bank",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=True,
        ),
        Capability(
            name="credentials.capture",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=True,
        ),
        Capability(
            name="credentials.list_tenants",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="credentials.account_status",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="credentials.bank_account",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        # ---- Attributes ---------------------------------------------------
        Capability(
            name="attributes.upsert",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=True,
        ),
        Capability(
            name="attributes.list",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="attributes.bind_field",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="attributes.acquire_missing",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Criteria -----------------------------------------------------
        Capability(
            name="criteria.get",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="criteria.edit",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        # ---- Feedback -----------------------------------------------------
        Capability(
            name="feedback.submit",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        Capability(
            name="feedback.survey",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Chat ---------------------------------------------------------
        Capability(
            name="chat.turn",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="chat.confirm_proposal",
            mutates_application=False,
            needs_human_review=True,
            exposes_sensitive=False,
        ),
        # ---- Campaigns ----------------------------------------------------
        Capability(
            name="campaigns.list",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="campaigns.create",
            mutates_application=True,
            needs_human_review=False,  # exempted — see REVIEW_EXEMPTIONS
            exposes_sensitive=False,
        ),
        # ---- Agent runs ---------------------------------------------------
        Capability(
            name="agent_runs.configure",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="agent_runs.intent",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="agent_runs.status",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Setup / onboarding -------------------------------------------
        Capability(
            name="setup.status",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="setup.configure_llm",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="setup.configure_channels",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="setup.configure_sandbox",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="setup.advance_wizard_step",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="onboarding.get",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="onboarding.save_step",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="onboarding.complete",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="onboarding.ingest_resume",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        # ---- Model endpoints ----------------------------------------------
        Capability(
            name="model_endpoints.list",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="model_endpoints.add",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="model_endpoints.test",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="model_endpoints.toggle",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="model_endpoints.remove",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="model_endpoints.list_models",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Admin / observability ----------------------------------------
        Capability(
            name="admin.list_tools",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="admin.toggle_tool",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        Capability(
            name="admin.debug_logs",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="admin.application_history",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=True,
        ),
        Capability(
            name="admin.reset_learning",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
        # ---- Conversion ---------------------------------------------------
        Capability(
            name="conversion.render_pdf",
            mutates_application=False,
            needs_human_review=False,
            exposes_sensitive=False,
        ),
    }
)

# Public, read-only view of the registry.
CAPABILITY_REGISTRY: frozenset[Capability] = _REGISTRY


def lookup(name: str) -> Capability | None:
    """Return the :class:`Capability` for *name*, or ``None`` if not registered."""
    for cap in _REGISTRY:
        if cap.name == name:
            return cap
    return None


def all_capabilities() -> frozenset[Capability]:
    """Return a frozen copy of the full registry (immutable)."""
    return _REGISTRY
