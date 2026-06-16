"""PrefillService (FR-PREFILL-*, FR-ATTR-5/6, FR-STEALTH, FR-SANDBOX, FR-NOTIF-2).

# STAGE B — owned by Phase 2; fleshed out as a thin scaffold.

Drives the **maximal pre-fill loop**: provision a sandbox, walk every page of the
ATS, detect every fillable field, and fill it from the campaign attribute cloud —
routing every fill decision through the core **sensitive-field policy** (EEO fields
filled only from explicit stored answers, never AI-guessed) and every click/submit
through the core **pre-fill-stop boundary** (never click account-create / final
submit). It emits the §7 ``BLOCKED_*`` / ``AWAITING_*`` states with pending actions
+ notifications, supports **cautious mode** (pause on a detection signal), and the
**final-approval gate** via the durable orchestrator's ``recv`` (FR-NOTIF-2).

Scope note: thin scaffold over the in-memory browser/sandbox/detection adapters —
no real browser. The state transitions, rule enforcement, and hand-off shape are
real and tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.pending_action import PendingAction
from applicant.core.ids import ApplicationId, CampaignId, PendingActionId, new_id
from applicant.core.rules.sensitive_fields import decide_sensitive_fill
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import DetectedField

#: Topic the durable orchestrator uses for the final-approval gate (FR-NOTIF-2).
FINAL_APPROVAL_TOPIC = "final_approval"


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
    screenshots: list[str] = field(default_factory=list)
    pending_action_id: PendingActionId | None = None
    detection_signal: str | None = None
    #: True once the engine reached and handed off at the account-create page.
    account_handoff: bool = False


class PrefillService:
    def __init__(
        self, storage, browser, detection, sandbox, credentials, notification=None
    ) -> None:
        self._storage = storage
        self._browser = browser
        self._detection = detection
        self._sandbox = sandbox
        self._credentials = credentials
        self._notification = notification

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
        result = PrefillResult(
            application_id=aid,
            state=app.status,
            sandbox_session_url=session.remote_view_url,
        )

        # 2. Open the first page.
        self._browser.open(aid, url)

        # 3. Account-creation page (if any) → pre-fill, then hand off (FR-PREFILL-4).
        if self._browser.is_account_create_page(aid):
            app = app.with_status(ApplicationState.ACCOUNT_PREFILL)
            self._fill_current_page(aid, attributes, result)
            result.screenshots.append(self._browser.screenshot(aid))
            # The engine never clicks the account-creating submit — hand off.
            app = app.with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
            result.account_handoff = True
            result.state = app.status
            result.pending_action_id = self._emit_waiting(
                application=app,
                kind="account_human_step",
                title="Complete account creation",
                session_url=session.remote_view_url,
            )
            self._persist(app)
            return result

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
        aid = app.id
        while True:
            # Cautious mode: pause on a detection signal BEFORE filling (FR-PREFILL-6).
            if cautious:
                event = self._check_detection(aid)
                if event is not None:
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

            # If this is the final-submit page, all fillable pages are done.
            if self._browser.is_final_submit_page(aid):
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

            # Pre-fill every fillable field on this page (maximal pre-fill).
            self._fill_current_page(aid, attributes, result)
            result.screenshots.append(self._browser.screenshot(aid))

            # Advance; if there is no next page we are done filling.
            if self._browser.advance(aid) is None:
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

    def _fill_current_page(self, aid, attributes, result) -> None:
        """Fill every detected field on the current page via the core rules."""
        state = self._browser.current_state(aid)
        page_log: dict[str, str] = {}
        for fld in self._browser.detect_fields(aid):
            value = self._resolve_value(fld, attributes, result)
            if value is None:
                continue  # missing non-sensitive value → would soft-error; skip here.
            self._browser.fill_field(aid, fld.selector, value)
            page_log[fld.selector] = value
        if page_log:
            result.filled_by_page[state.url] = page_log

    def _resolve_value(
        self, fld: DetectedField, attributes: list[Attribute], result: PrefillResult
    ) -> str | None:
        """Resolve a fill value for a field, enforcing the sensitive-field policy.

        Sensitive (EEO) fields are routed through ``decide_sensitive_fill`` so they
        are filled only from the user's explicit stored answer and otherwise
        default to "decline to self-identify" — never AI-guessed (FR-ATTR-6).
        """
        explicit = self._lookup(fld.label, attributes)
        decision = decide_sensitive_fill(fld.label, explicit)
        if decision.is_sensitive:
            if decision.from_explicit_answer:
                result.sensitive_filled_from_explicit.append(fld.selector)
            else:
                result.sensitive_declined.append(fld.selector)
            return decision.value
        # Non-sensitive: use the explicit answer (real adapter escalates ambiguous
        # mappings to the LLM per FR-PREFILL-3; the scaffold uses direct mapping).
        return explicit

    @staticmethod
    def _lookup(label: str, attributes: list[Attribute]) -> str | None:
        for attr in attributes:
            if attr.matches(label):
                return attr.value
        return None

    def _check_detection(self, aid):
        state = self._browser.current_state(aid)
        if not state.detection_signals:
            return None
        return self._detection.evaluate(aid, {"signals": state.detection_signals})

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
        """Land a pending action + notify (every waiting state does this, §7)."""
        cid: CampaignId = application.campaign_id
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
            from applicant.ports.driven.notification import Notification

            self._notification.notify(
                Notification(
                    title=title,
                    body=f"Application {application.id} awaits you.",
                    deep_link=session_url,
                    dedup_key=f"{application.id}:{kind}",
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
