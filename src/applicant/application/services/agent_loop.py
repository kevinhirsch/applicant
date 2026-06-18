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
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from applicant.application.workflows import application_pipeline
from applicant.application.workflows.application_pipeline import (
    WORKFLOW_NAME,
    PipelineContext,
)
from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState
from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Below this many characters the candidate's known history is too thin to tailor
#: from, so deep research is worth a call before writing (see _context_is_lacking).
_THIN_SOURCE_CHARS = 400

#: Consecutive failed resume attempts after which the loop STOPS re-driving a parked
#: application and surfaces it to the operator once, instead of churning the sandbox
#: every backoff window forever (24/7 robustness).
_RESUME_FAILURE_CAP = 5


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
        criteria_service=None,
        prefill_service=None,
        material_service=None,
        submission_service=None,
        learning_service=None,
        notification_service=None,
        capacity_service=None,
        final_approval_service=None,
        sandbox=None,
        orchestrator=None,
        setup_service=None,
        research_service=None,
    ) -> None:
        self._storage = storage
        self._runs = agent_run_service
        self._discovery = discovery_service
        self._scoring = scoring_service
        self._digest = digest_service
        # FR-AGENT-3 / #6: campaign criteria so discovery + scoring + digest all use
        # the same ``get_criteria(campaign.id)`` (onboarding-seeded + learned), instead
        # of the loop scoring against empty default criteria.
        self._criteria = criteria_service
        self._prefill = prefill_service
        self._material = material_service
        self._submission = submission_service
        self._learning = learning_service
        self._notifications = notification_service
        self._capacity = capacity_service
        self._final_approval = final_approval_service
        self._sandbox = sandbox
        self._orch = orchestrator
        # Lane B (Stage 2.5): the CAPPED deep-research tool the agent escalates to
        # on a genuine company/role knowledge gap while tailoring materials. Optional
        # (None in legacy/unit tests) and self-gating (skips when the workspace
        # callback channel is off), so wiring it never changes existing behavior.
        self._research = research_service
        # FR-ONBOARD-2 / FR-OOBE-3: the automated-work gate. No NEW automated work
        # (discovery / digest delivery / pipeline starts) may run until onboarding is
        # complete AND channels are configured AND the LLM gate is open. Enforced here
        # in the 24/7 loop, not only at the HTTP layer (``require_automated_work``).
        # Already-in-flight workflows may still be re-driven (recovery), but the loop
        # never starts new work while the gate is closed. When unset (legacy tests),
        # the gate is treated as open so behavior is unchanged.
        self._setup = setup_service
        # (campaign_id, date) -> count of applications acted on that day (FR-AGENT-1).
        self._acted: dict[tuple[str, date], int] = {}
        # (campaign_id, UTC date) -> True once today's digest was delivered (FR-DIG-1).
        # Guards the loop's own delivery so a ~60s scheduler tick does not re-send the
        # digest email + Discord ready-ping every tick.
        self._digest_sent: dict[tuple[str, date], bool] = {}
        # application_id -> last time it was re-driven by _resume_in_flight (#9 backoff)
        # so a human-gated app is not re-driven every ~60s tick.
        self._last_resume: dict[str, datetime] = {}
        #: minimum seconds between resume re-drives of the same parked app (#9).
        self._resume_backoff_seconds: float = 300.0
        # application_id -> consecutive resume failures, and the set of apps we've
        # GIVEN UP re-driving (>= _RESUME_FAILURE_CAP). A permanently-stuck app would
        # otherwise churn the sandbox every backoff window forever and never alert the
        # operator; instead we stop re-driving it and surface it once. In-memory: a
        # restart re-attempts (the issue may have resolved), which is the right default.
        self._resume_failures: dict[str, int] = {}
        self._resume_giveup: set[str] = set()
        # CONC: the scheduler tick now runs OFF the event loop (worker thread). Guard the
        # read-modify-write of the per-run ledgers (``_acted`` / ``_digest_sent`` /
        # ``_last_resume``) so two overlapping ticks can't lose-update them. A single
        # re-entrant lock (the prune/record helpers nest under tick paths).
        self._state_lock = threading.RLock()
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
        with self._state_lock:
            delta = self._acted.get(key, 0)
        return self._persisted_acted_today(campaign_id, now) + delta

    def _persisted_acted_today(self, campaign_id: CampaignId, now: datetime) -> int:
        """Sum durably-recorded ``pipelines_started`` over today's agent runs (#11).

        Uses the indexed ``AgentRunRepository.count_pipelines_started_on`` (a single
        aggregate query for the day) instead of scanning the ENTIRE agent-run history
        every tick.
        """
        return int(
            self._storage.agent_runs.count_pipelines_started_on(campaign_id, now.date())
        )

    def _record_acted(self, campaign_id: CampaignId, now: datetime, n: int = 1) -> None:
        key = (str(campaign_id), now.date())
        with self._state_lock:
            self._acted[key] = self._acted.get(key, 0) + n

    def remaining_budget(self, campaign, now: datetime) -> int:
        """Applications still allowed today under the clamped per-day cap (FR-AGENT-1)."""
        budget = self._runs.daily_budget(campaign)
        return max(0, budget - self.acted_today(campaign.id, now))

    # --- the tick (one step of one campaign's work) -----------------------
    def tick(
        self, campaign_id: CampaignId, now: datetime | None = None, *, force: bool = False
    ) -> TickResult:
        """Advance one campaign's work by one step. Safe to call repeatedly.

        ``force=True`` is the operator's explicit "Run now": it runs a single pass
        even when the schedule is paused (campaign inactive) or the run-mode's
        auto-stop condition is met. It NEVER bypasses the automated-work gate
        (onboarding/LLM must be configured) nor the daily throughput cap — those are
        safety limits, not schedule state.
        """
        now = now or datetime.now(UTC)
        # The in-memory ledger holds ONLY this tick's not-yet-persisted delta; the
        # durable ``agent_runs`` carry the cross-tick total (FR-AGENT-1). Reset it at
        # tick start and clear it at tick end so the persisted count (which survives
        # restart) is the single source of truth between ticks — no double counting.
        key = (str(campaign_id), now.date())
        with self._state_lock:
            self._acted.pop(key, None)
        # CONC-3: prune per-day dedup ledgers older than today so the in-memory maps
        # do not grow unbounded over 24/7 operation.
        self._prune_daily(now.date())
        try:
            return self._tick(campaign_id, now, force=force)
        finally:
            with self._state_lock:
                self._acted.pop(key, None)

    def _automated_work_allowed(self) -> bool:
        """True when the loop may start NEW automated work (FR-ONBOARD-2/FR-OOBE-3).

        When no ``setup_service`` is wired (legacy/unit tests that drive the loop
        directly) the gate is treated as open so existing behavior is unchanged.
        """
        if self._setup is None:
            return True
        try:
            return bool(self._setup.is_automated_work_allowed())
        except Exception:  # pragma: no cover - defensive: gate failure closes the gate
            return False

    def _prune_daily(self, today: date) -> None:
        """Drop ``_digest_sent`` / ``_acted`` entries from days other than today (CONC-3)."""
        with self._state_lock:
            self._digest_sent = {k: v for k, v in self._digest_sent.items() if k[1] == today}
            self._acted = {k: v for k, v in self._acted.items() if k[1] == today}

    def _tick(self, campaign_id: CampaignId, now: datetime, force: bool = False) -> TickResult:
        result = TickResult(campaign_id=str(campaign_id))
        campaign = self._storage.campaigns.get(campaign_id)
        if campaign is None:
            result.reason = "campaign_not_found"
            return result

        # 1. Run-mode gate (FR-AGENT-2). UNTIL_N_VIABLE counts viable postings so far.
        # A manual "Run now" (force) bypasses this gate — the schedule may be paused
        # or the mode's auto-stop met, but the operator explicitly asked for one pass.
        viable_count = self._viable_count(campaign_id)
        if not force and not self._runs.should_continue(
            campaign, now=now, viable_count=viable_count
        ):
            result.reason = "run_mode_stop"
            result.budget_remaining = self.remaining_budget(campaign, now)
            return result

        result.ran = True
        result.budget_remaining = self.remaining_budget(campaign, now)

        # First resume any already-started pipelines that may now be unblocked, so a
        # tick advances in-flight work even when the budget is exhausted (FR-DUR-1/4).
        # This is recovery re-drive (NOT new automated work) so it runs even while the
        # automated-work gate is closed.
        self._resume_in_flight(campaign_id, result, now)

        # FR-ONBOARD-2 / FR-OOBE-3: no NEW automated work until onboarding is complete
        # AND channels are configured AND the LLM gate is open. With the gate closed we
        # re-drove in-flight work above but start nothing new: no discovery, no digest
        # delivery, no pipeline starts.
        if not self._automated_work_allowed():
            result.reason = "automated_work_gated"
            return result

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

    # --- criteria (FR-AGENT-3 / #6) ---------------------------------------
    def _criteria_for(self, campaign_id: CampaignId):
        """Return the campaign's SearchCriteria so discovery/scoring use it (#6).

        Without this the loop scored every posting against empty default criteria
        (a uniform neutral score), so the onboarding-seeded + learned criteria never
        reached scoring/discovery. ``None`` when no criteria service is wired.
        """
        if self._criteria is None:
            return None
        try:
            return self._criteria.get_criteria(campaign_id)
        except Exception:  # pragma: no cover - defensive
            return None

    # --- discovery + digest ----------------------------------------------
    def _discover_and_digest(self, campaign, result: TickResult, now: datetime) -> None:
        criteria = self._criteria_for(campaign.id)
        if self._discovery is not None:
            try:
                # #6: discovery uses the campaign criteria (it accepts an optional
                # criteria arg; older signatures ignore it via the fallback).
                found = self._run_discovery(campaign.id, criteria)
                result.discovered = len(found)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("discovery_failed", campaign_id=str(campaign.id), error=str(exc))
        # #8: score ONLY the postings not yet scored this campaign (was: re-score the
        # ENTIRE posting history every tick, reloading the LearningModel per posting).
        # The LearningModel is loaded once per tick inside ScoringService via the
        # criteria-aware score; here we only feed it the unscored backlog.
        if self._scoring is not None:
            for posting in self._unscored_postings(campaign.id):
                try:
                    self._scoring.score_viability(posting.id, criteria)
                except Exception:  # pragma: no cover - defensive
                    pass
        if self._digest is not None:
            # FR-DIG-1: deliver the digest at most ONCE per (campaign, UTC day) so a
            # ~60s scheduler cadence does not re-send the email + Discord ready-ping
            # on every tick.
            key = (str(campaign.id), now.date())
            with self._state_lock:
                already_sent = bool(self._digest_sent.get(key))
            if not already_sent:
                try:
                    delivered = self._digest.deliver(campaign.id)
                    result.digest_rows = len(delivered.get("payload", {}).get("rows", []))
                    with self._state_lock:
                        self._digest_sent[key] = True
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("digest_failed", campaign_id=str(campaign.id), error=str(exc))

    def _run_discovery(self, campaign_id: CampaignId, criteria):
        """Call discovery with criteria (#6), tolerating older no-criteria signatures."""
        try:
            return self._discovery.run_discovery(campaign_id, criteria)
        except TypeError:  # pragma: no cover - legacy signature without criteria
            return self._discovery.run_discovery(campaign_id)

    def _unscored_postings(self, campaign_id: CampaignId) -> list:
        """Postings not yet viability-scored this campaign (#8).

        Uses the indexed ``JobPostingRepository.list_unscored_for_campaign`` so the loop
        scores only the fresh backlog instead of re-scanning the full posting history.
        """
        return list(self._storage.postings.list_unscored_for_campaign(campaign_id))

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
            # #9: record the daily-acted budget ONLY after the pipeline actually
            # started. _start_pipeline returns False when admission is deferred (full
            # sandbox capacity); counting before would burn budget for work that never
            # started and could wrongly exhaust the day's cap.
            if self._start_pipeline(campaign, app, result):
                self._record_acted(campaign.id, now, 1)
        result.budget_remaining = self.remaining_budget(campaign, now)

    def _start_pipeline(self, campaign, app: Application, result: TickResult) -> bool:
        """Start the durable pipeline for ``app``. Returns True iff it actually started.

        Returns False when admission is deferred (sandbox capacity full) so the caller
        does NOT charge the daily-acted budget for work that never started (#9).
        """
        wf_id = self._workflow_id(app.id)
        # Pivot/yield admission (FR-DUR-4): cap concurrent sandboxes. If we cannot
        # admit now, leave the app APPROVED — a later tick retries when a slot frees.
        if self._capacity is not None and not self._capacity.admit_sandbox(str(app.id)):
            log.info("sandbox_admission_deferred", application_id=str(app.id))
            return False
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
        return True

    def _resume_in_flight(
        self, campaign_id: CampaignId, result: TickResult, now: datetime
    ) -> None:
        """Re-drive applications parked at a waiting state that may now be unblocked (#9).

        Was: re-drive EVERY app in the campaign every tick (a full scan + a workflow
        start per app). Now drives ONLY apps in a resumable state (indexed
        ``ApplicationRepository.list_by_status``) AND applies a per-app backoff so a
        human-gated app is not re-driven every ~60s tick (it churns the sandbox + the
        orchestrator for no progress until the human acts).
        """
        if self._orch is None:
            return
        for app in self._resumable_apps(campaign_id):
            if not self._resume_due(app.id, now):
                continue
            # A resume that raises must NOT leak the sandbox slot nor abort the
            # whole tick (it would stall every other app). Mirror _start_pipeline:
            # release the slot + tear down the session, log, and continue.
            try:
                campaign = self._storage.campaigns.get(campaign_id)
                wf_id = self._workflow_id(app.id)
                ctx = self._build_context(campaign, app)
                outcome = self._orch.start_workflow(WORKFLOW_NAME, wf_id, ctx=ctx).result()
                self._apply_outcome(app, outcome, result)
                self._mark_resumed(app.id, now)
                # A clean resume clears the failure streak (the app made progress).
                with self._state_lock:
                    self._resume_failures.pop(str(app.id), None)
            except Exception:
                if self._capacity is not None:
                    self._capacity.release_sandbox(str(app.id))
                self._teardown_sandbox(app.id)
                self._mark_resumed(app.id, now)
                self._record_resume_failure(app.id)
                continue

    def _record_resume_failure(self, application_id: ApplicationId) -> None:
        """Count a failed resume; after the cap, stop re-driving + alert once.

        Without this a permanently-stuck application (corrupt context, a sandbox that
        can never launch, a deleted dependency) is re-driven every backoff window
        forever — churning the sandbox and logging on every pass, never reaching the
        operator. At the cap we give up re-driving it and surface ONE deduped error.
        """
        key = str(application_id)
        with self._state_lock:
            n = self._resume_failures.get(key, 0) + 1
            self._resume_failures[key] = n
            capped = n >= _RESUME_FAILURE_CAP and key not in self._resume_giveup
            if capped:
                self._resume_giveup.add(key)
        if not capped:
            log.warning("resume_failed_slot_released", application_id=key, failures=n)
            return
        log.error("resume_giving_up", application_id=key, failures=n)
        # Surface it to the operator once (deduped), so a stuck application becomes a
        # visible action item instead of silent churn. Never let this break the tick.
        if self._notifications is not None:
            try:
                self._notifications.notify_error(
                    title="An application needs a look",
                    body=(
                        "Applicant couldn't resume one of your applications after "
                        f"{n} tries and has paused work on it. Open Activity to review it."
                    ),
                    dedup_key=f"stuck_application:{key}",
                )
            except Exception:  # pragma: no cover - notification must never break the loop
                pass

    def _resumable_apps(self, campaign_id: CampaignId) -> list[Application]:
        """Apps in a resumable state via the indexed ``list_by_status`` (#9).

        Apps we've given up re-driving (>= _RESUME_FAILURE_CAP consecutive failures)
        are excluded so a permanently-stuck app no longer churns every backoff window.
        """
        with self._state_lock:
            giveup = frozenset(self._resume_giveup)
        return [
            a
            for a in self._storage.applications.list_by_status(
                campaign_id, tuple(_IN_FLIGHT_RESUMABLE)
            )
            if str(a.id) not in giveup
        ]

    def _resume_due(self, application_id: ApplicationId, now: datetime) -> bool:
        """True if enough time has elapsed since this app was last re-driven (#9 backoff)."""
        with self._state_lock:
            last = self._last_resume.get(str(application_id))
        if last is None:
            return True
        return (now - last).total_seconds() >= self._resume_backoff_seconds

    def _mark_resumed(self, application_id: ApplicationId, now: datetime) -> None:
        with self._state_lock:
            self._last_resume[str(application_id)] = now

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
            # #4: a re-driven app that is parked at a BLOCKED_* / AWAITING_ACCOUNT state
            # must RESUME from where it stalled, not restart the whole pre-fill. Choose
            # the right ``resume_after_*`` for the persisted blocked state; only a fresh
            # (APPROVED / provisioning) app does a full ``prefill_application``.
            res = self._run_prefill_step(current, url, attrs)
            # Persist where pre-fill landed so resume/yield see the real §7 state.
            self._sync_status(current, res.state)
            return {"state": res.state.value}

        def _material_warranted() -> bool:
            # #3: material is warranted when there is generated work to do for this
            # application: a tailored resume variant always (the core FR-RESUME-1
            # output), a cover letter when the role/campaign asks for one, or a
            # deferred essay screening question pre-fill recorded.
            if self._material is None:
                return False
            return self._material_warranted_for(campaign, app)

        def _prepare_material() -> dict:
            # #3: actually GENERATE the material and route it to review. The
            # MaterialService persists each doc unapproved + emits the review
            # notification + pending action; the pipeline treats unapproved material as
            # a MATERIAL_REVIEW hand-off until the user approves the redline.
            return self._prepare_material_for(campaign, app)

        def _material_approved() -> bool:
            # #1: re-read approval from storage on EVERY re-drive (outside the
            # checkpointed material step) so an approval actually advances the pipeline.
            current = self._storage.applications.get(aid) or app
            return self._review_approved(current)

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
            material_approved=_material_approved,
            request_final_approval=_request_approval,
            submit=_submit,
            teardown=_teardown,
            approval_timeout=0.0,
        )

    def _run_prefill_step(self, current: Application, url: str, attrs):
        """Choose the right pre-fill entry point for the app's §7 state (#4).

        Was: always ``prefill_application`` (a full restart) even for an app already
        parked at AWAITING_ACCOUNT_HUMAN_STEP / BLOCKED_MISSING_ATTR — orphaning the
        in-progress session. Now a re-driven blocked app resumes from where it stalled.
        """
        status = current.status
        if status is ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP:
            return self._prefill.resume_after_account(current, attrs)
        if status is ApplicationState.BLOCKED_MISSING_ATTR:
            return self._prefill.resume_after_missing_attr(current, attrs)
        if status is ApplicationState.BLOCKED_DETECTION:
            # #2: BLOCKED_DETECTION may legally transition ONLY -> PREFILLING (§7).
            # Routing it through the full-restart ``prefill_application`` (which first
            # moves to SANDBOX_PROVISIONING) raised IllegalStateTransition and stranded
            # the app. Resume via the PREFILLING path WITHOUT tearing down the session
            # the user just cleared. Non-cautious so the just-cleared signal does not
            # immediately re-block the resume.
            resume = getattr(self._prefill, "resume_after_detection", None)
            if callable(resume):
                return resume(current, attrs, cautious=False)
        # BLOCKED_QUESTION re-drives through the normal loop; a fresh APPROVED app
        # starts the full pre-fill.
        return self._prefill.prefill_application(current, url, attrs)

    # --- material generation (#3) ----------------------------------------
    def _jd_terms(self, posting) -> list[str]:
        """Cheap JD terms for material targeting: title + work mode tokens."""
        if posting is None:
            return []
        bits = [posting.title or "", posting.work_mode or ""]
        terms: list[str] = []
        for b in bits:
            for tok in str(b).replace(",", " ").split():
                if len(tok) >= 3 and tok not in terms:
                    terms.append(tok)
        return terms

    def _material_warranted_for(self, campaign, app: Application) -> bool:
        """True when this application has generated material to produce (#3)."""
        # A tailored resume variant is the baseline FR-RESUME-1 output, so material is
        # always warranted when a material service is wired; cover-letter / deferred
        # essays are additive. Defensive: never break the pipeline.
        return self._material is not None

    def _prepare_material_for(self, campaign, app: Application) -> dict:
        """Generate the application's material + route to review (#3).

        Selects-or-generates a resume variant (truthful adaptation toward the JD),
        generates a cover letter when the role/campaign warrants one, and generates an
        answer for each deferred essay screening question pre-fill recorded. Each doc
        is stored UNAPPROVED and routed to review, so the pipeline hands off at
        MATERIAL_REVIEW until the user approves the redline.
        """
        if self._material is None:
            return {"review_approved": True}
        posting = self._storage.postings.get(app.posting_id) if app.posting_id else None
        jd_terms = self._jd_terms(posting)
        true_source = self._true_source(campaign, app, posting)
        summary: dict[str, Any] = {}
        # AUTO-ESCALATE (Lane B): before writing important material (résumé / cover
        # letter / free-text answers), escalate to the capped deep-research tool ONLY
        # when context is lacking — a genuine company/role knowledge gap — so a
        # well-covered application doesn't spend the research budget. The tool also
        # dedupes + caches per campaign and self-gates on budget / channel
        # availability, so this is free on re-use and a no-op when research is off.
        research_ctx = ""
        if self._context_is_lacking(true_source, jd_terms):
            research_ctx = self._maybe_research_company(campaign, posting)
        if research_ctx:
            true_source = f"{true_source}\n\n{research_ctx}" if true_source else research_ctx
            summary["research_used"] = True
        try:
            sel = self._material.select_or_generate(
                campaign.id, app.posting_id, jd_terms, true_source, application_id=app.id
            )
            summary["variant_id"] = str(sel.variant.id)
            summary["variant_generated"] = sel.generated
            # #1: LINK the chosen/generated variant to the application so the review
            # gate (ensure_application_submittable) can see an unapproved generated
            # variant and the next call's review-approval check covers it.
            self._link_variant(app, sel.variant.id)
        except Exception as exc:  # pragma: no cover - defensive: never crash the tick
            log.warning("material_variant_failed", application_id=str(app.id), error=str(exc))
        # Cover letter on demand (FR-RESUME-10) when the role/campaign warrants one.
        try:
            if self._material.cover_letter_warranted(campaign_default=False):
                self._material.generate_cover_letter(
                    campaign.id, app.id, true_source, jd_terms, campaign_default=False
                )
                summary["cover_letter"] = True
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("material_cover_letter_failed", application_id=str(app.id), error=str(exc))
        # Deferred essay screening questions recorded during pre-fill (FR-ANSWER-1).
        for deferred in self._deferred_questions(app):
            try:
                self._material.generate_for_deferred_question(
                    campaign.id, app.id, deferred, true_source
                )
                summary["deferred_essays"] = summary.get("deferred_essays", 0) + 1
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("material_deferred_failed", application_id=str(app.id), error=str(exc))
        # #1: ALWAYS recompute review_approved from storage on every call — True only
        # once ALL generated material (documents AND the linked generated variant) is
        # approved. The old hardcoded ``False`` (cached under a constant checkpoint key)
        # parked the pipeline before the recv gate forever; recomputing here + the
        # pipeline's re-check-on-re-drive means an approval actually advances the flow.
        summary["review_approved"] = self._review_approved(app)
        return summary

    def _context_is_lacking(self, true_source: str, jd_terms: list[str]) -> bool:
        """True when we lack enough context to write well, so deep research is worth
        a call before generating material (résumé / cover letter / free-text answers).

        Signals a genuine company/role knowledge gap (the trigger the user wants —
        research "whenever there is lacking context"): the candidate's known history
        is too thin to tailor from, or it does NOT already cover the role's required
        terms (an uncovered JD requirement). When the source already covers the role,
        research is skipped to preserve the per-campaign budget. Substring coverage
        mirrors the fit-scoring check (``score_fit``).
        """
        src = (true_source or "").strip()
        if len(src) < _THIN_SOURCE_CHARS:
            return True
        low = src.lower()
        return any(t and t.strip().lower() not in low for t in jd_terms)

    def _maybe_research_company(self, campaign, posting) -> str:
        """Escalate to the capped deep-research tool for a company/role gap (Lane B).

        Returns a short context block (research summary + key findings) to fold into
        material generation, or "" when research is not wired, the channel is off,
        the budget is spent, there is no company to research, or the run fails. The
        ResearchService itself enforces the per-campaign cap + dedupe + cache, so a
        repeated company is served free and a runaway can't burn unbounded runs.
        """
        if self._research is None or posting is None:
            return ""
        company = (getattr(posting, "company", "") or "").strip()
        if not company:
            return ""
        role = (getattr(posting, "title", "") or "").strip()
        query = f"What should a job applicant know about {company} to tailor their application?"
        try:
            report = self._research.research(
                campaign.id,
                query,
                company=company,
                role=role,
            )
        except Exception:  # pragma: no cover - service degrades, never raises
            return ""
        if report is None or not (report.summary or report.key_findings):
            return ""
        lines = [f"[Company research — {company}]", report.summary.strip()]
        for finding in report.key_findings[:6]:
            lines.append(f"- {finding}")
        return "\n".join(p for p in lines if p).strip()

    def _link_variant(self, app: Application, variant_id) -> None:
        """Persist the chosen/generated resume variant on the application row (#1/#4)."""
        current = self._storage.applications.get(app.id) or app
        if getattr(current, "resume_variant_id", None) == variant_id:
            return
        updated = dataclasses.replace(current, resume_variant_id=variant_id)
        self._storage.applications.update(updated)
        self._storage.commit()

    def _review_approved(self, app: Application) -> bool:
        """True only when ALL generated material for ``app`` is approved (#1).

        Covers BOTH generated documents (cover letters / screening answers) AND the
        app's linked generated resume variant. Computed from storage every call so a
        just-approved item advances the pipeline past MATERIAL_REVIEW.
        """
        try:
            for d in self._storage.documents.list_for_application(app.id):
                if not d.approved:
                    return False
        except Exception:  # pragma: no cover - defensive
            return False
        current = self._storage.applications.get(app.id) or app
        variant_id = getattr(current, "resume_variant_id", None)
        if variant_id is not None:
            variant = self._storage.resume_variants.get(variant_id)
            if variant is not None and not variant.approved:
                return False
        return True

    def _true_source(self, campaign, app: Application, posting) -> str:
        """Flatten the candidate's TRUE source for truthful generation (#3)."""
        try:
            return self._material.true_attribute_text(campaign.id, "")
        except Exception:  # pragma: no cover - defensive
            return ""

    def _deferred_questions(self, app: Application) -> list[dict]:
        """Open deferred essay screening questions for this app from pending actions."""
        out: list[dict] = []
        try:
            for pa in self._storage.pending_actions.list_open(app.campaign_id):
                if (
                    getattr(pa, "kind", "") == "agent_question"
                    and str(getattr(pa, "application_id", "")) == str(app.id)
                ):
                    payload = pa.payload or {}
                    out.append(
                        {
                            "label": payload.get("question"),
                            "selector": payload.get("field_selector"),
                            "url": payload.get("url"),
                        }
                    )
        except Exception:  # pragma: no cover - defensive
            pass
        return out

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
        """Count viable postings from the PERSISTED viability score (#8).

        Was: re-score every posting every tick (and reload the LearningModel per
        posting). Now reads the durable ``viability_score`` the scoring step already
        persisted, so UNTIL_N_VIABLE costs an O(n) read, not an O(n) re-score.
        """
        if self._scoring is None:
            return 0
        threshold = getattr(self._scoring, "threshold", 70)
        count = 0
        for posting in self._storage.postings.list_for_campaign(campaign_id):
            score = getattr(posting, "viability_score", None)
            if score is None:
                # Not yet scored (e.g. first tick before discovery scored it). Fall
                # back to a one-off score so the gate is never under-counted.
                try:
                    # #8: score against the campaign's criteria (was: empty default
                    # criteria, a uniform neutral score that ignored onboarding/learned
                    # criteria).
                    scoring = self._scoring.score_posting(
                        posting, self._criteria_for(campaign_id)
                    )
                    if self._scoring.is_viable(scoring):
                        count += 1
                except Exception:  # pragma: no cover - defensive
                    pass
                continue
            if score * 100.0 >= threshold:
                count += 1
        return count

    def _approved_posting_ids(self, campaign_id: CampaignId) -> list[JobPostingId]:
        """Posting ids the user approved in the digest (#10).

        Uses the indexed ``DecisionRepository.list_approved_postings_for_campaign``
        (one query) instead of the prior N+1 — a decisions lookup per posting plus a
        full postings scan.
        """
        seen: set[str] = set()
        out: list[JobPostingId] = []
        for pid in self._storage.decisions.list_approved_postings_for_campaign(
            campaign_id
        ):
            if str(pid) not in seen:
                out.append(JobPostingId(str(pid)))
                seen.add(str(pid))
        return out

    def _ensure_application(
        self, campaign_id: CampaignId, posting_id: JobPostingId
    ) -> Application | None:
        """Create (or fetch) the Application row for an approved posting, in APPROVED.

        #10: prefers ``ApplicationRepository.get_by_posting`` (indexed) over scanning
        the campaign's whole application list to find the row for one posting.
        """
        existing = self._app_by_posting(campaign_id, posting_id)
        if existing is not None:
            return existing
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

    def _app_by_posting(
        self, campaign_id: CampaignId, posting_id: JobPostingId
    ) -> Application | None:
        """Fetch the application for a posting via the indexed ``get_by_posting`` (#10)."""
        return self._storage.applications.get_by_posting(campaign_id, posting_id)

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
