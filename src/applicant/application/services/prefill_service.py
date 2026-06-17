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

from dataclasses import dataclass, field

from applicant.adapters.browser.ats import SCREENING_ESSAY, SCREENING_FACTUAL
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.pending_action import PendingAction
from applicant.core.ids import ApplicationId, CampaignId, PendingActionId, new_id
from applicant.core.rules.sensitive_fields import decide_sensitive_fill, is_sensitive_field
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import DetectedField

#: Topic the durable orchestrator uses for the final-approval gate (FR-NOTIF-2).
FINAL_APPROVAL_TOPIC = "final_approval"


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
        required_field_types: frozenset[str] | None = None,
    ) -> None:
        self._storage = storage
        self._browser = browser
        self._detection = detection
        self._sandbox = sandbox
        self._credentials = credentials
        self._notification = notification
        # LLM port for ambiguous-mapping escalation (FR-PREFILL-3). Optional: when
        # absent, an unresolved non-sensitive field becomes a missing-attr soft error.
        self._llm = llm
        # Field types that MUST be filled (a missing value soft-errors, FR-ATTR-5).
        # Optional fields just skip. Defaults to the load-bearing required ones.
        self._required_types = required_field_types or frozenset(
            {"text", "password", "select", SCREENING_FACTUAL}
        )

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

        # 2. Open the first page.
        self._browser.open(aid, url)

        # 3. Account-creation page (if any) → pre-fill, then hand off (FR-PREFILL-4).
        if self._browser.is_account_create_page(aid):
            app = app.with_status(ApplicationState.ACCOUNT_PREFILL)
            # FR-PREFILL-6: run a cautious detection check BEFORE filling the account
            # page — a CAPTCHA/Cloudflare/etc. there must pause + hand off, never fill.
            # The account context's legal hand-off is the account human step (the user
            # takes over the live session to clear the challenge + create the account).
            if cautious:
                event = self._check_detection(aid)
                if event is not None:
                    result.detection_signal = event.signal_type
                    return self._account_handoff(
                        app, result, session.remote_view_url, signal_type=event.signal_type
                    )
            blocked = self._fill_current_page(app, attributes, result)
            if blocked is not None:
                return blocked
            self._capture_screenshot(aid, result)
            # The engine never clicks the account-creating submit — hand off.
            return self._account_handoff(app, result, session.remote_view_url)

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
        self, application: Application, attributes: list[Attribute] | None = None
    ) -> PrefillResult:
        """Emergency copy/paste handoff — ONLY after a reported fill failure (FR-PREFILL-7).

        This is never the default path: it is invoked when the agent reports it
        tried to fill and failed. It assembles the values the user can paste into
        their own browser and lands the EMERGENCY_DATA_HANDOFF waiting state.
        """
        attributes = attributes or []
        # The agent reports it tried to fill and failed while PREFILLING; if the
        # caller passes an earlier state, normalize to PREFILLING first.
        app = application
        if app.status is not ApplicationState.PREFILLING:
            app = app.with_status(ApplicationState.PREFILLING)
        # Best-effort assemble the values that WOULD have been filled, for paste.
        values: dict[str, str] = {}
        for fld in self._browser.detect_fields(application.id):
            resolved = self._resolve_value(fld, attributes, PrefillResult(application.id, app.status))
            if resolved.value is not None and not resolved.defer_essay:
                values[fld.label] = resolved.value
        app = app.with_status(ApplicationState.EMERGENCY_DATA_HANDOFF)
        result = PrefillResult(
            application_id=application.id,
            state=app.status,
            sandbox_session_url=application.sandbox_session_url,
            handoff_values=values,
        )
        result.pending_action_id = self._emit_waiting(
            application=app,
            kind="emergency_handoff",
            title="Emergency handoff + mark submitted",
            session_url=application.sandbox_session_url,
            payload={"handoff_values": values},
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

            # If this is the final-submit page, all fillable pages are done.
            if self._browser.is_final_submit_page(aid):
                return self._reach_final_approval(app, result)

            # Pre-fill every fillable field on this page (maximal pre-fill).
            blocked = self._fill_current_page(app, attributes, result)
            if blocked is not None:
                return blocked
            self._capture_screenshot(aid, result)

            # Advance; if there is no next page we are done filling.
            if self._browser.advance(aid) is None:
                return self._reach_final_approval(app, result)

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

    def _reach_final_approval(self, app, result) -> PrefillResult:
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

    def _fill_current_page(self, app, attributes, result) -> PrefillResult | None:
        """Fill every detected field on the current page via the core rules.

        Returns ``None`` on success, or a terminated :class:`PrefillResult` when the
        page blocks (missing attribute → BLOCKED_MISSING_ATTR, essay screening
        question → BLOCKED_QUESTION).
        """
        aid = app.id
        state = self._browser.current_state(aid)
        page_log: dict[str, str] = {}
        for fld in self._browser.detect_fields(aid):
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
                if fld.field_type in self._required_types:
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
                continue
            page_log[fld.selector] = resolved.value
            if resolved.is_sensitive and resolved.from_explicit:
                result.sensitive_filled_from_explicit.append(fld.selector)
            elif resolved.is_sensitive:
                result.sensitive_declined.append(fld.selector)

        if page_log:
            result.filled_by_page[state.url] = page_log
        return None

    # --- field resolution -------------------------------------------------
    @dataclass
    class _Resolved:
        value: str | None
        is_sensitive: bool = False
        from_explicit: bool = False
        defer_essay: bool = False

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

        if is_sensitive_field(fld.label):
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
        return self._Resolved(value=guessed)

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

        names = ", ".join(a.name for a in attributes)
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
        except Exception:
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
    def _lookup(label: str, attributes: list[Attribute]) -> str | None:
        for attr in attributes:
            if attr.matches(label):
                return attr.value
        return None

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
            from applicant.ports.driven.notification import Notification

            self._notification.notify(
                Notification(
                    title=title,
                    body=f"Application {app.id} needs you.",
                    deep_link=None,
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
        url = self._browser.current_state(aid).url
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
            from applicant.ports.driven.notification import Notification

            self._notification.notify(
                Notification(
                    title=title,
                    body=f"Application {application.id} awaits you.",
                    deep_link=session_url,
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
