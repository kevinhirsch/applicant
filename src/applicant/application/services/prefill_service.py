"""PrefillService (FR-PREFILL-*, FR-ATTR-5/6, FR-STEALTH, FR-SANDBOX, FR-NOTIF-2).

Drives the **maximal pre-fill loop**: provision a sandbox, walk every page of the
ATS, detect every fillable field, and fill it from the campaign attribute cloud —
routing every fill decision through the core **sensitive-field policy** (EEO fields
filled only from explicit stored answers, never AI-guessed) and every click/submit
through the core **pre-fill-stop boundary** (never click account-create / final
submit). It emits the §7 ``BLOCKED_*`` / ``AWAITING_*`` states with pending actions
+ notifications, supports **cautious mode** (pause on a detection signal), and the
**final-approval gate** via the durable orchestrator's ``recv`` (FR-NOTIF-2).

Field resolution (FR-PREFILL-3, FR-ATTR-5/6, FR-ANSWER-1):

* **Sensitive (EEO) fields** route through ``decide_sensitive_fill`` — explicit
  stored answer only, else "decline to self-identify"; never AI-guessed.
* **Factual screening questions** fill from stored attributes like any field.
* **Essay screening questions** are NOT answered here — they are recorded and
  deferred to Phase 3 generation + the FR-RESUME-8 review gate (a clean handoff);
  pre-fill of the remaining fields continues.
* **Ambiguous non-sensitive mappings** escalate to the LLM port when one is
  configured; an unconfident/absent answer becomes a missing-attribute soft error.
* **Missing required attributes** raise the FR-ATTR-5 soft-error flow
  (``BLOCKED_MISSING_ATTR``): a pending action lands, the value is reused after the
  user resolves it.
* **Fill failure** (the agent reports it tried and failed) yields the emergency
  data-handoff (``EMERGENCY_DATA_HANDOFF``) — never the default (FR-PREFILL-7).

Scope note: drives the in-memory browser/sandbox/detection adapters — no real
browser. The state transitions, rule enforcement, and hand-off shape are real and
tested; swapping in the real Playwright page-source is the only change to go live.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field

from applicant.adapters.browser.ats import SCREENING_ESSAY, SCREENING_FACTUAL
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.pending_action import PendingAction
from applicant.core.errors import NativeFilePickerRequired
from applicant.core.ids import ApplicationId, CampaignId, PendingActionId, new_id
from applicant.core.rules.ats_match_rate import (
    DEFAULT_MATCH_RATE_FLOOR,
    field_match_rate,
    is_probable_wrong_ats,
)
from applicant.core.rules.sensitive_fields import decide_sensitive_fill, is_sensitive_field
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import DetectedField

log = logging.getLogger(__name__)


#: Topic the durable orchestrator uses for the final-approval gate (FR-NOTIF-2).
FINAL_APPROVAL_TOPIC = "final_approval"

#: Credential-vault key for the user's Google account (one account reused across all
#: tenants' "Sign in with Google", vs. per-ATS-tenant direct credentials).
GOOGLE_CREDENTIAL_KEY = "google"

#: Credential-vault key for the predefined account set used to CREATE new ATS accounts
#: (ADR-0004): its ``username`` is the email; a strong password is generated per tenant
#: and banked under the tenant's key on success.
PREDEFINED_CREDENTIAL_KEY = "predefined:account"

#: Account-level credentials that are NOT tied to one job search: the user sets them
#: once in Settings and they apply to every campaign. They are banked under the global
#: SYSTEM campaign; ``_lookup_credential`` falls back to that scope for these keys so
#: "sign in to Google once and reuse it everywhere" actually holds across campaigns.
SHARED_CREDENTIAL_KEYS = (GOOGLE_CREDENTIAL_KEY, PREDEFINED_CREDENTIAL_KEY)


def ping_ref(application_id, kind: str) -> str:
    """Stable ref for a prefill blocked-state ping (#7).

    ``NotificationService.notify_decision`` keys a ping at ``decision:<ref>`` and
    ``NotificationService.acted(<ref>)`` expires exactly that key. Prefill pings now
    use this same ``prefill:<app>:<kind>`` ref so resolving a blocked state expires
    its ping via ``acted(ping_ref(app, kind))`` — the old un-prefixed
    ``<app>:<kind>`` key could never be expired by ``acted``.
    """
    return f"prefill:{application_id}:{kind}"


def ping_dedup_key(application_id, kind: str, _suffix: str | None = None) -> str:
    """The notification dedup key for a prefill ping (mirrors NotificationService).

    Equal to ``decision:<ping_ref>`` so ``NotificationService.acted(ping_ref(...))``
    expires it. ``_suffix`` is accepted for call-site symmetry but intentionally NOT
    folded into the key, so the key stays exactly expirable by ``acted``.
    """
    return f"decision:{ping_ref(application_id, kind)}"

#: Per-task starting tier for field-mapping escalation (FR-LLM-4). Mapping an
#: ambiguous form field to a stored attribute is a small reasoning task that the
#: trivial L1 rung handles poorly, so the ladder STARTS at L2 (it still climbs on
#: low confidence / overflow). This is the spec's per-task starting tier in action.
FIELD_MAPPING_START_TIER = 2


@dataclass
class PrefillResult:
    """Outcome of a (single) pre-fill pass."""

    application_id: ApplicationId
    state: ApplicationState
    sandbox_session_url: str | None = None
    #: page url -> {selector: value} for every value filled (per-page log).
    filled_by_page: dict[str, dict[str, str]] = field(default_factory=dict)
    #: selectors whose value came from the user's explicit stored answer.
    sensitive_filled_from_explicit: list[str] = field(default_factory=list)
    #: sensitive selectors that fell back to "decline to self-identify".
    sensitive_declined: list[str] = field(default_factory=list)
    #: essay screening questions deferred to Phase 3 generation (FR-ANSWER-1).
    deferred_essay_questions: list[dict] = field(default_factory=list)
    #: screening answers DRAFTED from the profile by the LLM (truthful, review-gated).
    #: ``[{selector, label, answer, url}]`` — surfaced for the user's review before
    #: any submit (FR-ANSWER-1, FR-RESUME-8).
    generated_answers: list[dict] = field(default_factory=list)
    #: résumé/CV files uploaded into ATS file inputs (FR-RESUME-4).
    #: ``[{selector, label, path, url}]`` — the base résumé attached during pre-fill.
    uploaded_documents: list[dict] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    #: page url for each screenshot in ``screenshots`` (parallel list, FR-LOG-2).
    screenshot_pages: list[str] = field(default_factory=list)
    pending_action_id: PendingActionId | None = None
    detection_signal: str | None = None
    #: the attribute name that was missing, when blocked on FR-ATTR-5.
    missing_attribute: str | None = None
    #: True once the engine reached and handed off at the account-create page.
    account_handoff: bool = False
    #: pre-filled values offered for the emergency copy/paste handoff (FR-PREFILL-7).
    handoff_values: dict[str, str] = field(default_factory=dict)
    #: running count of fillable fields DETECTED across the whole run (#177). A file
    #: input or an essay/sensitive field still COUNTS as detected — the universal-ATS
    #: match-rate measures "did the page model line up with the real form at all".
    fields_detected: int = 0
    #: running count of fields the engine actually FILLED across the whole run (#177).
    fields_filled: int = 0
    #: selectors that FAILED to fill (field-level failures).
    fields_failed: list[dict] = field(default_factory=list)
    #: True when the run was flagged as a probable wrong-ATS / near-empty fill and held
    #: for human review instead of being offered for final submission (#177).
    wrong_ats_flagged: bool = False


class PrefillService:
    def __init__(
        self,
        storage,
        browser,
        detection,
        sandbox,
        credentials,
        notification=None,
        *,
        llm=None,
        resume_provider=None,
        computer_use=None,
        required_field_types: frozenset[str] | None = None,
        allow_automated_accounts: bool = False,
        match_rate_floor: float = DEFAULT_MATCH_RATE_FLOOR,
        planner=None,
        use_planner: bool = False,
        captcha_solver=None,
        routine_store=None,
        max_replans: int = 2,
    ) -> None:
        self._storage = storage
        self._browser = browser
        self._detection = detection
        self._sandbox = sandbox
        self._credentials = credentials
        self._notification = notification
        # FR-RESUME-4: resolves the uploadable résumé file for an application (the
        # uploaded base résumé by default). Optional: absent → file inputs are skipped.
        self._resume_provider = resume_provider
        # FR-CUA: desktop-assist (computer-use) port, used ONLY to complete a native OS
        # file-picker the DOM can't satisfy during résumé/cover-letter attachment.
        # Optional/defaulted: absent — or the noop test backend / a non-operable driver —
        # degrades EXACTLY as before (skip / human hand-off). It never drives any step
        # other than the bounded file-attach (FR-CUA-3 stop-boundary stays untouched).
        self._computer_use = computer_use
        # ADR-0004: only attempt automated account creation when the operator opted in.
        self._allow_automated_accounts = bool(allow_automated_accounts)
        # LLM port for ambiguous-mapping escalation (FR-PREFILL-3). Optional: when
        # absent, an unresolved non-sensitive field becomes a missing-attr soft error.
        self._llm = llm
        # Field types that MUST be filled (a missing value soft-errors, FR-ATTR-5).
        # Optional fields just skip. Defaults to the load-bearing required ones.
        self._required_types = required_field_types or frozenset(
            {"text", "password", "select", SCREENING_FACTUAL}
        )
        # #177: minimum acceptable field-match rate (filled / detected) for a run; below
        # it (with at least one field detected) the run is flagged as a probable
        # wrong-ATS / near-empty fill for human review rather than offered for submission.
        self._match_rate_floor = float(match_rate_floor)
        # #305 Plan-as-Data: optional PlannerPort driving adapter. When ``use_planner``
        # is True AND a planner is present, each page produces a typed Plan before any
        # browser action runs. The plan is validated (validate_plan) and then executed
        # op-by-op through the existing guarded actions — the STOP boundary is still
        # enforced (consequential stop ops route through _account_handoff /
        # _reach_final_approval, never auto-submitted). Default OFF so no existing
        # behaviour changes; flip PREFILL_USE_PLANNER=true to opt in.
        self._planner = planner
        self._use_planner = bool(use_planner) and (planner is not None)
        # #350 CaptchaSolverPort: an opt-in driven port placed in FRONT of the existing
        # captcha stop-boundary hand-off. Optional/defaulted: absent (or the default
        # ``human`` strategy) means EVERY captcha still routes to the existing hand-off,
        # so behavior is byte-for-byte identical to today. Score/behavioral captchas may
        # be avoided via stealth and interactive challenges solved by token injection
        # ONLY when the operator explicitly opts in; any failure degrades to the hand-off.
        # It never bypasses the account-create / final-submit stop-boundary.
        self._captcha_solver = captcha_solver
        # #306 self-improvement flywheel: the process-lived RoutineStore (AWM
        # workflow-induction + ACE curation). Optional/defaulted: absent → the planner
        # path behaves exactly as #305 (no priors, single-shot). MUST be the SAME
        # process-lived instance across ticks (injected from container.py like the
        # resume/curation ledgers), never a per-tick instance, or induced routines
        # silently reset every tick. It influences PLANNING priors + reflective re-plan
        # ONLY — the STOP boundary / review-before-submit gates are untouched.
        self._routine_store = routine_store
        # Reflexion self-healing: how many reflective re-plans to attempt on a failed
        # op (a broken selector) before giving up to the normal fill path. Bounded so a
        # persistently-broken page never loops forever.
        self._max_replans = max(0, int(max_replans))
        # Operator-visible diagnostics for SILENT degradations (#202/#203/#211/#223):
        # a credential lookup whose tenant resolver crashed, an all-scopes vault
        # failure, an LLM-mapping outage, or a transient browser error during login —
        # each degrades gracefully (no crash) BUT must leave a trace an operator can see
        # rather than vanishing. A bounded ring of recent diagnostic strings, surfaced
        # via ``diagnostics()``; the loop also lands a pending action where it has the
        # application context to do so.
        self._diagnostics: list[str] = []

    #: Cap the in-process diagnostics ring so a persistently-failing dependency cannot
    #: grow it without bound across a long-lived service.
    _MAX_DIAGNOSTICS = 200

    def diagnostics(self) -> list[str]:
        """Recent operator-visible diagnostics for silent-degradation events.

        Credential / LLM / login failures degrade gracefully (the loop never crashes),
        but a swallowed-without-a-trace failure is invisible to the operator. Each such
        event is recorded here so it is surfaced rather than lost (#202/#203/#211/#223).
        """
        return list(self._diagnostics)

    def _record_diagnostic(self, message: str) -> None:
        """Record one operator-visible diagnostic (bounded, deduped against the last)."""
        if not message:
            return
        # Drop an immediate duplicate so one failing dependency does not spam the ring
        # (e.g. an LLM that raises on every field re-records the same outage).
        if self._diagnostics and self._diagnostics[-1] == message:
            return
        self._diagnostics.append(message)
        if len(self._diagnostics) > self._MAX_DIAGNOSTICS:
            del self._diagnostics[: -self._MAX_DIAGNOSTICS]

    # --- public API -------------------------------------------------------
    def prefill_application(
        self,
        application: Application,
        url: str,
        attributes: list[Attribute] | None = None,
        *,
        cautious: bool = True,
    ) -> PrefillResult:
        """Run the maximal pre-fill loop for ``application`` starting at ``url``.

        Returns a :class:`PrefillResult` whose ``state`` reflects where the loop
        stopped: a ``BLOCKED_*`` / ``AWAITING_*`` hand-off state, or
        ``AWAITING_FINAL_APPROVAL`` once every page is filled.
        """
        attributes = attributes or []
        aid = application.id

        # 1. Provision the isolated, ephemeral sandbox (FR-SANDBOX-1, FR-PREFILL-1).
        app = application.with_status(ApplicationState.SANDBOX_PROVISIONING)
        session = self._sandbox.provision(aid)
        # Session-continuity handoff (FR-PREFILL-5 / FR-SANDBOX-3): when the remote
        # view is the full webtop desktop, tell it which application URL to open so the
        # human takes over the SAME application the agent was filling. Best-effort and
        # signature-stable: only the webtop adapter exposes ``bind_application_url``.
        session_url = session.remote_view_url
        remote_view = getattr(self._sandbox, "remote_view", None)
        if callable(remote_view):
            rv = remote_view()
            bind = getattr(rv, "bind_application_url", None)
            if callable(bind):
                bind(session.session_id, url)
                session_url = rv.view_url(session.session_id)
        result = PrefillResult(
            application_id=aid,
            state=app.status,
            sandbox_session_url=session_url,
        )

        # 2. Open the first page. For the native Proxmox Windows backend the session
        # carries a CDP endpoint to the remote Windows VM's Chrome — the engine
        # connects to THAT real browser over CDP (genuine Windows fingerprint, no
        # spoof) instead of launching a local one. For the local backend it is None
        # and the local-launch path is unchanged. The kwarg is passed only when the
        # session actually carries an endpoint (signature-stable for fake browsers).
        cdp_endpoint = getattr(session, "cdp_endpoint", None)
        if cdp_endpoint:
            self._browser.open(aid, url, cdp_endpoint=cdp_endpoint)
        else:
            self._browser.open(aid, url)

        # 2b. Move from the job posting/landing page INTO the application flow (click
        # "Apply"). A no-op when the URL already lands inside the flow, or for the
        # in-memory fake source (FR-PREFILL-1). Without this the engine inspects the
        # posting page (no form fields) and finishes having filled nothing. Signature-
        # stable: a minimal stub browser without this method simply skips the entry.
        enter_application = getattr(self._browser, "enter_application", None)
        if callable(enter_application):
            enter_application(aid)

        # 3. Account GATE (sign-in OR create-account) → pre-fill what we can, then hand
        # off (FR-PREFILL-4). Broader than create-only: a Workday account step often
        # shows sign-in *options* (incl. OAuth "Sign in with Google", which the engine
        # cannot drive) before any field, so the loop must hand off here rather than
        # mistake a field-less gate for 'done'. Signature-stable: a minimal stub browser
        # without is_account_gate falls back to the create-only check.
        if self._on_account_gate(aid):
            app = app.with_status(ApplicationState.ACCOUNT_PREFILL)
            # FR-PREFILL-6: run a cautious detection check BEFORE filling the account
            # page — a CAPTCHA/Cloudflare/etc. there must pause + hand off, never fill.
            # The account context's legal hand-off is the account human step (the user
            # takes over the live session to clear the challenge + create the account).
            if cautious:
                event = self._check_detection(aid)
                if event is not None:
                    result.detection_signal = event.signal_type
                    # #3 (FR-PREFILL-5): pass the BOUND session url (carries ``&app=``
                    # continuity) — not the pre-binding ``session.remote_view_url``
                    # snapshot — so the takeover link lands on the same application.
                    return self._account_handoff(
                        app, result, result.sandbox_session_url, signal_type=event.signal_type
                    )
            # Automate-by-default: if we hold a stored credential for this ATS, log in
            # ourselves (email/password) and proceed straight to the form — no per-
            # application human sign-in. Login failure / no credential / OAuth fall
            # through to the human hand-off below (which the persistent session + the
            # 2FA flow build on next).
            credential = self._lookup_credential(app)
            if credential is not None and self._try_log_in(aid, credential):
                self._capture_screenshot(aid, result)
                return self._prefill_pages(app, attributes, result, cautious=cautious)
            # "Sign in with Google" (OAuth): a persistent Google session usually clicks
            # straight through; if Google demands 2FA, the engine cannot produce the
            # second factor → run the 2FA notify/continue/retry hand-off.
            google = self._lookup_credential(app, tenant_key=GOOGLE_CREDENTIAL_KEY)
            if google is not None and self._offers_google(aid):
                status = self._try_google_login(aid, google)
                if status == "ok":
                    self._capture_screenshot(aid, result)
                    return self._prefill_pages(app, attributes, result, cautious=cautious)
                if status == "two_factor":
                    return self._two_factor_handoff(app, result)
                # "failed" → fall through (try account creation / hand off).
            # No working login: create an account from the predefined set if the
            # operator opted in (ADR-0004). On success continue; if it triggers email
            # verification, bank the credential and hand off (verify is irreducible).
            created = self._maybe_create_account(app)
            if created == "ok":
                self._capture_screenshot(aid, result)
                return self._prefill_pages(app, attributes, result, cautious=cautious)
            if created == "email_verify":
                self._capture_screenshot(aid, result)
                return self._account_handoff(app, result, result.sandbox_session_url)
            blocked = self._fill_current_page(
                app, attributes, result, block_on_missing=False
            )
            if blocked is not None:
                return blocked
            self._capture_screenshot(aid, result)
            # The engine never clicks the account-creating submit — hand off.
            # #3: use the bound ``result.sandbox_session_url`` (with ``&app=``), not the
            # pre-binding ``session.remote_view_url``.
            return self._account_handoff(app, result, result.sandbox_session_url)

        # 4. No account needed → straight to pre-filling.
        return self._prefill_pages(app, attributes, result, cautious=cautious)

    def resume_after_account(
        self,
        application: Application,
        attributes: list[Attribute] | None = None,
        *,
        cautious: bool = True,
    ) -> PrefillResult:
        """Continue pre-filling after the user completed the account step.

        Transitions AWAITING_ACCOUNT_HUMAN_STEP -> PREFILLING and walks the
        remaining pages. Assumes the browser session for the application is open.
        """
        attributes = attributes or []
        app = application.with_status(ApplicationState.PREFILLING)
        result = PrefillResult(
            application_id=application.id,
            state=app.status,
            sandbox_session_url=application.sandbox_session_url,
        )
        # Advance past the account page to the next application page.
        self._browser.advance(application.id)
        return self._continue_pages(app, attributes, result, cautious=cautious)

    def resume_two_factor(
        self,
        application: Application,
        attributes: list[Attribute] | None = None,
        *,
        timeout_s: float = 60.0,
        poll_s: float = 2.0,
        cautious: bool = True,
    ) -> PrefillResult:
        """Resume a Google 2FA hand-off after the user taps "continue".

        Triggers the 2FA push (re-drives the Google sign-in so Google sends the prompt
        to the user's device), then waits up to ``timeout_s`` for approval — detected by
        the page leaving the account gate. On approval → continue into the form; on
        timeout → emit a retry notification and stay held so the user can tap again.
        Assumes the held browser session is still open."""
        attributes = attributes or []
        aid = application.id
        result = PrefillResult(
            application_id=aid,
            state=application.status,
            sandbox_session_url=application.sandbox_session_url,
        )
        # Trigger the push: re-drive the Google sign-in (sends the 2FA prompt).
        google = self._lookup_credential(application, tenant_key=GOOGLE_CREDENTIAL_KEY)
        if google is not None:
            self._try_google_login(aid, google)
        # Poll for the user's on-device approval (the gate clears once approved).
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            if not self._on_account_gate(aid):
                app = application.with_status(ApplicationState.PREFILLING)
                result.state = app.status
                return self._continue_pages(app, attributes, result, cautious=cautious)
            if time.monotonic() >= deadline:
                break
            time.sleep(max(0.0, poll_s))
        # Timed out waiting for 2FA → re-notify for a retry; the app stays held.
        result.state = application.status
        result.pending_action_id = self._emit_waiting(
            application=application,
            kind="two_factor",
            title="Two-factor sign-in timed out — tap to try Google again",
            session_url=result.sandbox_session_url,
            payload={"provider": "google", "action": "continue_two_factor", "retry": True},
        )
        return result

    def resume_after_detection(
        self,
        application: Application,
        attributes: list[Attribute] | None = None,
        *,
        cautious: bool = True,
    ) -> PrefillResult:
        """Continue pre-filling after the user cleared a detection challenge (FR-PREFILL-6).

        #2: an app parked at BLOCKED_DETECTION may legally transition ONLY ->
        PREFILLING (§7). The old re-drive routed through ``prefill_application`` whose
        first move is ``with_status(SANDBOX_PROVISIONING)`` — an ILLEGAL transition
        from BLOCKED_DETECTION that raised IllegalStateTransition (swallowed; the app
        stranded with no resolver). This resumes via the legal PREFILLING transition
        and does NOT tear down / re-provision the live session the user just cleared.
        Subsequent re-drives are non-cautious so the same (now-cleared) signal does not
        immediately re-block the resume.
        """
        attributes = attributes or []
        app = application.with_status(ApplicationState.PREFILLING)
        result = PrefillResult(
            application_id=application.id,
            state=app.status,
            sandbox_session_url=application.sandbox_session_url,
        )
        return self._continue_pages(app, attributes, result, cautious=cautious)

    def resume_after_missing_attr(
        self,
        application: Application,
        attributes: list[Attribute],
        *,
        cautious: bool = True,
    ) -> PrefillResult:
        """Continue pre-filling after the user supplied a missing attribute (FR-ATTR-5).

        The newly-acquired value is reused per campaign, so the same field now fills
        and the loop proceeds from the page it stalled on.
        """
        app = application.with_status(ApplicationState.PREFILLING)
        result = PrefillResult(
            application_id=application.id,
            state=app.status,
            sandbox_session_url=application.sandbox_session_url,
        )
        return self._continue_pages(app, attributes, result, cautious=cautious)

    def emergency_handoff(
        self,
        application: Application,
        attributes: list[Attribute] | None = None,
        *,
        kind: str = "emergency_handoff",
        title: str = "Emergency handoff + mark submitted",
        extra_payload: dict | None = None,
    ) -> PrefillResult:
        """Emergency copy/paste handoff — ONLY after a reported fill failure (FR-PREFILL-7).

        This is never the default path: it is invoked when the agent reports it
        tried to fill and failed. It assembles the values the user can paste into
        their own browser and lands the EMERGENCY_DATA_HANDOFF waiting state.

        ``kind``/``title``/``extra_payload`` let a more specific fill-failure signal
        (``flag_probable_wrong_ats`` — a near-empty fill, #177) reuse this exact
        value-assembly + transition + pending action while keeping its own pending
        action identity and diagnostic payload, instead of duplicating the logic.
        """
        attributes = attributes or []
        # The agent reports it tried to fill and failed while PREFILLING; if the
        # caller passes an earlier state, normalize to PREFILLING first.
        app = application
        if app.status is not ApplicationState.PREFILLING:
            app = app.with_status(ApplicationState.PREFILLING)
        # Best-effort assemble the values that WOULD have been filled, for paste —
        # never let a browser/detection hiccup at this late stage crash the loop
        # (mirrors every other soft-degrade path in this service).
        values: dict[str, str] = {}
        try:
            for fld in self._browser.detect_fields(application.id):
                resolved = self._resolve_value(
                    fld, attributes, PrefillResult(application.id, app.status)
                )
                if resolved.value is not None and not resolved.defer_essay:
                    values[fld.label] = resolved.value
        except Exception:  # noqa: BLE001 — never crash assembling the paste set
            log.debug("emergency_handoff: field assembly failed", exc_info=True)
        app = app.with_status(ApplicationState.EMERGENCY_DATA_HANDOFF)
        result = PrefillResult(
            application_id=application.id,
            state=app.status,
            sandbox_session_url=application.sandbox_session_url,
            handoff_values=values,
        )
        payload = {"handoff_values": values}
        if extra_payload:
            payload.update(extra_payload)
        result.pending_action_id = self._emit_waiting(
            application=app,
            kind=kind,
            title=title,
            session_url=application.sandbox_session_url,
            payload=payload,
        )
        self._persist(app)
        return result

    def await_final_approval(self, orchestrator, workflow_id: str, *, timeout: float | None = None):
        """Block on the durable approval gate (FR-NOTIF-2, FR-DUR-3).

        Uses ``DurableOrchestrationPort.recv`` (which already accepts ``timeout``)
        so a crash resumes the wait. Returns the approval payload, or ``None`` on
        timeout (the caller then re-notifies via the escalation ladder).
        """
        return orchestrator.recv(workflow_id, FINAL_APPROVAL_TOPIC, timeout=timeout)

    # --- internal loop ----------------------------------------------------
    def _prefill_pages(self, app, attributes, result, *, cautious):
        app = app.with_status(ApplicationState.PREFILLING)
        result.state = app.status
        return self._continue_pages(app, attributes, result, cautious=cautious)

    def _continue_pages(self, app, attributes, result, *, cautious):
        # #207 / #336 browser-crash recovery: the page walk drives a real browser whose
        # tab/context can vanish (TargetClosedError) or hang (TimeoutError) mid-flow.
        # Without a boundary here the raw exception escapes to the orchestrator — no
        # PrefillResult, no FAILED state, no pending action — so a crashed application is
        # stranded with nothing to resume from. Catch any browser error from the walk and
        # land a structured FAILED result (§7: "any unrecoverable error -> FAILED").
        try:
            return self._walk_pages(app, attributes, result, cautious=cautious)
        except Exception as exc:  # noqa: BLE001 — a dead browser must not escape the loop
            log.warning(
                "Pre-fill page walk crashed for application %s — returning a FAILED "
                "result instead of propagating",
                app.id,
                exc_info=True,
            )
            return self._failed_prefill(app, result, exc)

    def _failed_prefill(self, app, result, exc: Exception) -> PrefillResult:
        """Land a structured FAILED :class:`PrefillResult` after a browser crash (#207/#336).

        Records a diagnostic + an error pending action so the operator sees WHY the
        application failed (a dead tab / hung operation), then transitions to the §7
        terminal ``FAILED`` state. Defensive: emitting the trail must never re-raise.
        """
        self._record_diagnostic(
            f"Pre-fill browser crashed for application {app.id}: {exc}"
        )
        try:
            self._emit_error(
                app,
                title="Pre-fill failed — the automation browser stopped responding",
                detail=str(exc),
                selector=f"browser:{app.id}",
            )
        except Exception:  # noqa: BLE001 — error-trail emission must never crash recovery
            log.debug("Failed to emit browser-crash error action", exc_info=True)
        try:
            app = app.with_status(ApplicationState.FAILED)
            self._persist(app)
        except Exception:  # noqa: BLE001 — even an illegal transition must not re-raise
            log.debug("Failed to persist FAILED transition", exc_info=True)
        result.state = ApplicationState.FAILED
        return result

    def _walk_pages(self, app, attributes, result, *, cautious):
        aid = app.id
        while True:
            # Cautious mode: pause on a detection signal BEFORE filling (FR-PREFILL-6).
            if cautious:
                event = self._check_detection(aid)
                if event is not None:
                    return self._blocked_detection(app, result, event)

            # FR-PREFILL-4: a mid-flow account-creation page (not just the first page)
            # must hand off to the human — the engine NEVER fills/advances past an
            # account-create step on its own. We pre-fill what we can (still in
            # PREFILLING), then hand off (PREFILLING -> AWAITING_ACCOUNT_HUMAN_STEP).
            if self._browser.is_account_create_page(aid):
                blocked = self._fill_current_page(app, attributes, result)
                if blocked is not None:
                    return blocked
                self._capture_screenshot(aid, result)
                return self._account_handoff(app, result, result.sandbox_session_url)

            # #305 Plan-as-Data: when a planner is configured and enabled (OFF by
            # default), emit a typed plan for this page and execute each op through
            # the existing guarded actions. Stop ops are routed through the same
            # hand-off paths as the non-planner loop — the STOP boundary is intact.
            if self._use_planner:
                planner_result = self._execute_plan_for_page(app, attributes, result)
                if planner_result is not None:
                    return planner_result
            else:
                # Pre-fill every fillable field on this page FIRST (maximal pre-fill).
                # A SINGLE-PAGE application (Greenhouse / Lever / Ashby) has the whole
                # form AND the Submit button on one page, so filling must happen BEFORE
                # we decide the page is the final-submit page — otherwise the engine
                # sees "Submit Application" and skips the entire form (universal-ATS
                # support, FR-PREFILL-2/3).
                blocked = self._fill_current_page(app, attributes, result)
                if blocked is not None:
                    # G11 #177: Log ATS type on prefill failure for diagnostics.
                    from applicant.adapters.browser.ats import resolve_ats
                    try:
                        state = self._browser.current_state(aid)
                        ats_type = type(resolve_ats(state.url)).__name__ if state and state.url else "unknown"
                    except Exception:
                        ats_type = "unknown"
                    log.warning(
                        "Prefill blocked on ATS %s — state=%s missing_attr=%s",
                        ats_type, blocked.state, blocked.missing_attribute,
                    )
                    return blocked
            self._capture_screenshot(aid, result)

            # Now stop at the final review/submit page (the engine never clicks the
            # final submit), otherwise advance to the next page; no next page → done.
            if self._browser.is_final_submit_page(aid):
                return self._reach_final_approval(app, result, attributes)
            if self._browser.advance(aid) is None:
                return self._reach_final_approval(app, result, attributes)

    @staticmethod
    def _routine_domain(url: str) -> str:
        """Derive the routine key (ATS tenant / host) from a page URL (#306).

        Keyed by the registrable host so routines learned on one tenant's pages are
        reused across that tenant's pages. Best-effort: a bare/relative URL falls back
        to the raw string so the key is at least stable.
        """
        from urllib.parse import urlparse

        try:
            host = urlparse(url).netloc
        except Exception:  # noqa: BLE001 — never crash deriving a key
            host = ""
        return (host or url or "").lower()

    def _execute_plan_for_page(self, app, attributes, result) -> PrefillResult | None:
        """#305 Plan-as-Data + #306 flywheel: emit, ground, and execute a typed Plan.

        Builds the attribute cloud, asks the planner for a Plan — **injecting any
        stored routine for this domain as an AWM prior** (#306) — validates it, then
        executes each op through the existing guarded actions. On a broken op (a
        broken selector) it captures a short **reflection** and runs a bounded
        **reflective re-plan** (Reflexion) so a broken selector re-plans rather than
        dead-stops. On a clean success it **induces** a reusable routine for the
        domain (AWM) and up-weights it (ACE); on a re-plan it down-weights the prior
        (ACE), pruning a stale routine that stops working.

        Stop ops (account_create, captcha, final_submit, ...) are routed through the
        same hand-off paths as the non-planner loop so the STOP boundary is intact.

        Returns ``None`` when the page was filled successfully (caller proceeds to
        advance), or a terminated :class:`PrefillResult` on a stop/block.
        """
        from applicant.core.rules.plan import (
            resolve_fill_values,
            validate_plan,
        )
        from applicant.ports.driving.planner import PlannerInput, PlannerObservation

        aid = app.id
        state = self._browser.current_state(aid)
        if state is None:
            log.warning(
                "PlannerPath: current_state() returned None for application %s — "
                "falling back to non-planner fill",
                aid,
            )
            return self._fill_current_page(app, attributes, result)

        # Build the attribute cloud (attribute_id -> value) for validation + resolution.
        attribute_cloud: dict[str, str] = {}
        for attr in (attributes or []):
            if attr.name and attr.value is not None:
                attribute_cloud[attr.name] = str(attr.value)
        known_ids = frozenset(attribute_cloud.keys())

        # #306 AWM prior-injection: render the routine that worked on this domain
        # before (if any) as a planning prior. Data only (op kinds + ids/locators),
        # never a literal value — it cannot leak a fabricated answer into the plan.
        domain = self._routine_domain(state.url)
        prior_routine = self._prior_routine_text(domain)

        observation = PlannerObservation(
            url=state.url,
            html_summary=state.body or "",
            snapshot_tokens=len(state.body or "") // 4,
        )

        # Reflexion re-plan loop: first pass injects the prior; subsequent passes
        # carry the reflection captured from the failed op. Bounded by ``max_replans``.
        reflection: str | None = None
        for attempt in range(1 + self._max_replans):
            planner_input = PlannerInput(
                goal="fill all form fields on this page",
                observation=observation,
                facts={k: k for k in known_ids},  # id -> label (planner uses labels)
                prior_routine=prior_routine if attempt == 0 else None,
                reflection=reflection,
                failure_reason=reflection,  # keep the existing single-line path populated too
            )

            try:
                plan = self._planner.plan(planner_input)
            except Exception:
                log.warning(
                    "PlannerPath: planner.plan() raised for application %s — "
                    "falling back to non-planner fill",
                    aid,
                    exc_info=True,
                )
                return self._fill_current_page(app, attributes, result)

            # An empty plan falls back to the non-planner loop (planner couldn't help).
            if not plan or len(plan) == 0:
                log.debug(
                    "PlannerPath: empty plan for application %s page %s — "
                    "falling back to non-planner fill",
                    aid, state.url,
                )
                return self._fill_current_page(app, attributes, result)

            # Validate before any execution (NFR-TRUTH-1, FR-PREFILL-4).
            errors = validate_plan(plan, known_ids)
            if errors:
                log.warning(
                    "PlannerPath: invalid plan for application %s page %s (%d error(s)) — "
                    "falling back to non-planner fill: %s",
                    aid, state.url, len(errors), errors[0],
                )
                return self._fill_current_page(app, attributes, result)

            fill_values = resolve_fill_values(plan, attribute_cloud)
            terminal, reflection, induced_steps = self._run_plan_ops(
                app, state, plan, fill_values, result, attributes
            )
            if reflection is None:
                # Clean execution (whether the page ended naturally or at a benign
                # final_submit / hand-off StopOp) — #306 AWM induction: store the
                # op-sequence that worked, keyed by domain, and ACE-up-weight a reused
                # routine. The STOP boundary is untouched: this only records what to
                # PLAN next time; the terminal hand-off below is returned unchanged.
                self._induce_routine(domain, induced_steps, reused=prior_routine is not None)
                return terminal  # terminal (final_submit / hand-off) or None (page done)
            # A broken op produced a reflection. ACE: down-weight (and maybe prune) the
            # prior routine that mis-grounded, then reflectively re-plan if budget remains.
            if prior_routine is not None and self._routine_store is not None:
                try:
                    self._routine_store.record_failure(domain)
                except Exception:  # noqa: BLE001 — curation must never crash the loop
                    log.debug("RoutineStore.record_failure failed", exc_info=True)
                prior_routine = None  # don't re-inject a prior that just mis-grounded
            log.info(
                "PlannerPath: reflective re-plan %d/%d for application %s: %s",
                attempt + 1, self._max_replans, aid, reflection,
            )

        # Exhausted the re-plan budget — fall back to the deterministic fill path so
        # the page still gets a best-effort pass (never a silent dead stop).
        log.warning(
            "PlannerPath: re-plan budget exhausted for application %s page %s — "
            "falling back to non-planner fill",
            aid, state.url,
        )
        return self._fill_current_page(app, attributes, result)

    def _run_plan_ops(self, app, state, plan, fill_values, result, attributes=None):
        """Execute one plan's ops, honouring the STOP boundary.

        Returns ``(terminal, reflection, steps)``:
        * ``terminal`` — a terminated :class:`PrefillResult` (stop/handoff) or ``None``.
        * ``reflection`` — a short Reflexion note when an op (a broken selector) failed,
          else ``None`` (clean execution). A non-None reflection signals the caller to
          reflectively re-plan.
        * ``steps`` — the :class:`RoutineStep` sequence that executed cleanly, for AWM
          induction (only meaningful when ``reflection`` is ``None``).
        """
        from applicant.core.entities.plan import (
            ClickOp,
            FillOp,
            OpKind,
            SelectOp,
            StopOp,
        )
        from applicant.ports.driven.routine_store import RoutineStep

        aid = app.id
        page_log: dict[str, str] = {}
        steps: list[RoutineStep] = []

        for op in plan:
            kind = op.kind

            if kind == OpKind.FILL and isinstance(op, FillOp):
                value = fill_values.get(op.ref)
                if value is None:
                    continue  # attribute not resolvable; skip this op
                try:
                    self._browser.fill_field(aid, op.ref, value)
                    page_log[op.ref] = value
                    result.fields_filled += 1
                    steps.append(RoutineStep(
                        kind=OpKind.FILL.value, ref=op.ref, attribute_id=op.attribute_id
                    ))
                except Exception as exc:  # noqa: BLE001
                    self._emit_error(
                        app,
                        title=f"Planner: could not fill field ref={op.ref!r}",
                        detail=str(exc),
                        selector=op.ref,
                    )
                    page_log[op.ref] = f"__FAILED__:{exc}"
                    result.fields_failed.append({
                        "selector": op.ref,
                        "label": op.attribute_id,
                        "url": state.url,
                        "error": str(exc),
                    })
                    # #306 Reflexion: a broken selector → reflect + signal re-plan.
                    reflection = (
                        f"fill on ref={op.ref!r} (attribute_id={op.attribute_id!r}) "
                        f"failed: {exc}. The locator is likely broken/stale — try a "
                        f"different way to find this field on the current DOM."
                    )
                    if page_log:
                        result.filled_by_page[state.url] = page_log
                    return None, reflection, ()

            elif kind == OpKind.SELECT and isinstance(op, SelectOp):
                value = fill_values.get(op.ref)
                if value is None:
                    continue
                try:
                    self._browser.fill_field(aid, op.ref, value)
                    page_log[op.ref] = value
                    result.fields_filled += 1
                    steps.append(RoutineStep(
                        kind=OpKind.SELECT.value, ref=op.ref, attribute_id=op.attribute_id
                    ))
                except Exception as exc:  # noqa: BLE001
                    self._emit_error(
                        app,
                        title=f"Planner: could not select field ref={op.ref!r}",
                        detail=str(exc),
                        selector=op.ref,
                    )
                    reflection = (
                        f"select on ref={op.ref!r} (attribute_id={op.attribute_id!r}) "
                        f"failed: {exc}. The locator is likely broken/stale — try a "
                        f"different way to find this control on the current DOM."
                    )
                    if page_log:
                        result.filled_by_page[state.url] = page_log
                    return None, reflection, ()

            elif kind == OpKind.CLICK and isinstance(op, ClickOp):
                # Clicks are allowed for navigation (e.g. "Next" buttons).
                # The STOP boundary: if this click would submit the application,
                # the planner should have emitted a StopOp instead — but for
                # defence in depth, any click on a final-submit/account-create
                # element is blocked by is_final_submit_page / is_account_create_page
                # checks in the outer _continue_pages loop.
                try:
                    self._browser.click(aid, op.ref)
                    steps.append(RoutineStep(kind=OpKind.CLICK.value, ref=op.ref))
                except Exception as exc:  # noqa: BLE001
                    log.debug(
                        "PlannerPath: click ref=%r failed: %s", op.ref, exc
                    )

            elif kind == OpKind.STOP and isinstance(op, StopOp):
                # The planner emitted a stop — honour the STOP boundary.
                reason = op.reason
                if reason in ("final_submit",):
                    return self._reach_final_approval(app, result, attributes), None, tuple(steps)
                elif reason in ("account_create", "email_verify", "two_factor", "sms_verify"):
                    return self._account_handoff(app, result, result.sandbox_session_url), None, tuple(steps)
                elif reason in ("captcha", "oauth"):
                    # #350: route a captcha through the opt-in solver port FIRST. With the
                    # default config (no solver / ``human`` strategy) this is a no-op and we
                    # fall straight through to the existing hand-off below — byte-for-byte
                    # today's behavior. Only an explicitly opted-in avoid/solve can continue
                    # the page; a failed/disabled solve falls back to the same hand-off.
                    if reason == "captcha" and self._try_solve_captcha(app, state):
                        continue
                    # Emit a detection-style blocked state.
                    from applicant.core.entities.pending_action import PendingAction
                    from applicant.core.ids import PendingActionId
                    result.detection_signal = reason
                    pending_action = PendingAction(
                        id=PendingActionId(new_id()),
                        campaign_id=app.campaign_id,
                        application_id=app.id,
                        kind="blocked_detection",
                        title="Detection blocker — take over",
                        payload={"signal_type": reason, "url": state.url},
                    )
                    if self._notification:
                        from applicant.ports.driven.notification import (
                            Notification,
                            NotificationUrgency,
                        )

                        try:
                            self._notification.notify(
                                Notification(
                                    title="Detection blocker — take over",
                                    body=f"Application {app.id} is blocked by a detection signal ({reason}) and needs you.",
                                    deep_link=result.sandbox_session_url,
                                    urgency=NotificationUrgency.CRITICAL,
                                    dedup_key=ping_dedup_key(app.id, "blocked_detection"),
                                )
                            )
                        except Exception:  # noqa: BLE001
                            pass
                    result.pending_action_id = pending_action.id
                    result.state = ApplicationState.BLOCKED_DETECTION
                    return result, None, tuple(steps)
                else:
                    # Unknown stop reason — treat as a generic block.
                    log.warning(
                        "PlannerPath: unrecognised stop reason %r for application %s",
                        reason, aid,
                    )
                    result.state = ApplicationState.AWAITING_HUMAN_PREFILL
                    return result, None, tuple(steps)

            # GOTO, FIND, EXTRACT, ASSERT, WAIT — informational / navigation;
            # executed as no-ops here (the real browser path handles navigation
            # through the PageSource interface, not via raw goto ops).

        if page_log:
            result.filled_by_page[state.url] = page_log

        return None, None, tuple(steps)

    def _prior_routine_text(self, domain: str) -> str | None:
        """Return the AWM prior-routine prompt text for ``domain``, or ``None``.

        Defensive: no store wired / no live routine / any error → ``None`` so the
        planner cleanly falls back to a cold plan. A pruned routine returns ``None``
        (the store dropped it), so a stale routine is never injected (ACE).
        """
        store = self._routine_store
        if store is None or not domain:
            return None
        try:
            routine = store.get(domain)
        except Exception:  # noqa: BLE001 — priors must never crash the loop
            log.debug("RoutineStore.get failed for %s", domain, exc_info=True)
            return None
        if routine is None or not routine.steps:
            return None
        return routine.as_prior_text()

    def _induce_routine(self, domain: str, steps, *, reused: bool) -> None:
        """#306 AWM workflow-induction: store the op-sequence that worked for ``domain``.

        Best-effort + defensive: no store / empty trace / any error → no-op. When the
        page was filled by REUSING an injected prior, up-weight that routine (ACE) AND
        refresh it with the latest working trace (``induce`` counts a success).

        Routed through ``LearningService.induce_workflow`` (a ``@staticmethod``, so no
        ``LearningService`` instance construction is needed here) rather than calling
        ``routine_store.induce`` directly — dark-engine audit #45 flagged
        ``induce_workflow`` as a zero-caller wrapper; this is that call site.
        """
        store = self._routine_store
        if store is None or not domain or not steps:
            return
        try:
            from applicant.application.services.learning_service import LearningService

            LearningService.induce_workflow(store, domain, tuple(steps))
        except Exception:  # noqa: BLE001 — induction must never crash the loop
            log.debug("RoutineStore.induce failed for %s", domain, exc_info=True)

    def list_routines(self) -> list[dict]:
        """List every induced per-ATS routine for the admin/Mind read-model (audit #45).

        Reads the SAME process-lived ``RoutineStore`` the running loop writes to
        (``_induce_routine`` above) and reads from as planning priors
        (``_prior_routine_text``), so this always reflects the live loop state, not a
        stale snapshot. Returns an empty list (never an error) when no store is wired.
        """
        store = self._routine_store
        if store is None:
            return []
        rows: list[dict] = []
        try:
            domains = store.all_domains()
        except Exception:  # noqa: BLE001 — introspection must never crash the caller
            log.debug("RoutineStore.all_domains failed", exc_info=True)
            return []
        for domain in domains:
            try:
                routine = store.get(domain)
            except Exception:  # noqa: BLE001
                log.debug("RoutineStore.get failed for %s", domain, exc_info=True)
                continue
            if routine is None:
                continue
            rows.append({
                "domain": routine.domain,
                "step_count": len(routine.steps),
                "successes": routine.successes,
                "failures": routine.failures,
                "score": routine.score,
                "source": routine.source,
            })
        rows.sort(key=lambda r: (-r["score"], r["domain"]))
        return rows

    def _try_solve_captcha(self, app, state) -> bool:
        """#350: route a detected captcha through the opt-in solver port.

        Returns True ONLY when the captcha was resolved (avoided via stealth, or solved
        by token injection) so the caller may CONTINUE the page. Returns False — with no
        side effects — when there is no solver, the strategy is the default hand-off, the
        captcha is unsupported, or the solve failed; the caller then runs the EXISTING
        stop-boundary hand-off. So with the shipped defaults this always returns False
        and behavior is byte-for-byte identical to today.

        This never advances past the account-create / final-submit boundary — those are
        separate stop reasons handled above; this only ever resolves the captcha gate.
        """
        solver = self._captcha_solver
        if solver is None:
            return False
        try:
            from applicant.adapters.captcha.context import build_captcha_context
            from applicant.ports.driven.captcha import CaptchaDisposition

            context = build_captcha_context(state)
            outcome = solver.resolve(context)
        except Exception:  # noqa: BLE001 — a solver failure must degrade to the hand-off
            log.warning(
                "captcha solver raised for application %s — falling back to hand-off",
                app.id,
                exc_info=True,
            )
            return False
        if outcome.disposition in (CaptchaDisposition.AVOID,) and not outcome.solved:
            # Score/behavioral: proceed without a token (stealth already minimizes risk).
            log.info("captcha avoided for application %s: %s", app.id, outcome.detail)
            return True
        if outcome.solved:
            log.info("captcha solved for application %s: %s", app.id, outcome.detail)
            return True
        # HANDOFF (or any unsolved outcome): defer to the existing stop-boundary.
        return False

    def _lookup_credential(self, app, *, tenant_key: str | None = None):
        """Retrieve a stored credential, or ``None``. Defaults to the application's ATS
        tenant; pass ``tenant_key`` (e.g. ``GOOGLE_CREDENTIAL_KEY``) for a shared one.

        Defensive: no vault wired / no tenant key resolvable / nothing stored → None,
        so the caller cleanly falls back to the human hand-off."""
        store = self._credentials
        if store is None:
            return None
        if tenant_key is None:
            tenant_of = getattr(self._browser, "tenant_key", None)
            if not callable(tenant_of):
                return None
            try:
                tenant_key = tenant_of(app.id)
            except Exception as exc:  # noqa: BLE001 — degrade gracefully, but surface it
                log.warning(
                    "tenant_of() failed for application %s — credential lookup degraded",
                    app.id,
                    exc_info=True,
                )
                # #202: a CRASHED tenant resolver is not the same as a genuinely absent
                # tenant — record a diagnostic the operator can see so the failure does
                # not vanish silently (the lookup still degrades to None / hand-off).
                self._record_diagnostic(
                    f"Credential tenant lookup failed for application {app.id}: {exc}"
                )
                return None
        if not tenant_key:
            return None
        # Per-tenant ATS credentials live under the application's campaign. The shared
        # account credentials (Google / the default new-account set) are global: a
        # campaign-specific entry still wins as an override, but we fall back to the
        # SYSTEM campaign so a single Settings entry applies to every job search.
        scopes = [app.campaign_id]
        if tenant_key in SHARED_CREDENTIAL_KEYS:
            from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId

            scopes.append(CampaignId(SYSTEM_CAMPAIGN_ID))
        scopes_failed = 0
        last_error: Exception | None = None
        for scope in scopes:
            try:
                cred = store.retrieve(scope, tenant_key)
            except Exception as exc:  # noqa: BLE001 — a failing scope must not stop the rest
                log.warning("Credential lookup failed for scope %s key %s", scope, tenant_key, exc_info=True)
                scopes_failed += 1
                last_error = exc
                cred = None
            if cred is not None:
                return cred
        # #203: when EVERY scope raised (vs. simply held nothing) the vault is failing,
        # not empty — surface a diagnostic so a transient/total outage is not mistaken
        # for "no credential stored". A single working scope above already returned.
        if scopes_failed and scopes_failed == len(scopes):
            self._record_diagnostic(
                f"Every credential scope failed for tenant {tenant_key!r} "
                f"(vault unreachable): {last_error}"
            )
        return None

    def _try_log_in(self, aid, credential) -> bool:
        """Attempt an email/password sign-in from a stored credential; return success.

        Signature-stable: a browser without ``log_in`` (a minimal stub) returns False,
        so the flow falls back to the hand-off."""
        log_in = getattr(self._browser, "log_in", None)
        if not callable(log_in):
            return False
        try:
            return bool(log_in(aid, credential.username, credential.secret))
        except Exception as exc:  # noqa: BLE001 — degrade to hand-off, but distinguish it
            log.warning(
                "Login attempt failed for application %s — probable browser crash or "
                "connection error, not a wrong-password rejection",
                aid,
                exc_info=True,
            )
            # #223: a transient browser/CDP error during login is NOT a wrong password —
            # both currently degrade to the same hand-off (return False), so without a
            # diagnostic the operator cannot tell "the session crashed" from "bad creds".
            # Record the browser error so the two are distinguishable.
            self._record_diagnostic(
                f"Browser error during login for application {aid} "
                f"(transient, not an auth rejection): {exc}"
            )
            return False

    def _on_account_gate(self, aid) -> bool:
        """Whether the current page is the account gate (sign-in OR create-account).
        Signature-stable: falls back to the create-only check for minimal stubs."""
        gate = getattr(self._browser, "is_account_gate", None)
        try:
            if callable(gate):
                return bool(gate(aid))
            return bool(self._browser.is_account_create_page(aid))
        except Exception:  # pragma: no cover - defensive
            return False

    def _offers_google(self, aid) -> bool:
        """Whether the gate offers OAuth 'Sign in with Google' (defensive)."""
        offers = getattr(self._browser, "offers_google_signin", None)
        if not callable(offers):
            return False
        try:
            return bool(offers(aid))
        except Exception:  # pragma: no cover - defensive
            return False

    def _try_google_login(self, aid, credential) -> str:
        """Drive 'Sign in with Google' from a stored Google credential. Returns
        'ok' | 'two_factor' | 'failed' (defensive: a stub browser → 'failed')."""
        login = getattr(self._browser, "log_in_with_google", None)
        if not callable(login):
            return "failed"
        try:
            return str(login(aid, credential.username, credential.secret))
        except Exception:  # pragma: no cover - defensive
            return "failed"

    def _maybe_create_account(self, app) -> str | None:
        """Create an account from the predefined set if enabled (ADR-0004). Returns
        'ok' | 'email_verify' on a created account (credential banked), else ``None``
        (not enabled / no predefined set / stub browser / creation failed → hand off)."""
        # Per-tenant credential allowance (#175): if a stored credential already
        # exists for this tenant, allow account creation without the global opt-in.
        tenant_of = getattr(self._browser, "tenant_key", None)
        tenant_key = tenant_of(app.id) if callable(tenant_of) else None
        if not self._allow_automated_accounts and not (
            tenant_key and self.allow_account_creation_for_tenant(app, tenant_key)
        ):
            return None
        predefined = self._lookup_credential(app, tenant_key=PREDEFINED_CREDENTIAL_KEY)
        if predefined is None:
            return None
        create = getattr(self._browser, "create_account", None)
        if not callable(create):
            return None
        username = predefined.username
        password = secrets.token_urlsafe(16)
        try:
            status = str(create(app.id, username, password))
        except Exception:  # pragma: no cover - boundary/browser error -> hand off
            return None
        if status in ("ok", "email_verify"):
            self._capture_credential(app, username, password)
            return status
        return None

    def allow_account_creation_for_tenant(self, app, tenant_domain: str) -> bool:
        """Return True when account creation may proceed for a tenant even if the
        global ALLOW_AUTOMATED_ACCOUNTS is off, because a stored (non-predefined)
        credential already exists for that ATS. This is the per-tenant allowance that
        lets returning users skip the manual hand-off for accounts they already banked
        (ADR-0004 extension). The global flag still gates brand-new tenants."""
        if self._allow_automated_accounts:
            return True  # global opt-in covers all tenants
        # Per-tenant allowance: a non-predefined credential is already stored for this
        # tenant key in the campaign's credential vault -- the user already banked an
        # account here, so account creation is implicitly allowed for this ATS.
        store = self._credentials
        if store is None:
            return False
        try:
            cred = store.retrieve(app.campaign_id, tenant_domain)
        except Exception:  # pragma: no cover - defensive
            return False
        return cred is not None and cred.tenant_key != PREDEFINED_CREDENTIAL_KEY

    def _capture_credential(self, app, username: str, password: str) -> None:
        """Bank a freshly-created account credential under the ATS tenant key so future
        applications at this tenant log in automatically (FR-VAULT-2)."""
        store = self._credentials
        tenant_of = getattr(self._browser, "tenant_key", None)
        if store is None or not callable(tenant_of):
            return
        try:
            tenant_key = tenant_of(app.id)
            if tenant_key:
                store.capture(app.campaign_id, tenant_key, username, password)
        except Exception as exc:  # noqa: BLE001 — never crash, but never lose the credential
            log.warning("Failed to capture credential for tenant", exc_info=True)
            # #204: a swallowed capture means the engine CREATED an account whose
            # generated password is now lost — the worst silent failure. Land a recovery
            # pending action so the operator can recover/reset the account credential
            # instead of it vanishing with a bare ``pass``.
            self._record_diagnostic(
                f"Failed to bank a captured account credential for application {app.id}: {exc}"
            )
            try:
                self._emit_error(
                    app,
                    title="Account credential could not be saved — recover it",
                    detail=(
                        f"A new account was created for {username!r} but its generated "
                        f"password could not be banked ({exc}). Reset/recover this "
                        "account credential so future applications can sign in."
                    ),
                    selector=f"credential:{username}",
                )
            except Exception:  # noqa: BLE001 — recovery-action emission must never crash
                log.debug("Failed to emit credential-recovery action", exc_info=True)

    def _two_factor_handoff(self, app, result) -> PrefillResult:
        """Google sign-in needs a second factor the engine cannot produce. Hold the
        sandbox, notify the user with a 'continue' link to trigger the 2FA push, and
        pivot to other work. (The continue→60s-wait→retry resume is the next
        increment; this lands the descriptive first notification.)"""
        app = app.with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
        result.state = app.status
        result.pending_action_id = self._emit_waiting(
            application=app,
            kind="two_factor",
            title="Google needs two-factor sign-in to continue",
            session_url=result.sandbox_session_url,
            payload={"provider": "google", "action": "continue_two_factor"},
        )
        self._persist(app)
        return result

    def _blocked_detection(self, app, result, event) -> PrefillResult:
        """Pause + hand off on a detection signal (cautious mode, FR-PREFILL-6)."""
        app = app.with_status(ApplicationState.BLOCKED_DETECTION)
        result.state = app.status
        result.detection_signal = event.signal_type
        result.pending_action_id = self._emit_waiting(
            application=app,
            kind="detection_blocker",
            title="Detection blocker — take over",
            session_url=result.sandbox_session_url,
            payload={"signal_type": event.signal_type},
        )
        self._persist(app)
        return result

    def _account_handoff(
        self, app, result, session_url, *, signal_type: str | None = None
    ) -> PrefillResult:
        """Land AWAITING_ACCOUNT_HUMAN_STEP — the engine never creates an account.

        Shared by the first-page account step and a mid-flow account-creation page
        (FR-PREFILL-4): both pre-fill what they can, then hand off to the human. When
        a detection signal triggered the hand-off (FR-PREFILL-6), ``signal_type`` is
        recorded on the pending action so the take-over surfaces the cause.
        """
        app = app.with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
        result.account_handoff = True
        result.state = app.status
        payload = {"signal_type": signal_type} if signal_type else None
        title = (
            "Detection on account page — take over"
            if signal_type
            else "Complete account creation"
        )
        result.pending_action_id = self._emit_waiting(
            application=app,
            kind="account_human_step",
            title=title,
            session_url=session_url,
            payload=payload,
        )
        self._persist(app)
        return result

    def _reach_final_approval(self, app, result, attributes=None) -> PrefillResult:
        # #177: before offering the run for final submission, check the field-match
        # rate (filled / detected). A run that walked the whole flow but matched almost
        # nothing is a probable wrong-ATS / near-empty fill — flag it for human review
        # instead of silently submitting garbage (universal-ATS robustness).
        if is_probable_wrong_ats(
            result.fields_filled, result.fields_detected, floor=self._match_rate_floor
        ):
            return self.flag_probable_wrong_ats(app, result, attributes)
        app = app.with_status(ApplicationState.MATERIAL_PREP)
        app = app.with_status(ApplicationState.MATERIAL_REVIEW)
        app = app.with_status(ApplicationState.AWAITING_FINAL_APPROVAL)
        result.state = app.status
        result.pending_action_id = self._emit_waiting(
            application=app,
            kind="final_approval",
            title="Final approval / submit",
            session_url=result.sandbox_session_url,
        )
        self._persist(app)
        return result

    @staticmethod
    def field_match_rate(filled: int, detected: int) -> float:
        """The fraction of detected fillable fields actually filled over a run (#177).

        Thin pass-through to the pure core rule (``core.rules.ats_match_rate``) so the
        accounting the loop records on the :class:`PrefillResult` is also computable on
        demand. ``detected == 0`` is a perfect rate (nothing to fill, nothing to flag).
        """
        return field_match_rate(filled, detected)

    def flag_probable_wrong_ats(self, app, result, attributes=None) -> PrefillResult:
        """Flag a probable wrong-ATS / near-empty-fill run for human review (#177).

        Universal-ATS coverage drives ANY form via the generic live-DOM driver, but
        when the run's field-match rate (filled / detected) came in below the floor the
        page model did not line up with the real form — pre-fill landed (almost)
        nothing. This too is "the agent tried to fill the form and failed" (FR-PREFILL-7)
        — just detected by match-rate rather than an exception — so it delegates to
        :meth:`emergency_handoff` for the value-assembly + the established
        ``EMERGENCY_DATA_HANDOFF`` transition (a §7-legal PREFILLING transition) with
        the copy/paste values the user can apply by hand, layering its own
        ``wrong_ats`` pending-action identity and match-rate diagnostics on top. The
        human either takes over the live session or marks it submitted manually.
        """
        rate = self.field_match_rate(result.fields_filled, result.fields_detected)
        pct = round(rate * 100)
        handoff = self.emergency_handoff(
            app,
            attributes,
            kind="wrong_ats",
            title="Pre-fill matched too few fields — review needed",
            extra_payload={
                "reason": "probable_wrong_ats",
                "fields_filled": result.fields_filled,
                "fields_detected": result.fields_detected,
                "match_rate": rate,
                "match_rate_pct": pct,
                "match_rate_floor": self._match_rate_floor,
            },
        )
        result.state = handoff.state
        result.wrong_ats_flagged = True
        result.handoff_values = handoff.handoff_values
        result.pending_action_id = handoff.pending_action_id
        return result

    def _fill_current_page(
        self, app, attributes, result, *, block_on_missing: bool = True
    ) -> PrefillResult | None:
        """Fill every detected field on the current page via the core rules.

        Returns ``None`` on success, or a terminated :class:`PrefillResult` when the
        page blocks (missing attribute → BLOCKED_MISSING_ATTR, essay screening
        question → BLOCKED_QUESTION).

        ``block_on_missing=False`` is used for the account-creation page: that page
        always hands off to the human (the engine never creates an account), so a
        required field we cannot fill must NOT raise a ``BLOCKED_MISSING_ATTR``
        transition the ACCOUNT_PREFILL state forbids — the human completes it when
        they take over the live session.
        """
        aid = app.id
        state = self._browser.current_state(aid)
        if state is None:
            log.warning("current_state() returned None for application %s", aid)
            return result
        page_log: dict[str, str] = {}
        for fld in self._browser.detect_fields(aid):
            # #177: every fillable field DETECTED counts toward the run's match rate
            # (filled / detected), so a wrong page model that detects fields but fills
            # none is observable. The count includes file/essay/sensitive fields — the
            # rate measures whether the page model lined up with the real form at all.
            result.fields_detected += 1
            # File inputs can't be text-filled and never count as a missing-attribute
            # block. A résumé/CV input gets the rendered base résumé attached (FR-RESUME-4,
            # Phase 2: upload the base résumé as-is); cover-letter / unknown file inputs
            # are still skipped so the rest of the form pre-fills regardless.
            if fld.field_type == "file":
                before = len(result.uploaded_documents)
                self._maybe_upload_resume(app, fld, state.url, result)
                if len(result.uploaded_documents) > before:
                    result.fields_filled += 1  # a résumé/CV actually attached.
                continue
            resolved = self._resolve_value(fld, attributes, result)

            if resolved.defer_essay:
                # Essay screening question: NOT auto-answered in Phase 2 — recorded
                # and deferred to Phase 3 generation + the FR-RESUME-8 review gate
                # (FR-ANSWER-1). A clean handoff; pre-fill of other fields continues.
                # FR-UI-3: a genuine question requiring the human materializes an
                # ``agent_question`` pending action so it shows in the portal.
                result.deferred_essay_questions.append(
                    {"selector": fld.selector, "label": fld.label, "url": state.url}
                )
                self._emit_agent_question(app, fld, state.url)
                continue

            if resolved.value is None:
                # Block only on fields that are genuinely required. ``required is False``
                # (the real DOM says optional) → skip an unmappable field rather than
                # stall the whole application on an optional free-text question — real
                # ATS forms have many (universal-ATS support). ``required is None``
                # (unknown / fake source) preserves the legacy "required by type" rule.
                is_optional = getattr(fld, "required", None) is False
                if fld.field_type in self._required_types and not is_optional:
                    if not block_on_missing:
                        # Account page: hand off to the human for anything we can't
                        # fill (they create the account anyway); never raise the
                        # BLOCKED_MISSING_ATTR transition ACCOUNT_PREFILL forbids.
                        continue
                    # Required field with no value → missing-attr soft error (FR-ATTR-5).
                    return self._block_missing_attr(app, fld, result)
                continue  # optional field with no value → skip.

            try:
                self._browser.fill_field(aid, fld.selector, resolved.value)
            except Exception as exc:  # noqa: BLE001 — soft failure, never crash the loop
                # FR-UI-3: an error / soft-failure during fill materializes an
                # ``error`` pending action so it surfaces in the portal (it does not
                # crash the run; remaining fields continue, then the user is asked).
                self._emit_error(
                    app,
                    title=f"Could not fill field: {fld.label}",
                    detail=str(exc),
                    selector=fld.selector,
                )
                # Record the failure in page_log and audit trail (G11 #205).
                page_log[fld.selector] = f"__FAILED__:{exc}"
                result.fields_failed.append({
                    "selector": fld.selector,
                    "label": fld.label,
                    "url": state.url,
                    "error": str(exc),
                })
                continue
            page_log[fld.selector] = resolved.value
            result.fields_filled += 1  # #177: a field value actually landed.
            if resolved.generated:
                # A DRAFTED screening answer — record it so it is surfaced for the
                # user's review before any submit (FR-ANSWER-1, FR-RESUME-8).
                result.generated_answers.append(
                    {
                        "selector": fld.selector,
                        "label": fld.label,
                        "answer": resolved.value,
                        "url": state.url,
                    }
                )
            if resolved.is_sensitive and resolved.from_explicit:
                result.sensitive_filled_from_explicit.append(fld.selector)
            elif resolved.is_sensitive:
                result.sensitive_declined.append(fld.selector)

        if page_log:
            result.filled_by_page[state.url] = page_log
        return None

    #: Label/selector markers that identify a résumé/CV file input (as opposed to a
    #: cover-letter or unrelated attachment). Kept narrow so we only ever upload the
    #: base résumé into a control that is actually asking for it.
    _RESUME_INPUT_MARKERS: tuple[str, ...] = (
        "resume", "résumé", "resumé", "cv", "curriculum vitae", "curriculum-vitae",
    )

    @classmethod
    def _is_resume_input(cls, fld: DetectedField) -> bool:
        """True when a file input is asking for a résumé/CV (FR-RESUME-4).

        Token-aware so the bare ``cv`` marker matches "Resume/CV" or an ``id=cv`` but
        not a substring inside an unrelated word; matches on the label OR the selector.
        """
        import re

        hay = f"{fld.label or ''} {fld.selector or ''}".lower()
        tokens = set(re.split(r"[^a-z]+", hay))
        for marker in cls._RESUME_INPUT_MARKERS:
            if " " in marker:
                if marker in hay:
                    return True
            elif marker in tokens:
                return True
        return False

    def _maybe_upload_resume(
        self, app, fld: DetectedField, url: str, result: PrefillResult
    ) -> None:
        """Attach the base résumé to a résumé/CV file input (FR-RESUME-4).

        Best-effort: no provider, no résumé file, a non-résumé file input, or any
        upload failure all simply skip — a file input never blocks the pre-fill loop.
        """
        if self._resume_provider is None or not self._is_resume_input(fld):
            return
        try:
            path = self._resume_provider.resume_file_for(app)
        except Exception:  # noqa: BLE001 — never crash the loop on provider error
            path = None
        if not path:
            return
        try:
            self._browser.upload_file(app.id, fld.selector, path)
        except NativeFilePickerRequired as picker:
            # The attach control opened a NATIVE OS file-picker the DOM can't satisfy.
            # If desktop assist (computer use) is operable, complete the off-page dialog
            # with it (FR-CUA); otherwise degrade EXACTLY as before — skip / human
            # hand-off — by treating it like any other soft upload failure.
            picker_path = getattr(picker, "file_path", None) or path
            if not self._complete_native_picker(app, fld, picker_path):
                return
        except Exception as exc:  # noqa: BLE001 — soft failure, surface but continue
            self._emit_error(
                app,
                title=f"Could not upload résumé: {fld.label}",
                detail=str(exc),
                selector=fld.selector,
            )
            return
        result.uploaded_documents.append(
            {"selector": fld.selector, "label": fld.label, "path": path, "url": url}
        )

    def _desktop_operable(self) -> bool:
        """Whether desktop assist (computer use) is genuinely operable (FR-CUA).

        Mirrors the router's capability gate (``app/routers/remote.py`` ``_desktop_health``):
        a real driver answered the health preflight (``ok``) AND the active backend is NOT
        the ``noop`` test backend. So a default ``COMPUTER_USE_BACKEND=noop`` deploy — or a
        driver missing from the sandbox image — reports not-operable and we never attempt
        the desktop path. Defensive: any error → not operable (degrade as before).
        """
        cu = self._computer_use
        if cu is None:
            return False
        try:
            report = cu.health()
        except Exception:  # noqa: BLE001 — a flaky preflight must never crash the loop
            return False
        return bool(getattr(report, "ok", False)) and getattr(report, "backend", "") != "noop"

    def _complete_native_picker(self, app, fld: DetectedField, path: str) -> bool:
        """Complete a native OS file-picker with desktop assist (FR-CUA). Returns success.

        STRICTLY bounded to the file-attach step (``StepKind.UPLOAD_DOCUMENT``): it only
        ever focuses the dialog, types the résumé/CV PATH (a path is not a secret —
        FR-CUA-6 blocks only credentials), and confirms. It NEVER clicks account-create /
        submit / CAPTCHA; the desktop adapter additionally enforces the stop-boundary
        (FR-CUA-3) on every action, and these actions carry no boundary ``intent`` so they
        cannot trip it. Returns False (degrade — skip / human hand-off) when desktop assist
        is not operable or any step fails."""
        if not self._desktop_operable():
            return False
        cu = self._computer_use
        try:
            # Target the file-open dialog in the background (no foreground steal, FR-CUA-7),
            # type the path the DOM couldn't supply, then confirm — the bounded vocabulary.
            cu.focus_app("file-open-dialog")
            cu.type_text(path, is_secret=False)
            cu.key("enter")
        except Exception as exc:  # noqa: BLE001 — desktop failure is a soft upload failure
            self._emit_error(
                app,
                title=f"Could not attach résumé via desktop helper: {fld.label}",
                detail=str(exc),
                selector=fld.selector,
            )
            return False
        return True

    def _complete_native_dialog(self, app, intent: str, *, confirm_key: str = "escape") -> bool:
        """Clear a NON-file off-page OS dialog with desktop assist (#141, FR-CUA).

        Generalises ``_complete_native_picker`` beyond the résumé file-open dialog to the
        other off-page windows a page can spawn that the browser DOM cannot reach — an
        "Open with…" handler chooser or a print-to-PDF dialog. STRICTLY bounded: it only
        ever focuses the dialog (background, no foreground steal — FR-CUA-7) and presses a
        single dismiss/confirm key. It NEVER clicks, types a secret, or crosses the
        account-create / final-submit stop-boundary — those carry no boundary ``intent``
        here, and the desktop adapter enforces the stop-boundary (FR-CUA-3) on every
        action regardless. Returns False (degrade — leave the step for a human) when
        desktop assist is not operable or any bounded step fails.
        """
        if not self._desktop_operable():
            return False
        cu = self._computer_use
        try:
            cu.focus_app(f"native-dialog:{intent}")
            cu.key(confirm_key)
        except Exception as exc:  # noqa: BLE001 — a desktop failure is a soft hand-off
            self._record_diagnostic(
                f"Desktop assist could not clear off-page dialog {intent!r}: {exc}"
            )
            return False
        return True

    # --- field resolution -------------------------------------------------
    @dataclass
    class _Resolved:
        value: str | None
        is_sensitive: bool = False
        from_explicit: bool = False
        defer_essay: bool = False
        #: value was DRAFTED by the LLM from the profile (review-gated, FR-ANSWER-1).
        generated: bool = False

    def _resolve_value(
        self, fld: DetectedField, attributes: list[Attribute], result: PrefillResult
    ) -> PrefillService._Resolved:
        """Resolve a fill value for a field, enforcing all field policies.

        * Essay screening questions defer (Phase 3) — never auto-answered here.
        * Sensitive (EEO) fields route through ``decide_sensitive_fill``: explicit
          answer only, else decline; never AI-guessed (FR-ATTR-6).
        * Factual fields use the explicit answer, escalating an ambiguous mapping to
          the LLM port when configured (FR-PREFILL-3).
        """
        # Essay screening questions are deferred to Phase 3 generation (FR-ANSWER-1).
        if fld.field_type == SCREENING_ESSAY:
            return self._Resolved(value=None, defer_essay=True)

        explicit = self._lookup(fld.label, attributes)

        # A field is sensitive when its LABEL is a recognised demographic/EEO field OR
        # the matched attribute is itself flagged sensitive (#206). The substring label
        # matcher cannot recognise every protected attribute (e.g. "Caste"), so an
        # attribute the user explicitly marked sensitive must still route through the
        # sensitive-field policy (explicit-answer-only, never AI-guessed — FR-ATTR-6),
        # not the plain mapping path — defence against leaking/guessing a demographic.
        if is_sensitive_field(fld.label) or self._matched_attr_is_sensitive(fld.label, attributes):
            decision = decide_sensitive_fill(fld.label, explicit)
            return self._Resolved(
                value=decision.value,
                is_sensitive=True,
                from_explicit=decision.from_explicit_answer,
            )

        # Non-sensitive (incl. factual screening): direct mapping, else LLM escalate.
        if explicit is not None:
            return self._Resolved(value=explicit)
        guessed = self._escalate_mapping(fld, attributes)
        if guessed is not None:
            return self._Resolved(value=guessed)
        # Free-text screening QUESTION we could not map → draft a truthful answer from
        # the profile (FR-ANSWER-1). Review-gated (FR-RESUME-8); fabrication-checked so
        # it never invents facts; returns None (→ ask the user) when the profile lacks
        # enough to answer truthfully.
        if self._is_screening_question(fld):
            drafted = self._generate_screening_answer(fld, attributes)
            if drafted is not None:
                return self._Resolved(value=drafted, generated=True)
        return self._Resolved(value=None)

    def _escalate_mapping(
        self, fld: DetectedField, attributes: list[Attribute]
    ) -> str | None:
        """Escalate an ambiguous non-sensitive mapping to the LLM port (FR-PREFILL-3).

        The LLM is given the field label and the available attribute names and asked
        which stored value (if any) maps to the field. A confident, non-sensitive
        match is returned; anything else returns ``None`` so the caller raises the
        missing-attribute soft error rather than guessing.
        """
        if self._llm is None or not attributes:
            return None
        # NEVER escalate a sensitive field to an LLM guess (FR-ATTR-6).
        if is_sensitive_field(fld.label):
            return None
        from applicant.ports.driven.llm import ChatMessage

        # Only expose non-sensitive attribute NAMES to the LLM (#222, FR-ATTR-6).
        # Sensitive attribute names (SSN, DOB, EEO fields, etc.) must not appear
        # in the prompt — even the name itself is information the model should
        # not see. The result is still validated against `is_sensitive` below.
        non_sensitive_attrs = [a for a in attributes if not is_sensitive_field(a.name)]
        if not non_sensitive_attrs:
            return None
        names = ", ".join(a.name for a in non_sensitive_attrs)
        prompt = (
            "You map a web-form field to ONE stored attribute. "
            f"Field label: {fld.label!r}. Stored attributes: {names}. "
            "Reply with the EXACT attribute name that maps to this field, or the "
            "single word NONE if none clearly maps. Do not invent a value."
        )
        try:
            # FR-LLM-4: field mapping starts above L1 (the task-appropriate tier).
            res = self._llm.complete(
                [ChatMessage(role="user", content=prompt)],
                start_tier=FIELD_MAPPING_START_TIER,
            )
        except Exception as exc:  # noqa: BLE001 — LLM outage degrades, never crashes
            log.warning("LLM escalation failed for field %r", fld.label, exc_info=True)
            # #211: surface a SINGLE 'LLM unavailable' diagnostic (deduped in the ring)
            # so a rate-limit / bad-key outage during mapping is visible to the operator
            # instead of silently degrading every ambiguous field to a soft error.
            self._record_diagnostic(f"LLM unavailable during field mapping: {exc}")
            return None  # LLM unavailable → fall through to soft error (frugal).
        if getattr(res, "low_confidence", False):
            return None
        choice = (res.text or "").strip()
        if not choice or choice.upper() == "NONE":
            return None
        for attr in attributes:
            if attr.matches(choice) and not is_sensitive_field(attr.name):
                return attr.value
        return None

    @staticmethod
    def _is_screening_question(fld: DetectedField) -> bool:
        """A free-text answer field we draft for, vs a plain data field (name/email).
        A ``<textarea>`` is inherently a free-text prompt; a text input qualifies only
        when its label READS like a question (ends with '?' or uses question-like
        phrasing such as "describe", "explain", "tell us about"). Never sensitive
        (FR-ATTR-6 — EEO is never AI-drafted)."""
        if is_sensitive_field(fld.label):
            return False
        if fld.field_type == "textarea":
            return True
        if fld.field_type not in ("text", SCREENING_FACTUAL):
            return False
        label = (fld.label or "").strip()
        low = label.lower()
        # Ends with '?' is a strong signal.
        if label.endswith("?"):
            return True
        # Question-like phrasing beats simple word count.
        _QUESTION_TRIGGERS = (
            "describe", "explain", "tell us", "tell me", "how do you",
            "how would you", "why do you", "what is your", "what are your",
            "please describe", "please explain", "in detail", "elaborate",
            "walk me through", "share your experience", "give an example",
            "provide an example", "briefly describe",
        )
        if any(trigger in low for trigger in _QUESTION_TRIGGERS):
            return True
        # #209: a long-but-factual data field ("Current Home Street Address Line 2"
        # is six words) must NOT be misclassified as an essay prompt by raw word
        # count. Known plain-data label patterns are excluded before the fallback.
        _DATA_FIELD_MARKERS = (
            "address", "street", "city", "state", "province", "zip", "postal",
            "country", "phone", "email", "name", "linkedin", "github", "portfolio",
            "website", "url", "date of birth", "birth", "ssn", "social security",
            "license", "salary", "compensation", "wage", "number", "code",
        )
        if any(marker in low for marker in _DATA_FIELD_MARKERS):
            return False
        # Free-text label with enough words to be a prompt (not name/email/phone).
        words = [w for w in label.split() if w]
        return len(words) >= 6

    def _generate_screening_answer(
        self, fld: DetectedField, attributes: list[Attribute]
    ) -> str | None:
        """Draft a TRUTHFUL answer to a screening question from the profile (FR-ANSWER-1).

        Uses ONLY the candidate's stored facts; the answer is fabrication-checked
        against those facts (FR-RESUME-2) and run through the non-AI post-filter
        (FR-RESUME-5). Returns ``None`` — so the caller asks the user — when the LLM is
        absent, signals INSUFFICIENT, is low-confidence, or the draft would fabricate.
        The drafted answer is review-gated by the caller (FR-RESUME-8)."""
        if self._llm is None or not attributes:
            return None
        from applicant.core.rules.truthfulness import (
            normalize_emdashes,
            strip_banned_phrases,
            unsupported_prose_claims,
        )
        from applicant.ports.driven.llm import ChatMessage

        facts = "\n".join(
            f"{a.name}: {a.value}" for a in attributes if not is_sensitive_field(a.name)
        )
        prompt = (
            "You are completing a job application for the candidate described below. "
            "Answer the application QUESTION truthfully and concisely, using ONLY the "
            "candidate's facts. Do NOT invent employers, job titles, dates, skills, "
            "degrees, or numbers. If the facts do not contain enough to answer the "
            "question truthfully, reply with exactly: INSUFFICIENT.\n\n"
            f"CANDIDATE FACTS:\n{facts}\n\nQUESTION: {fld.label}\n\nANSWER:"
        )
        try:
            res = self._llm.complete(
                [ChatMessage(role="user", content=prompt)],
                start_tier=FIELD_MAPPING_START_TIER,
            )
        except Exception:
            return None
        if getattr(res, "low_confidence", False):
            return None
        answer = (res.text or "").strip()
        if not answer or answer.upper().startswith("INSUFFICIENT"):
            return None
        # Truthfulness guard (FR-RESUME-2): reject anything the profile can't support
        # rather than fill a fabricated claim — fall back to asking the user.
        if unsupported_prose_claims(facts, answer):
            return None
        # FR-RESUME-5 non-AI post-filter (no em dashes / banned phrases).
        return normalize_emdashes(strip_banned_phrases(answer))

    @staticmethod
    def _lookup(label: str, attributes: list[Attribute]) -> str | None:
        """Return the value of the BEST-MATCHING attribute for ``label`` (issue #210).

        Priority tiers (descending):
          1. **Exact name** — ``label`` matches ``attr.name`` case-insensitively.
          2. **Alias** — ``label`` matches one of ``attr.aliases`` case-insensitively.
          3. **Loose/fuzzy** — the normalised label or name is a substring of the other.

        Within each tier, the *first* attribute in list order wins, so the user
        can still control tie-breaking by ordering attributes.
        """
        label_low = label.strip().lower()
        # Tier 1: exact name match
        for attr in attributes:
            if label_low == attr.name.strip().lower():
                return attr.value
        # Tier 2: alias match
        for attr in attributes:
            low_aliases = {a.strip().lower() for a in attr.aliases}
            if label_low in low_aliases:
                return attr.value
        # Tier 3: loose / fuzzy (substring containment)
        for attr in attributes:
            name_low = attr.name.strip().lower()
            if label_low in name_low or name_low in label_low:
                return attr.value
        return None

    @staticmethod
    def _matched_attr_is_sensitive(label: str, attributes: list[Attribute]) -> bool:
        """True when the attribute that maps to ``label`` is flagged sensitive (#206).

        Mirrors :meth:`_lookup`'s priority (exact name > alias > loose) to find the SAME
        attribute the value would come from, and reports its ``is_sensitive`` flag — so a
        protected attribute whose label the substring matcher misses (e.g. "Caste") is
        still gated by the sensitive-field policy rather than the plain mapping path.
        """
        label_low = label.strip().lower()
        for attr in attributes:  # tier 1: exact name
            if label_low == attr.name.strip().lower():
                return bool(getattr(attr, "is_sensitive", False))
        for attr in attributes:  # tier 2: alias
            if label_low in {a.strip().lower() for a in attr.aliases}:
                return bool(getattr(attr, "is_sensitive", False))
        for attr in attributes:  # tier 3: loose / fuzzy
            name_low = attr.name.strip().lower()
            if label_low in name_low or name_low in label_low:
                return bool(getattr(attr, "is_sensitive", False))
        return False

    # --- block emitters ---------------------------------------------------
    def _block_missing_attr(self, app, fld: DetectedField, result: PrefillResult) -> PrefillResult:
        app = app.with_status(ApplicationState.BLOCKED_MISSING_ATTR)
        result.state = app.status
        result.missing_attribute = fld.label
        result.pending_action_id = self._emit_waiting(
            application=app,
            kind="missing_attr",
            title=f"Provide missing detail: {fld.label}",
            session_url=result.sandbox_session_url,
            payload={
                "attribute_name": fld.label,
                "field_selector": fld.selector,
                "dedup_key": f"missing_attr:{fld.label}:{fld.selector}",
            },
        )
        self._persist(app)
        return result

    def _emit_agent_question(self, app, fld: DetectedField, url: str) -> PendingActionId:
        """Materialize an ``agent_question`` pending action (FR-UI-3 / FR-AGENT-4).

        A genuine question requiring the human (an essay/screening question we do not
        auto-answer) becomes a portal item so the user can answer it. Deduped per
        (application, selector) so re-walking the page does not pile up duplicates.
        """
        return self._emit_pending(
            app,
            kind="agent_question",
            title=f"Question needs your input: {fld.label}",
            payload={
                "question": fld.label,
                "field_selector": fld.selector,
                "url": url,
                "dedup_key": f"agent_question:{app.id}:{fld.selector}",
            },
        )

    def _emit_error(self, app, *, title: str, detail: str, selector: str) -> PendingActionId:
        """Materialize an ``error`` pending action for a soft failure (FR-UI-3)."""
        return self._emit_pending(
            app,
            kind="error",
            title=title,
            payload={
                "detail": detail,
                "field_selector": selector,
                "dedup_key": f"error:{app.id}:{selector}",
            },
        )

    def _emit_pending(self, app, *, kind: str, title: str, payload: dict) -> PendingActionId:
        """Create a pending action (deduped by ``payload['dedup_key']`` if present)."""
        cid: CampaignId = app.campaign_id
        dedup_key = payload.get("dedup_key")
        if dedup_key is not None:
            for existing in self._storage.pending_actions.list_open(cid):
                if existing.payload.get("dedup_key") == dedup_key:
                    return existing.id
        pid = PendingActionId(new_id())
        action = PendingAction(
            id=pid, campaign_id=cid, kind=kind, title=title,
            application_id=app.id, payload=dict(payload),
        )
        self._storage.pending_actions.add(action)
        self._storage.commit()
        if self._notification is not None:
            from applicant.ports.driven.notification import (
                Notification,
                NotificationUrgency,
            )

            self._notification.notify(
                Notification(
                    title=title,
                    body=f"Application {app.id} needs you.",
                    deep_link=None,
                    # Unlike _emit_waiting, this backs agent_question/error — a queued
                    # item for the Portal (a screening question, a soft field failure),
                    # not the agent frozen mid-flow. Default/NORMAL urgency: it should
                    # land in the queue, not wake the user through quiet hours.
                    urgency=NotificationUrgency.NORMAL,
                    # #7: consistent ``decision:prefill:{ref}`` key so resolving the
                    # blocked state can expire this ping via
                    # ``NotificationService.acted(f"prefill:{ref}")`` — the un-prefixed
                    # ``{app.id}:{kind}:...`` key could never be expired by ``acted``.
                    dedup_key=ping_dedup_key(app.id, kind, dedup_key or title),
                )
            )
        return pid

    def _capture_screenshot(self, aid, result: PrefillResult) -> None:
        """Capture a per-page screenshot, record its page URL, and ARCHIVE it (FR-LOG-2).

        Each page screenshot is persisted to ``application_screenshots`` as it is
        captured during the live pre-fill walk, so a completed application has its
        per-page screenshots in storage (retrievable via the storage port / the
        outcomes log endpoint) — not just held in the in-memory ``PrefillResult``.
        """
        ref = self._browser.screenshot(aid)
        state = self._browser.current_state(aid)
        url = state.url if state is not None else ""
        result.screenshots.append(ref)
        result.screenshot_pages.append(url)
        self._archive_screenshot(aid, ref, url)

    def _archive_screenshot(self, aid, page_ref: str, page_url: str) -> None:
        """Persist one per-page screenshot to the storage port (FR-LOG-2)."""
        from applicant.core.entities.application_screenshot import ApplicationScreenshot
        from applicant.core.ids import ScreenshotId

        try:
            self._storage.screenshots.add(
                ApplicationScreenshot(
                    id=ScreenshotId(new_id()),
                    application_id=aid,
                    page_ref=page_ref,
                    page_url=page_url,
                )
            )
            self._storage.commit()
        except Exception:  # pragma: no cover - never let archival break the pre-fill loop
            pass

    def _check_detection(self, aid):
        """Forward the FULL signal dict so cautious mode sees every supported signal.

        ``classify_signals`` recognizes HTTP status (403/429), body/markup challenge
        markers (Cloudflare/CAPTCHA), anomalous redirects (url vs expected_host), and
        the explicitly-extracted signal tuple — not just ``signals`` (FR-PREFILL-6).
        """
        state = self._browser.current_state(aid)
        if state is None:
            log.warning("current_state() returned None in _check_detection for %s", aid)
            return None
        page_signals: dict = {"signals": state.detection_signals}
        status = getattr(state, "status", None)
        if status is not None:
            page_signals["status"] = status
        body = getattr(state, "body", None)
        if body is not None:
            page_signals["body"] = body
        page_signals["url"] = state.url
        expected = getattr(state, "expected_host", None)
        if expected is not None:
            page_signals["expected_host"] = expected
        event = self._detection.evaluate(aid, page_signals)
        if event is not None:
            self._archive_detection(event)
        return event

    def _archive_detection(self, event) -> None:
        """Persist a classified detection signal for the FR-OBS-2 debug surface.

        Cautious mode classified a signal (CAPTCHA/Cloudflare/403/429/...) — record
        it durably so detection history is queryable, not only computed in-flight.
        Best-effort: archival must never break the pre-fill loop.
        """
        repo = getattr(self._storage, "detection_events", None)
        if repo is None:
            return
        try:
            repo.add(event)
            self._storage.commit()
        except Exception:  # pragma: no cover - never let archival break pre-fill
            pass

    # --- side effects -----------------------------------------------------
    def _emit_waiting(
        self,
        *,
        application: Application,
        kind: str,
        title: str,
        session_url: str | None,
        payload: dict | None = None,
    ) -> PendingActionId:
        """Land a pending action + notify (every waiting state does this, §7).

        IDEM-2: deduped by ``(application_id, kind)`` — ``_resume_in_flight`` re-drives
        an in-flight app every ~60s tick, re-landing the same waiting state; without
        this guard each redrive piled up another identical pending action.
        """
        cid: CampaignId = application.campaign_id
        for existing in self._storage.pending_actions.list_open(cid):
            if (
                str(getattr(existing, "application_id", "")) == str(application.id)
                and existing.kind == kind
            ):
                return existing.id
        pid = PendingActionId(new_id())
        body = dict(payload or {})
        if session_url:
            body["session_url"] = session_url
        action = PendingAction(
            id=pid,
            campaign_id=cid,
            kind=kind,
            title=title,
            application_id=application.id,
            payload=body,
        )
        self._storage.pending_actions.add(action)
        self._storage.commit()
        if self._notification is not None:
            from applicant.ports.driven.notification import (
                Notification,
                NotificationUrgency,
            )

            self._notification.notify(
                Notification(
                    title=title,
                    body=f"Application {application.id} awaits you.",
                    deep_link=session_url,
                    # Every waiting state here (2FA / detection / account hand-off /
                    # emergency hand-off, §7) blocks the agent on the human — CRITICAL
                    # so it is never silently deferred by quiet hours (FR-NOTIF-5).
                    urgency=NotificationUrgency.CRITICAL,
                    # #7: consistent ``decision:prefill:{ref}`` key so the resolution
                    # path expires this ping via ``NotificationService.acted``.
                    dedup_key=ping_dedup_key(application.id, kind),
                )
            )
        return pid

    def _persist(self, application: Application) -> None:
        existing = self._storage.applications.get(application.id)
        if existing is None:
            self._storage.applications.add(application)
        else:
            self._storage.applications.update(application)
        self._storage.commit()
