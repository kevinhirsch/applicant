"""AgentLoop — the per-campaign agent run loop (FR-AGENT-1/2/4/5/6/7, FR-DUR-1/4).

This is the orchestrator that finally *drives* the per-unit services end-to-end.
Nothing called them on a cadence before: discovery / scoring / digest /
notification-escalation / pre-fill never fired on their own. ``AgentLoop.tick``
advances one campaign's work by one step and is safe to call repeatedly (it is
the unit the scheduler invokes).

What one ``tick`` does (§7 pipeline):

1. **Run-mode gate (FR-AGENT-2/7).** Stop if the campaign's run mode says so
   (``AgentRunService.should_continue``); otherwise record the single-sentence
   intent (FR-AGENT-7) for this run.
2. **Throughput cap (FR-AGENT-1).** Count applications acted on per campaign per
   day against the clamped per-day budget (``daily_budget`` -> ``clamp_throughput``,
   hard cap 30). When the budget is exhausted, discovery + new pre-fill stop for
   the day.
3. **Discovery -> viability scoring -> build/deliver the daily digest** (FR-DIG-1).
4. **On approved digest items**, create the ``Application`` row and **enqueue + run
   the durable application pipeline** (the real per-application workflow).
5. **Pivot / yield (FR-AGENT-6, FR-DUR-4).** Admit the application to a sandbox slot
   through ``CapacityService``; when the pipeline lands a ``BLOCKED_*`` /
   ``AWAITING_*`` state it yields its slot so other work proceeds — the blocked one
   never stalls others.
6. **Uncertainty / question holds (FR-AGENT-4/5).** A hand-off state keeps the
   application at its waiting state with its pending action + notification already
   emitted by the pre-fill service; the loop does NOT auto-proceed past the
   human-in-the-loop point.

The clock is injected (``now``) so the loop is pure and unit-testable with no real
sleeps. The daily-acted ledger is keyed by ``(campaign, UTC date)``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from applicant.application.workflows import application_pipeline
from applicant.application.workflows.application_pipeline import (
    WORKFLOW_NAME,
    PipelineContext,
)
from applicant.core.entities.application import Application
from applicant.core.entities.decision import DecisionType
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState
from applicant.observability.logging import get_logger

log = get_logger(__name__)


@dataclass
class TickResult:
    """Structured outcome of one ``tick`` (introspection + tests)."""

    campaign_id: str
    ran: bool = False
    reason: str = ""
    intent: str = ""
    discovered: int = 0
    digest_rows: int = 0
    pipelines_started: list[str] = field(default_factory=list)
    handoffs: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    budget_remaining: int = 0
    budget_exhausted: bool = False


class AgentLoop:
    def __init__(
        self,
        *,
        storage,
        agent_run_service,
        discovery_service=None,
        scoring_service=None,
        digest_service=None,
        prefill_service=None,
        material_service=None,
        submission_service=None,
        learning_service=None,
        notification_service=None,
        capacity_service=None,
        final_approval_service=None,
        sandbox=None,
        orchestrator=None,
    ) -> None:
        self._storage = storage
        self._runs = agent_run_service
        self._discovery = discovery_service
        self._scoring = scoring_service
        self._digest = digest_service
        self._prefill = prefill_service
        self._material = material_service
        self._submission = submission_service
        self._learning = learning_service
        self._notifications = notification_service
        self._capacity = capacity_service
        self._final_approval = final_approval_service
        self._sandbox = sandbox
        self._orch = orchestrator
        # (campaign_id, date) -> count of applications acted on that day (FR-AGENT-1).
        self._acted: dict[tuple[str, date], int] = {}
        # (campaign_id, UTC date) -> True once today's digest was delivered (FR-DIG-1).
        # Guards the loop's own delivery so a ~60s scheduler tick does not re-send the
        # digest email + Discord ready-ping every tick.
        self._digest_sent: dict[tuple[str, date], bool] = {}
        # Register the durable pipeline once if an orchestrator is present.
        if self._orch is not None:
            try:
                application_pipeline.register(self._orch)
            except Exception:  # pragma: no cover - idempotent re-register tolerated
                pass

    # --- daily throughput ledger (FR-AGENT-1) -----------------------------
    def acted_today(self, campaign_id: CampaignId, now: datetime) -> int:
        """Applications acted on today, counted from PERSISTED state (FR-AGENT-1).

        The hard cap must survive a restart, so the count is derived from durable
        ``agent_runs`` (each tick persists its ``pipelines_started``) PLUS the
        current in-progress tick's not-yet-persisted delta. A fresh ``AgentLoop`` over
        the same storage therefore still sees the prior count and keeps enforcing the
        cap — the old in-process-only dict zeroed on restart and let the cap be
        exceeded.
        """
        key = (str(campaign_id), now.date())
        return self._persisted_acted_today(campaign_id, now) + self._acted.get(key, 0)

    def _persisted_acted_today(self, campaign_id: CampaignId, now: datetime) -> int:
        """Sum durably-recorded ``pipelines_started`` over today's agent runs."""
        try:
            runs = self._storage.agent_runs.list_for_campaign(campaign_id)
        except Exception:  # pragma: no cover - defensive
            return 0
        today = now.date()
        total = 0
        for run in runs:
            ts = getattr(run, "timestamp", None)
            if ts is not None and ts.date() == today:
                total += int((run.stats or {}).get("pipelines_started", 0))
        return total

    def _record_acted(self, campaign_id: CampaignId, now: datetime, n: int = 1) -> None:
        key = (str(campaign_id), now.date())
        self._acted[key] = self._acted.get(key, 0) + n

    def remaining_budget(self, campaign, now: datetime) -> int:
        """Applications still allowed today under the clamped per-day cap (FR-AGENT-1)."""
        budget = self._runs.daily_budget(campaign)
        return max(0, budget - self.acted_today(campaign.id, now))

    # --- the tick (one step of one campaign's work) -----------------------
    def tick(
        self, campaign_id: CampaignId, now: datetime | None = None
    ) -> TickResult:
        """Advance one campaign's work by one step. Safe to call repeatedly."""
        now = now or datetime.now(UTC)
        # The in-memory ledger holds ONLY this tick's not-yet-persisted delta; the
        # durable ``agent_runs`` carry the cross-tick total (FR-AGENT-1). Reset it at
        # tick start and clear it at tick end so the persisted count (which survives
        # restart) is the single source of truth between ticks — no double counting.
        key = (str(campaign_id), now.date())
        self._acted.pop(key, None)
        # CONC-3: prune per-day dedup ledgers older than today so the in-memory maps
        # do not grow unbounded over 24/7 operation.
        self._prune_daily(now.date())
        try:
            return self._tick(campaign_id, now)
        finally:
            self._acted.pop(key, None)

    def _prune_daily(self, today: date) -> None:
        """Drop ``_digest_sent`` / ``_acted`` entries from days other than today (CONC-3)."""
        self._digest_sent = {k: v for k, v in self._digest_sent.items() if k[1] == today}
        self._acted = {k: v for k, v in self._acted.items() if k[1] == today}

    def _tick(self, campaign_id: CampaignId, now: datetime) -> TickResult:
        result = TickResult(campaign_id=str(campaign_id))
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            result.reason = "campaign_not_found"
            return result

        # 1. Run-mode gate (FR-AGENT-2). UNTIL_N_VIABLE counts viable postings so far.
        viable_count = self._viable_count(campaign_id)
        if not self._runs.should_continue(
            campaign, now=now, viable_count=viable_count
        ):
            result.reason = "run_mode_stop"
            result.budget_remaining = self.remaining_budget(campaign, now)
            return result

        result.ran = True
        result.budget_remaining = self.remaining_budget(campaign, now)

        # First resume any already-started pipelines that may now be unblocked, so a
        # tick advances in-flight work even when the budget is exhausted (FR-DUR-1/4).
        self._resume_in_flight(campaign_id, result)

        # 2. Throughput cap (FR-AGENT-1): stop discovery + new pre-fill when spent.
        if result.budget_remaining <= 0:
            result.budget_exhausted = True
            result.reason = "budget_exhausted"
            self._record_intent(campaign, result, now, suffix="(daily budget reached)")
            return result

        # 3. Discovery -> scoring -> deliver digest (FR-DISC/AGENT-3/DIG-1). ---
        self._discover_and_digest(campaign, result, now)

        # 4. Approved digest items -> create Application + run pipeline. -------
        self._process_approvals(campaign, result, now)

        self._record_intent(campaign, result, now)
        return result

    # ``run_once`` is the explicit single-pass entry point (alias of tick).
    run_once = tick

    # --- discovery + digest ----------------------------------------------
    def _discover_and_digest(self, campaign, result: TickResult, now: datetime) -> None:
        if self._discovery is not None:
            try:
                found = self._discovery.run_discovery(campaign.id)
                result.discovered = len(found)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("discovery_failed", campaign_id=str(campaign.id), error=str(exc))
        # Score every fresh posting so UNTIL_N_VIABLE and the digest have scores.
        if self._scoring is not None:
            for posting in self._storage.postings.list_for_campaign(campaign.id):
                try:
                    self._scoring.score_viability(posting.id)
                except Exception:  # pragma: no cover - defensive
                    pass
        if self._digest is not None:
            # FR-DIG-1: deliver the digest at most ONCE per (campaign, UTC day) so a
            # ~60s scheduler cadence does not re-send the email + Discord ready-ping
            # on every tick.
            key = (str(campaign.id), now.date())
            if not self._digest_sent.get(key):
                try:
                    delivered = self._digest.deliver(campaign.id)
                    result.digest_rows = len(delivered.get("payload", {}).get("rows", []))
                    self._digest_sent[key] = True
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("digest_failed", campaign_id=str(campaign.id), error=str(exc))

    # --- approvals -> applications -> durable pipeline --------------------
    def _process_approvals(self, campaign, result: TickResult, now: datetime) -> None:
        for posting_id in self._approved_posting_ids(campaign.id):
            if self.remaining_budget(campaign, now) <= 0:
                result.budget_exhausted = True
                break
            app = self._ensure_application(campaign.id, posting_id)
            if app is None:
                continue
            # Only act on applications that have not yet started the pipeline.
            if app.status is not ApplicationState.APPROVED:
                continue
            self._record_acted(campaign.id, now, 1)
            self._start_pipeline(campaign, app, result)
        result.budget_remaining = self.remaining_budget(campaign, now)

    def _start_pipeline(self, campaign, app: Application, result: TickResult) -> None:
        wf_id = self._workflow_id(app.id)
        # Pivot/yield admission (FR-DUR-4): cap concurrent sandboxes. If we cannot
        # admit now, leave the app APPROVED — a later tick retries when a slot frees.
        if self._capacity is not None and not self._capacity.admit_sandbox(str(app.id)):
            log.info("sandbox_admission_deferred", application_id=str(app.id))
            return
        ctx = self._build_context(campaign, app)
        try:
            outcome = self._orch.start_workflow(WORKFLOW_NAME, wf_id, ctx=ctx).result()
        except Exception:
            # FR-DUR-2/4: a pipeline exception must NOT permanently leak the sandbox
            # slot — otherwise ``sandbox_concurrency`` failing apps deadlock all
            # pre-fill. Release the slot (and tear the session down) so capacity
            # recovers and a later/other app can be admitted.
            if self._capacity is not None:
                self._capacity.release_sandbox(str(app.id))
            self._teardown_sandbox(app.id)
            log.warning("pipeline_failed_slot_released", application_id=str(app.id))
            raise
        result.pipelines_started.append(str(app.id))
        self._apply_outcome(app, outcome, result)

    def _resume_in_flight(self, campaign_id: CampaignId, result: TickResult) -> None:
        """Re-drive applications parked at a waiting state that may now be unblocked."""
        if self._orch is None:
            return
        for app in self._storage.applications.list_for_campaign(campaign_id):
            if app.status in _IN_FLIGHT_RESUMABLE:
                # A resume that raises must NOT leak the sandbox slot nor abort the
                # whole tick (it would stall every other app). Mirror _start_pipeline:
                # release the slot + tear down the session, log, and continue.
                try:
                    campaign = self._storage.campaigns.get(campaign_id)
                    wf_id = self._workflow_id(app.id)
                    ctx = self._build_context(campaign, app)
                    outcome = self._orch.start_workflow(WORKFLOW_NAME, wf_id, ctx=ctx).result()
                    self._apply_outcome(app, outcome, result)
                except Exception:
                    if self._capacity is not None:
                        self._capacity.release_sandbox(str(app.id))
                    self._teardown_sandbox(app.id)
                    log.warning("resume_failed_slot_released", application_id=str(app.id))
                    continue

    def redrive_recovered(self, workflow_id: str) -> dict | None:
        """Re-drive ONE recovered durable workflow with a LIVE context (FR-DUR-1).

        On restart the orchestrator only knows the workflow id, not which services to
        bind. Re-starting with ``ctx=None`` would let an already-approved application
        reach ``_submit`` with no submission service and silently drop the real
        outcome (no OutcomeEvent, no terminal §7 state, no FR-LEARN-2 signal, no
        teardown). This rebuilds the same live ``PipelineContext`` used for fresh
        runs so a recovered+approved workflow completes through the real services
        (FR-LOG-1/4). Returns the workflow outcome (or None if it cannot be mapped).
        """
        if self._orch is None:
            return None
        aid = self._application_id_from_workflow(workflow_id)
        if aid is None:
            # Not an application workflow we can bind — re-drive without a context so
            # checkpointed steps still resume idempotently.
            return self._orch.start_workflow(WORKFLOW_NAME, workflow_id).result()
        app = self._storage.applications.get(aid)
        if app is None:
            return self._orch.start_workflow(WORKFLOW_NAME, workflow_id).result()
        campaign = self._storage.campaigns.get(app.campaign_id)
        ctx = self._build_context(campaign, app)
        outcome = self._orch.start_workflow(WORKFLOW_NAME, workflow_id, ctx=ctx).result()
        result = TickResult(campaign_id=str(app.campaign_id))
        self._apply_outcome(app, outcome, result)
        return outcome

    def _application_id_from_workflow(self, workflow_id: str) -> ApplicationId | None:
        prefix = "application:"
        if not workflow_id.startswith(prefix):
            return None
        return ApplicationId(workflow_id[len(prefix):])

    def _apply_outcome(self, app: Application, outcome: dict, result: TickResult) -> None:
        status = outcome.get("status")
        if status == "done":
            result.completed.append(str(app.id))
            # Terminal: release the sandbox slot so the next waiter is admitted.
            if self._capacity is not None:
                self._capacity.release_sandbox(str(app.id))
            # DUR-2: a done workflow is complete — clear its checkpoint so it is not
            # re-driven on every restart (unbounded growth + duplicate outcomes).
            self._clear_checkpoint(app.id)
        elif status in ("handoff", "awaiting_final_approval"):
            handoff_state = outcome.get("handoff_state", status)
            result.handoffs.append(str(app.id))
            # Yield capacity at the human-in-the-loop point (FR-AGENT-6, FR-DUR-4).
            if self._capacity is not None:
                state = self._latest_state(app.id)
                if state is not None:
                    self._capacity.yield_for_block(str(app.id), state)
            log.info(
                "pipeline_handoff",
                application_id=str(app.id),
                state=str(handoff_state),
            )

    # --- context construction (binds live services to the pure pipeline) --
    def _build_context(self, campaign, app: Application) -> PipelineContext:
        aid = app.id

        def _prefill() -> dict:
            current = self._storage.applications.get(aid) or app
            if self._prefill is None:
                # No pre-fill adapter wired: model a clean path to final approval.
                self._persist_status(current, ApplicationState.SANDBOX_PROVISIONING)
                return {"state": ApplicationState.AWAITING_FINAL_APPROVAL.value}
            attrs = self._storage.attributes.list_for_campaign(campaign.id)
            url = current.root_url or (self._posting_url(current.posting_id) or "")
            # ``current`` is APPROVED; PrefillService advances it to SANDBOX_PROVISIONING
            # itself, so pass it through unchanged.
            res = self._prefill.prefill_application(current, url, attrs)
            # Persist where pre-fill landed so resume/yield see the real §7 state.
            self._sync_status(current, res.state)
            return {"state": res.state.value}

        def _material_warranted() -> bool:
            if self._material is None:
                return False
            try:
                return self._material.cover_letter_warranted(campaign_default=False)
            except Exception:  # pragma: no cover - defensive
                return False

        def _prepare_material() -> dict:
            # Routing generated material to review is a human-in-the-loop gate; the
            # MaterialService emits the review notification + pending action. The
            # pipeline treats unapproved material as a hand-off (MATERIAL_REVIEW).
            return {"review_approved": False}

        def _request_approval() -> Any:
            current = self._storage.applications.get(aid) or app
            if self._final_approval is not None:
                return self._final_approval.request_approval(
                    str(aid), session_url=current.sandbox_session_url
                )
            return None

        def _submit(decision: dict) -> dict:
            current = self._storage.applications.get(aid) or app
            if self._submission is None:
                return {"recorded": False}
            from applicant.core.entities.outcome_event import OutcomeSource

            choice = (decision or {}).get("decision", "finished_by_engine")
            source = (
                OutcomeSource.MANUAL
                if choice == "submitted_by_user"
                else OutcomeSource.AUTO
            )
            # Land the AWAITING_FINAL_APPROVAL gate via a VALIDATED transition: pre-fill
            # already walked PREFILLING->MATERIAL_PREP->MATERIAL_REVIEW->AWAITING_FINAL_APPROVAL
            # legally, so ``current`` is normally already at the gate (a no-op here). If
            # the persisted state is an ILLEGAL pre-state for the gate, this raises
            # IllegalStateTransition (->409 via the global handler) instead of silently
            # force-setting the status and letting material skip MATERIAL_REVIEW (#2).
            gated = self._advance_to(current, ApplicationState.AWAITING_FINAL_APPROVAL)
            event = self._submission.record_submission(gated, source=source)
            return {"recorded": True, "outcome": event.type}

        def _teardown() -> None:
            # FR-SANDBOX-1/4: destroy the real ephemeral session (browser context /
            # Neko room + its cookies/state) so nothing leaks across applications,
            # THEN free the concurrency slot for the next waiter (FR-DUR-2).
            self._teardown_sandbox(aid)
            if self._capacity is not None:
                self._capacity.release_sandbox(str(aid))

        return PipelineContext(
            application_id=str(aid),
            prefill=_prefill,
            material_warranted=_material_warranted,
            prepare_material=_prepare_material,
            request_final_approval=_request_approval,
            submit=_submit,
            teardown=_teardown,
            approval_timeout=0.0,
        )

    # --- helpers ----------------------------------------------------------
    def _teardown_sandbox(self, application_id: ApplicationId) -> None:
        """Destroy the application's live sandbox session if any (FR-SANDBOX-4).

        Resolves the app's session via ``sandbox.for_application`` and tears it down
        so the real browser context / Neko room (and its cookies/state) does not
        persist across applications. Idempotent + defensive: a missing session or a
        driver error never breaks the terminal path.
        """
        if self._sandbox is None:
            return
        resolver = getattr(self._sandbox, "for_application", None)
        if resolver is None:
            return
        try:
            session = resolver(application_id)
            if session is not None:
                self._sandbox.teardown(session.session_id)
        except Exception:  # pragma: no cover - defensive: teardown must never raise
            log.warning("sandbox_teardown_failed", application_id=str(application_id))

    def _workflow_id(self, application_id: ApplicationId) -> str:
        return f"application:{application_id}"

    def _clear_checkpoint(self, application_id: ApplicationId) -> None:
        """Remove a terminal workflow's durable checkpoint (DUR-2). Defensive."""
        if self._orch is None:
            return
        clear = getattr(self._orch, "clear", None)
        if clear is None:
            return
        try:
            clear(self._workflow_id(application_id))
        except Exception:  # pragma: no cover - clearing must never break teardown
            log.warning("checkpoint_clear_failed", application_id=str(application_id))

    def _viable_count(self, campaign_id: CampaignId) -> int:
        if self._scoring is None:
            return 0
        count = 0
        for posting in self._storage.postings.list_for_campaign(campaign_id):
            try:
                scoring = self._scoring.score_posting(posting)
                if self._scoring.is_viable(scoring):
                    count += 1
            except Exception:  # pragma: no cover - defensive
                pass
        return count

    def _approved_posting_ids(self, campaign_id: CampaignId) -> list[JobPostingId]:
        """Posting ids the user approved in the digest (decisions keyed by posting id)."""
        approved: list[JobPostingId] = []
        seen: set[str] = set()
        postings = {str(p.id) for p in self._storage.postings.list_for_campaign(campaign_id)}
        for posting in self._storage.postings.list_for_campaign(campaign_id):
            decisions = self._storage.decisions.list_for_application(
                ApplicationId(str(posting.id))
            )
            if any(d.type is DecisionType.APPROVE for d in decisions):
                if str(posting.id) not in seen and str(posting.id) in postings:
                    approved.append(posting.id)
                    seen.add(str(posting.id))
        return approved

    def _ensure_application(
        self, campaign_id: CampaignId, posting_id: JobPostingId
    ) -> Application | None:
        """Create (or fetch) the Application row for an approved posting, in APPROVED."""
        for app in self._storage.applications.list_for_campaign(campaign_id):
            if str(app.posting_id) == str(posting_id):
                return app
        posting = self._storage.postings.get(posting_id)
        if posting is None:
            return None
        app = Application(
            id=ApplicationId(new_id()),
            campaign_id=campaign_id,
            posting_id=posting_id,
            status=ApplicationState.APPROVED,
            job_title=posting.title,
            work_mode=posting.work_mode,
            root_url=posting.source_url,
        )
        self._storage.applications.add(app)
        self._storage.commit()
        return app

    def _posting_url(self, posting_id: JobPostingId) -> str | None:
        posting = self._storage.postings.get(posting_id)
        return posting.source_url if posting is not None else None

    def _latest_state(self, application_id: ApplicationId) -> ApplicationState | None:
        app = self._storage.applications.get(application_id)
        return app.status if app is not None else None

    def _persist_status(self, app: Application, to: ApplicationState) -> Application:
        updated = app.with_status(to)
        self._storage.applications.update(updated)
        self._storage.commit()
        return updated

    def _force_status(self, app: Application, to: ApplicationState) -> Application:
        """Set the status directly (only for states pre-fill already validated).

        Used by ``_sync_status`` to mirror the §7 state pre-fill itself walked through
        legal transitions. NOT used to land the final-approval gate — that goes through
        ``_advance_to`` so an illegal pre-state can never be silently force-set (#2).
        """
        updated = dataclasses.replace(app, status=to)
        self._storage.applications.update(updated)
        self._storage.commit()
        return updated

    def _advance_to(self, app: Application, to: ApplicationState) -> Application:
        """Move ``app`` to ``to`` through a VALIDATED §7 transition.

        A no-op when already at ``to``. Otherwise routes through
        ``Application.with_status`` so an illegal pre-state raises
        ``IllegalStateTransition`` rather than being force-set (state-machine
        integrity on submit, #2).
        """
        current = self._storage.applications.get(app.id) or app
        if current.status is to:
            return current
        updated = current.with_status(to)  # raises IllegalStateTransition if illegal
        self._storage.applications.update(updated)
        self._storage.commit()
        return updated

    def _sync_status(self, app: Application, to: ApplicationState) -> Application:
        """Persist the §7 state pre-fill landed at (direct set; pre-fill validated it)."""
        current = self._storage.applications.get(app.id) or app
        if current.status is to:
            return current
        return self._force_status(current, to)

    def _record_intent(
        self, campaign, result: TickResult, now: datetime, *, suffix: str = ""
    ) -> None:
        """Record the single-sentence intent for this run (FR-AGENT-7)."""
        intent = self._intent_sentence(campaign, result)
        if suffix:
            intent = f"{intent} {suffix}"
        result.intent = intent
        try:
            self._runs.start_run(
                campaign.id,
                intent,
                stats={
                    "discovered": result.discovered,
                    "digest_rows": result.digest_rows,
                    "pipelines_started": len(result.pipelines_started),
                    "handoffs": len(result.handoffs),
                    "completed": len(result.completed),
                    "budget_remaining": result.budget_remaining,
                },
            )
        except Exception:  # pragma: no cover - defensive
            pass

    def _intent_sentence(self, campaign, result: TickResult) -> str:
        if result.budget_exhausted:
            return "Daily application budget reached; pausing new pre-fill until tomorrow."
        if result.pipelines_started:
            return (
                f"Pre-filling {len(result.pipelines_started)} approved application(s) "
                f"and delivering {result.digest_rows} digest row(s) for review."
            )
        if result.digest_rows:
            return f"Delivered a digest of {result.digest_rows} viable role(s) for your review."
        return "Scanning enabled sources for new viable roles to add to today's digest."


#: States the loop can re-drive on a later tick once the user resolves the gate.
_IN_FLIGHT_RESUMABLE = frozenset(
    {
        ApplicationState.BLOCKED_DETECTION,
        ApplicationState.BLOCKED_MISSING_ATTR,
        ApplicationState.BLOCKED_QUESTION,
        ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP,
        ApplicationState.MATERIAL_REVIEW,
        ApplicationState.AWAITING_FINAL_APPROVAL,
    }
)
