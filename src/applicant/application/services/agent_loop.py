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
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
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

#: Consecutive failed APPROVED-application pipeline starts after which the loop
#: STOPS retrying that application and surfaces it to the operator once, instead of
#: retrying a permanently-poison posting forever (lens 04 #32). Mirrors
#: ``_RESUME_FAILURE_CAP``/``ResumeLedger`` above.
_APPROVAL_START_FAILURE_CAP = 5


@dataclass
class ResumeLedger:
    """Cross-tick resume bookkeeping that must OUTLIVE a single AgentLoop instance.

    The 24/7 scheduler rebuilds a fresh ``AgentLoop`` every tick (to isolate the DB
    Session — see ``container._build_tick_services``), so any per-instance state is
    discarded each tick. The resume **backoff** (#9) and the resume-**failure cap**
    both need to persist ACROSS ticks, or they reset every ~60s and never take
    effect: a parked application would be re-driven every tick, and a permanently
    failing one would never reach the give-up cap. The container creates ONE of these
    for the process and injects it into every per-tick loop, with its own lock since
    each per-tick loop has a different ``_state_lock``.
    """

    last_resume: dict[str, datetime] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    giveup: set[str] = field(default_factory=set)
    lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass
class ApprovalStartLedger:
    """Cross-tick bookkeeping for failures starting the pipeline on an APPROVED
    application (lens 04 #31/#32).

    ``_process_approvals`` drives every APPROVED application's pipeline start each
    tick. Before this ledger, a start that raised (a poison posting — a bad context,
    a permanently-failing adapter call, ...) propagated straight out of
    ``_process_approvals``, which (a) aborted the rest of THIS tick's approved batch
    (siblings after the poison one in iteration order never got attempted — #31) and
    (b) since the application row is left APPROVED, was retried from scratch on every
    later tick forever with no give-up (#32).

    Exactly like ``ResumeLedger``, the scheduler rebuilds a fresh ``AgentLoop`` every
    tick (per-tick Session isolation, ``container._build_tick_services``), so the
    failure streak + give-up set must live OUTSIDE the loop instance or they would
    reset every tick and the cap would never trip. Unlike ``ResumeLedger`` /
    ``DigestLedger`` / ``PresubmitBlockLedger`` (each explicitly constructed once and
    injected into every per-tick loop by the container), no explicit instance is
    injected here yet — ``AgentLoop.__init__`` falls back to the single
    process-lived ``_DEFAULT_APPROVAL_START_LEDGER`` module object below when none is
    given, so every loop built in the process (the shared one and every per-tick
    rebuild) shares the SAME ledger without requiring a container change. Callers
    that want an isolated ledger (tests, or once the container is updated to inject
    its own like the other ledgers) may still pass one explicitly.
    """

    failures: dict[str, int] = field(default_factory=dict)
    giveup: set[str] = field(default_factory=set)
    lock: threading.RLock = field(default_factory=threading.RLock)


#: The process-lived default described in ``ApprovalStartLedger`` above. Module-level
#: (not per-instance) so it survives every ``AgentLoop`` rebuild even without an
#: explicit ``approval_start_ledger=`` injection at the call site.
_DEFAULT_APPROVAL_START_LEDGER = ApprovalStartLedger()


@dataclass
class DigestLedger:
    """Cross-tick digest delivery guard that OUTLIVES a single AgentLoop instance.

    The 24/7 scheduler rebuilds a fresh ``AgentLoop`` every tick, so the per-instance
    ``_digest_sent`` dict resets each tick and the "already delivered today" guard is
    lost — causing the digest email + ready-ping to re-send every ~60s. This ledger
    persists the guard across rebuilds. The container creates ONE of these for the
    process and injects it into every per-tick loop.
    """

    sent: dict[tuple[str, date], bool] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass
class PresubmitBlockLedger:
    """Cross-tick record of pre-submit safety blocks (dark-engine audit #61).

    G07's pre-submit safety checks (scam/ghost-job, duplicate cooldown,
    per-company volume cap, eligibility/work-authorization -- see
    ``presubmit_safety.py``) run every tick against every APPROVED application.
    Before this ledger, a check that raised ``PresubmitBlock`` was handled with
    only ``log.info("presubmit_blocked")`` and a ``continue`` -- the posting
    stayed APPROVED forever with no user-visible reason and no way to resolve
    it short of a config change the operator could not even see they needed.
    This ledger persists the LATEST block per application (which check, its
    plain-language reason, first/last-seen timestamps, how many ticks it has
    recurred) plus an ``overridden`` set the operator can add an application id
    to so the loop proceeds past the block on ITS OWN informed decision --
    review-before-submit (FR-REVIEW) still gates the actual final submit
    downstream, so an override here only lets prefill/materials generation
    START, never auto-submits anything.

    The scheduler rebuilds a fresh ``AgentLoop`` every tick (per-tick Session
    isolation, ``container._build_tick_services``), so this must live OUTSIDE
    the loop instance or the whole record (and any override) would vanish the
    moment the next tick's fresh instance runs -- exactly like
    ``ResumeLedger``/``DigestLedger`` above. The container creates ONE of these
    for the process and injects it into every per-tick loop.
    """

    blocks: dict[str, dict] = field(default_factory=dict)
    overridden: set[str] = field(default_factory=set)
    lock: threading.RLock = field(default_factory=threading.RLock)


#: Plain-language "why nothing happened" sentences for the two early-return gates
#: a SCHEDULED tick can hit before any new work starts (dark-engine audit #64).
#: ``campaign_not_found`` isn't here (no campaign row to attach a run to);
#: ``budget_exhausted`` isn't here either — it already records its own intent via
#: ``_record_intent``. Keyed by ``TickResult.reason``.
SKIP_REASON_SENTENCES: dict[str, str] = {
    "run_mode_stop": "Paused — your run schedule says to hold off starting new work right now.",
    "automated_work_gated": (
        "Waiting on setup — finish connecting a model and your profile before I can "
        "start new work."
    ),
}


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
    #: #180 — the documented, machine-checkable set of instance attributes that are
    #: ALLOWED to live for only one tick (they are rebuilt fresh each tick and resetting
    #: them is correct). The scheduler rebuilds a fresh ``AgentLoop`` every tick, so any
    #: instance attribute NOT in this set — and not a ``*_ledger`` process-lived object
    #: injected into every loop — would silently reset each tick (the #180 footgun).
    #: ``assert_no_undeclared_cross_tick_state`` turns "I added a new per-instance dict
    #: that quietly resets each tick" from a silent bug into a loud, catchable failure.
    __per_tick_state__: frozenset[str] = frozenset(
        {
            "_acted",  # (campaign, date) -> count acted today; per-tick scratch.
            "_state_lock",  # guards this tick's per-run scratch ledgers.
        }
    )

    #: Public alias of the per-tick declaration (introspection / tooling).
    per_tick_fields = __per_tick_state__

    #: Instance attributes that MUST outlive a single tick. Each is either a process-
    #: lived ledger injected by the container (so cross-tick state survives the rebuild)
    #: or one of its read-through aliases. Anything mutable-and-stateful that is neither
    #: declared per-tick here nor cross-tick is the footgun #180 guards against.
    __cross_tick_state__: frozenset[str] = frozenset(
        {
            "_resume_ledger",
            "_digest_ledger",
            "_last_resume",
            "_resume_failures",
            "_resume_giveup",
            "_digest_sent",
            "_presubmit_block_ledger",
            "_presubmit_blocks",
            "_presubmit_overridden",
            "_approval_start_ledger",
            "_approval_start_failures",
            "_approval_start_giveup",
        }
    )

    def assert_no_undeclared_cross_tick_state(self) -> None:
        """Fail loudly if a mutable instance ledger is neither per-tick nor cross-tick.

        Catches the #180 footgun at construction/test time: a newly-added per-instance
        ``dict``/``set`` that resets every tick (because the scheduler rebuilds the loop)
        with nothing to flag it. Either declare it in ``__per_tick_state__`` (resetting is
        intended) or route it through a process-lived ledger listed in
        ``__cross_tick_state__``.
        """
        allowed = self.__per_tick_state__ | self.__cross_tick_state__
        offenders = []
        for name, value in vars(self).items():
            if name in allowed:
                continue
            # Only mutable containers can silently lose cross-tick state; injected
            # services/configs/scalars are stateless w.r.t. the tick cadence.
            if isinstance(value, (dict, set, list)) and value is not None:
                offenders.append(name)
        if offenders:
            raise AssertionError(
                "AgentLoop has undeclared mutable per-instance state that the per-tick "
                f"rebuild would silently reset: {sorted(offenders)}. Declare it in "
                "__per_tick_state__ (reset is intended) or move it into a process-lived "
                "ledger listed in __cross_tick_state__ (#180)."
            )

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
        resume_ledger: ResumeLedger | None = None,
        digest_ledger: DigestLedger | None = None,
        llm=None,
        loop_toolset_factory=None,
        # G07 pre-submit safety: optional dict of parameters.
        # When set, the loop runs scam/ghost-job detection before each pipeline.
        # ``None`` (default) skips all checks — byte-identical to before.
        presubmit_safety_params: dict | None = None,
        # dark-engine audit #61: process-lived ledger of pre-submit safety blocks
        # (reason + override), shared across per-tick rebuilds by the container.
        presubmit_block_ledger: PresubmitBlockLedger | None = None,
        # lens 04 #31/#32: process-lived ledger of APPROVED-application pipeline-start
        # failures (streak + give-up), shared across per-tick rebuilds. Defaults to the
        # module-level ``_DEFAULT_APPROVAL_START_LEDGER`` (see ``ApprovalStartLedger``)
        # rather than a fresh per-call instance, so it stays cross-tick-persistent even
        # where the container does not (yet) inject an explicit one.
        approval_start_ledger: ApprovalStartLedger | None = None,
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
        # FR-MIND-6 / FR-CUA-2: the agent-callable tool surface for the AUTONOMOUS loop.
        # Today memory/skills/recall (and the bounded desktop action) reach the loop only
        # as passive CONTEXT; this seam lets a tool-capable model CHOOSE to call them
        # mid-reasoning. Both are optional/defaulted: ``llm`` is the loop's reasoning
        # model, and ``loop_toolset_factory(campaign_id, llm) -> LoopToolset | None`` is a
        # process-lived builder that returns the registered tool set (reusing the chat
        # ChatToolbox + every existing guard) ONLY when the feature is opted in and the
        # model advertises tool calling. ``None`` (the default) ⇒ no tool path is ever
        # entered, so the loop behaves byte-identically to today. The toolset is built
        # PER CAMPAIGN on demand (the tools are campaign-scoped) and is never cached on the
        # instance, so the scheduler's per-tick rebuild can't leak campaign state across
        # ticks (FR-MIND-10); the staging/dedupe substrate it writes through is the SAME
        # process-lived curation ledger the rest of the system uses.
        self._llm = llm
        self._loop_toolset_factory = loop_toolset_factory
        # (campaign_id, date) -> count of applications acted on that day (FR-AGENT-1).
        self._acted: dict[tuple[str, date], int] = {}
        # (campaign_id, UTC date) -> True once today's digest was delivered (FR-DIG-1).
        # Guards the loop's own delivery so a ~60s scheduler tick does not re-send the
        # digest email + Discord ready-ping every tick. This guard lives in a
        # DigestLedger that OUTLIVES this instance: the scheduler rebuilds the loop every
        # tick, so a per-instance dict would reset and re-deliver every ~60s. The
        # container creates ONE ledger for the process and injects it into every per-tick
        # loop; when none is given (unit tests / direct use) a fresh per-instance one is
        # used.
        self._digest_ledger = digest_ledger if digest_ledger is not None else DigestLedger()
        self._digest_sent = self._digest_ledger.sent
        #: minimum seconds between resume re-drives of the same parked app (#9).
        self._resume_backoff_seconds: float = 300.0
        # Resume bookkeeping (#9 backoff + the failure cap) lives in a ledger that
        # OUTLIVES this instance: the scheduler rebuilds the loop every tick, so
        # per-instance dicts would reset each tick and neither the backoff nor the
        # give-up cap would ever take effect. The container injects one shared ledger;
        # when none is given (unit tests / direct use) a fresh per-instance one is used.
        # ``last_resume``: application_id -> last re-drive time (#9). ``failures``:
        # consecutive resume failures. ``giveup``: apps we've stopped re-driving and
        # surfaced once (>= _RESUME_FAILURE_CAP). Aliased for readability + tests; all
        # mutations take ``self._resume_ledger.lock`` (NOT the per-instance state lock).
        self._resume_ledger = resume_ledger if resume_ledger is not None else ResumeLedger()
        self._last_resume = self._resume_ledger.last_resume
        self._resume_failures = self._resume_ledger.failures
        self._resume_giveup = self._resume_ledger.giveup
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
        # G07: pre-submit safety parameters. When non-None, the loop runs safety
        # checks before starting each pipeline. ``None`` (default) skips all checks
        # so existing callers are byte-identical.
        self._presubmit_safety_params = presubmit_safety_params
        # dark-engine audit #61: pre-submit block bookkeeping lives in a ledger that
        # OUTLIVES this instance for the same reason resume/digest bookkeeping does —
        # the scheduler rebuilds the loop every tick, so a per-instance dict would lose
        # every block reason (and any operator override) the moment the next tick's
        # fresh instance runs. The container injects one shared ledger; when none is
        # given (unit tests / direct use) a fresh per-instance one is used.
        self._presubmit_block_ledger = (
            presubmit_block_ledger
            if presubmit_block_ledger is not None
            else PresubmitBlockLedger()
        )
        self._presubmit_blocks = self._presubmit_block_ledger.blocks
        self._presubmit_overridden = self._presubmit_block_ledger.overridden
        # lens 04 #31/#32: APPROVED-application start-failure bookkeeping lives in a
        # ledger that OUTLIVES this instance for the same reason resume/digest/
        # presubmit bookkeeping does -- the scheduler rebuilds the loop every tick, so
        # a per-instance dict would lose the failure streak (and the give-up flag) the
        # moment the next tick's fresh instance runs, letting a persistently-failing
        # posting be retried forever. When no ledger is injected explicitly, every
        # loop in the process shares ``_DEFAULT_APPROVAL_START_LEDGER`` so this is
        # cross-tick-persistent by default (see ``ApprovalStartLedger`` docstring).
        self._approval_start_ledger = (
            approval_start_ledger
            if approval_start_ledger is not None
            else _DEFAULT_APPROVAL_START_LEDGER
        )
        self._approval_start_failures = self._approval_start_ledger.failures
        self._approval_start_giveup = self._approval_start_ledger.giveup

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
            self._acted = {k: v for k, v in self._acted.items() if k[1] == today}
        with self._digest_ledger.lock:
            stale = [k for k in self._digest_sent if k[1] != today]
            for k in stale:
                self._digest_sent.pop(k, None)

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
            self._record_skip_reason(campaign, result, now)
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
            self._record_skip_reason(campaign, result, now)
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

    # --- agent-callable tools (FR-MIND-6 / FR-CUA-2) ----------------------
    def tools_for(self, campaign_id: CampaignId):
        """Build the loop's registered tool set for ``campaign_id``, or ``None``.

        Returns ``None`` (no tool path — today's behavior) unless a toolset factory was
        injected AND it yields an offerable tool set for this campaign. The factory
        itself enforces the opt-in + tool-capable-model gates, so the default (no factory)
        is a clean no-op. Built fresh per call (never cached on the instance) so the
        per-tick rebuild can't leak campaign state across ticks (FR-MIND-10).
        """
        if self._loop_toolset_factory is None:
            return None
        try:
            return self._loop_toolset_factory(campaign_id, self._llm)
        except Exception:  # pragma: no cover - defensive: tool wiring never breaks a tick
            return None

    def run_assisted_reasoning(
        self, campaign_id: CampaignId, system: str, prompt: str
    ) -> str | None:
        """Let the loop's tool-capable model CHOOSE to call the registered tools.

        Drives the bounded tool-dispatch loop (memory ``remember``/``forget``,
        ``save_playbook``/``update_playbook``, ``recall``, and the bounded ``desktop``
        action) through the SAME guarded handlers the chat path uses: writes STAGE for
        review (FR-MIND-9), an authority-claiming write is refused (FR-MIND-11), the
        desktop action inherits the stop-boundary (FR-CUA), and each tool respects the
        FR-UI-4 toggle. Returns the model's final text, or ``None`` when no tool path is
        available (feature off / non-tool model / nothing offered) — so a caller can fall
        back to its non-tool behavior unchanged.
        """
        toolset = self.tools_for(campaign_id)
        if toolset is None:
            return None
        return toolset.run(self._llm, system, prompt)

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
        # #344 cold-start gate: with zero criteria the scorer returns the neutral 0.75
        # (which clears the default threshold), so an ungated run would surface arbitrary
        # postings before the user has said what they want. Decline discovery until at
        # least one concrete criterion is configured; scoring/digest of any existing
        # backlog still proceeds so nothing already found is stranded. The gate only
        # applies when a criteria service is wired (the production path) — legacy/unit
        # setups with no criteria service keep their prior unconditional behavior.
        from applicant.core.rules.discovery_gate import has_any_criterion

        gate_applies = self._criteria is not None
        criteria_ready = (not gate_applies) or has_any_criterion(criteria)
        if self._discovery is not None and criteria_ready:
            try:
                # #6: discovery uses the campaign criteria (it accepts an optional
                # criteria arg; older signatures ignore it via the fallback).
                found = self._run_discovery(campaign.id, criteria)
                result.discovered = len(found)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("discovery_failed", campaign_id=str(campaign.id), error=str(exc))
        elif self._discovery is not None:
            log.info("discovery_declined_no_criteria", campaign_id=str(campaign.id))
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
            with self._digest_ledger.lock:
                already_sent = bool(self._digest_sent.get(key))
            if not already_sent:
                try:
                    delivered = self._digest.deliver(campaign.id)
                    result.digest_rows = len(delivered.get("payload", {}).get("rows", []))
                    with self._digest_ledger.lock:
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
            # lens 04 #32: an application whose pipeline start has failed
            # ``_APPROVAL_START_FAILURE_CAP`` times in a row has already been
            # surfaced to the operator once (see ``_record_approval_start_failure``)
            # and is given up on -- skip it silently rather than retrying a
            # permanently-poison posting every tick forever.
            with self._approval_start_ledger.lock:
                given_up_on_start = str(app.id) in self._approval_start_giveup
            if given_up_on_start:
                continue
            # G07: run pre-submit safety checks before starting the pipeline. When a
            # check blocks, PERSIST the reason (dark-engine audit #61 -- previously
            # only ``log.info`` recorded it, so the posting sat APPROVED forever with
            # nothing user-visible) and skip; the posting remains APPROVED so either a
            # future re-drive with the condition resolved, or an explicit operator
            # override, may proceed.
            if self._presubmit_safety_params is not None:
                posting = self._storage.postings.get(posting_id)
                if posting is not None:
                    app_key = str(app.id)
                    with self._presubmit_block_ledger.lock:
                        overridden = app_key in self._presubmit_overridden
                    if overridden:
                        # The operator explicitly chose to proceed past the safety
                        # flag for THIS application (#61) -- skip the checks and
                        # clear the bookkeeping now that it is actually starting.
                        self._clear_presubmit_block(app.id)
                    else:
                        from applicant.application.services.presubmit_safety import (
                            PresubmitBlock,
                            check_duplicate_application,
                            check_eligibility,
                            check_per_company_volume_cap,
                            check_scam_or_ghost_job,
                        )

                        try:
                            check_scam_or_ghost_job(
                                posting,
                                max_age_days=self._presubmit_safety_params.get(
                                    "max_age_days", 90
                                ),
                                reference_date=now.date(),
                            )
                            check_duplicate_application(
                                campaign.id,
                                posting,
                                self._storage,
                                cooldown_days=self._presubmit_safety_params.get(
                                    "duplicate_cooldown_days", 30
                                ),
                                reference_date=now.date(),
                            )
                            check_per_company_volume_cap(
                                campaign.id,
                                posting,
                                self._storage,
                                max_per_day=self._presubmit_safety_params.get(
                                    "max_apps_per_company_per_day", 3
                                ),
                                reference_date=now.date(),
                            )
                            if self._presubmit_safety_params.get(
                                "eligibility_enabled", True
                            ):
                                check_eligibility(
                                    campaign.id,
                                    posting,
                                    self._storage,
                                )
                        except PresubmitBlock as exc:
                            self._record_presubmit_block(app, posting, exc, now)
                            continue
            # lens 04 #31/#32: a start that raises must not be fatal to the rest of
            # this tick's approved batch -- mirror _resume_in_flight's per-app
            # isolation (log + continue) rather than letting the exception propagate
            # out of this loop and strand every approved posting still waiting its
            # turn. _start_pipeline already released the sandbox slot + tore down the
            # session before re-raising (FR-DUR-2/4); we just isolate it here and
            # count it toward the give-up cap so a permanently-poison posting stops
            # being retried forever instead of failing (and blocking siblings) every
            # tick.
            try:
                started = self._start_pipeline(campaign, app, result)
            except Exception as exc:
                log.warning(
                    "approval_start_exception_isolated",
                    application_id=str(app.id),
                    error=str(exc),
                )
                self._record_approval_start_failure(app.id)
                continue
            # #9: record the daily-acted budget ONLY after the pipeline actually
            # started. _start_pipeline returns False when admission is deferred (full
            # sandbox capacity); counting before would burn budget for work that never
            # started and could wrongly exhaust the day's cap.
            if started:
                self._record_acted(campaign.id, now, 1)
                # A clean start clears the failure streak (the app made progress).
                self._clear_approval_start_failure(app.id)
        result.budget_remaining = self.remaining_budget(campaign, now)

    def _record_approval_start_failure(self, application_id: ApplicationId) -> None:
        """Count a failed pipeline start; after the cap, stop retrying + alert once.

        Mirrors ``_record_resume_failure``: without this a permanently-failing
        APPROVED application (a poison posting whose start always raises -- a
        corrupt context, an adapter that can never succeed, ...) would be retried
        from scratch every tick forever, logging on every pass and never reaching
        the operator (lens 04 #32). At the cap we give up retrying it and surface
        ONE deduped error.
        """
        key = str(application_id)
        with self._approval_start_ledger.lock:
            n = self._approval_start_failures.get(key, 0) + 1
            self._approval_start_failures[key] = n
            capped = n >= _APPROVAL_START_FAILURE_CAP and key not in self._approval_start_giveup
            if capped:
                self._approval_start_giveup.add(key)
        if not capped:
            log.warning("approval_start_failed", application_id=key, failures=n)
            return
        log.error("approval_start_giving_up", application_id=key, failures=n)
        # Surface it to the operator once (deduped), so a stuck approval becomes a
        # visible action item instead of silent churn every tick. Never let this
        # break the tick.
        if self._notifications is not None:
            try:
                self._notifications.notify_error(
                    title="An application needs a look",
                    body=(
                        "Applicant couldn't start one of your approved applications "
                        f"after {n} tries and has paused work on it. Open Activity to "
                        "review it."
                    ),
                    dedup_key=f"stuck_approval_start:{key}",
                )
            except Exception:  # pragma: no cover - notification must never break the loop
                pass

    def _clear_approval_start_failure(self, application_id: ApplicationId) -> None:
        """Clear a start-failure streak after a clean start (mirrors resume's clear)."""
        with self._approval_start_ledger.lock:
            self._approval_start_failures.pop(str(application_id), None)

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
                with self._resume_ledger.lock:
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
        with self._resume_ledger.lock:
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
        with self._resume_ledger.lock:
            giveup = frozenset(self._resume_giveup)
        return [
            a
            for a in self._storage.applications.list_by_status(
                campaign_id, tuple(_IN_FLIGHT_RESUMABLE)
            )
            if str(a.id) not in giveup
        ]

    def list_given_up(self, campaign_id: CampaignId | None = None) -> list[dict]:
        """Applications the loop has stopped re-driving (dark-engine audit #62).

        Reads the SAME process-lived ``ResumeLedger`` the tick loop writes to (the
        one the container injects into every per-tick loop), so this reflects
        exactly what the running scheduler has given up on — not a stale snapshot.
        Without this method nothing could ever list the give-up set; the only
        visibility was the one deduped notification fired at cap time (#62). When
        ``campaign_id`` is given, only that campaign's rows are returned; an
        application that has since been deleted from storage is silently skipped
        rather than raising (the ledger key can outlive the row).
        """
        with self._resume_ledger.lock:
            entries = [(k, self._resume_failures.get(k, 0)) for k in self._resume_giveup]
        rows: list[dict] = []
        for app_id, failures in entries:
            app = self._storage.applications.get(ApplicationId(app_id))
            if app is None:
                continue
            if campaign_id is not None and app.campaign_id != campaign_id:
                continue
            posting = None
            if app.posting_id is not None:
                posting = self._storage.postings.get(app.posting_id)
            rows.append(
                {
                    "application_id": app_id,
                    "campaign_id": str(app.campaign_id),
                    "status": app.status.value,
                    "failures": failures,
                    "job_title": app.job_title or (posting.title if posting else None),
                    "company": posting.company if posting else None,
                    "role_name": app.role_name,
                }
            )
        rows.sort(key=lambda r: r["failures"], reverse=True)
        return rows

    def retry_given_up(self, application_id: str) -> bool:
        """Clear one application's give-up flag so the loop re-drives it (#62).

        The normal per-tick resume sweep (``_resumable_apps``) excludes anything
        in the give-up set, and nothing previously cleared that flag short of a
        full process restart (which rebuilds a fresh, empty ``ResumeLedger``) —
        leaving a stuck application permanently invisible AND permanently stuck.
        This clears the failure streak too (not just the give-up flag) so the app
        gets a full fresh run of the failure cap rather than tripping it again on
        the very next failure, and clears the backoff timestamp so the very next
        tick is free to re-drive it immediately (subject to the normal per-tick
        cadence) instead of waiting out a stale backoff window. Returns ``False``
        (a no-op) when the application was not in the give-up set.
        """
        key = str(application_id)
        with self._resume_ledger.lock:
            if key not in self._resume_giveup:
                return False
            self._resume_giveup.discard(key)
            self._resume_failures.pop(key, None)
            self._last_resume.pop(key, None)
        log.info("resume_retry_cleared", application_id=key)
        return True

    # --- G07 pre-submit safety blocks (dark-engine audit #61) --------------
    def _record_presubmit_block(self, app: Application, posting, exc, now: datetime) -> None:
        """Persist ONE pre-submit safety block so it survives the tick (#61).

        Previously ``PresubmitBlock`` was handled with only ``log.info`` -- the
        posting stayed APPROVED forever with nothing an operator could see or
        act on. This writes the latest check/reason into the process-lived
        ``PresubmitBlockLedger`` (surfaced by ``list_blocked``) and keeps counting
        how many ticks it has recurred, so a persistently-blocked application
        reads as "blocked 12 times since Tuesday", not a one-off blip.
        """
        key = str(app.id)
        with self._presubmit_block_ledger.lock:
            existing = self._presubmit_blocks.get(key)
            first_blocked_at = (
                existing["first_blocked_at"] if existing else now.isoformat()
            )
            times_blocked = (existing["times_blocked"] if existing else 0) + 1
            self._presubmit_blocks[key] = {
                "application_id": key,
                "campaign_id": str(app.campaign_id),
                "check": exc.check,
                "reason": exc.reason,
                "first_blocked_at": first_blocked_at,
                "last_blocked_at": now.isoformat(),
                "times_blocked": times_blocked,
            }
        log.info(
            "presubmit_blocked",
            application_id=key,
            posting_id=str(posting.id),
            check=exc.check,
            reason=exc.reason,
            times_blocked=times_blocked,
        )
        # Surface it to the operator ONCE per application (deduped on first block,
        # not every recurring tick -- unlike the resume give-up cap this has no
        # threshold, it would otherwise refire every ~60s tick forever), mirroring
        # ``_record_resume_failure``'s notification above. Never let this break
        # the tick.
        if times_blocked == 1 and self._notifications is not None:
            try:
                self._notifications.notify_error(
                    title="An application needs a look",
                    body=(
                        f"A safety check stopped one of your applications: {exc.reason} "
                        "Open Tracker to review it or start it anyway."
                    ),
                    dedup_key=f"presubmit_blocked:{key}",
                )
            except Exception:  # pragma: no cover - notification must never break the loop
                pass

    def _clear_presubmit_block(self, application_id: ApplicationId) -> None:
        """Drop one application's block record + override flag (#61).

        Called once the application actually starts the pipeline (an operator
        override let it through) so stale bookkeeping does not linger.
        """
        key = str(application_id)
        with self._presubmit_block_ledger.lock:
            self._presubmit_blocks.pop(key, None)
            self._presubmit_overridden.discard(key)

    def list_blocked(self, campaign_id: CampaignId | None = None) -> list[dict]:
        """Applications the pre-submit safety gate has stopped on (dark-engine audit #61).

        G07 checks (scam/ghost-job, duplicate cooldown, per-company volume cap,
        eligibility/work-authorization) run every tick against every APPROVED
        application; a block previously left the posting APPROVED forever with
        only a log line -- no reason surfaced, no way to act short of guessing at
        a config change. Reads the SAME process-lived ``PresubmitBlockLedger``
        the tick loop writes to, so this always reflects live loop state, not a
        stale snapshot. Only applications STILL in the APPROVED state are
        returned (one that has since been overridden/resolved, deleted, or
        otherwise moved on is not a currently-blocked row anymore, even if a
        stale ledger entry lingers until the next re-check clears it).
        """
        with self._presubmit_block_ledger.lock:
            entries = list(self._presubmit_blocks.values())
        rows: list[dict] = []
        for entry in entries:
            app = self._storage.applications.get(ApplicationId(entry["application_id"]))
            if app is None or app.status is not ApplicationState.APPROVED:
                continue
            if campaign_id is not None and app.campaign_id != campaign_id:
                continue
            posting = self._storage.postings.get(app.posting_id) if app.posting_id else None
            rows.append(
                {
                    **entry,
                    "status": app.status.value,
                    "job_title": app.job_title or (posting.title if posting else None),
                    "company": posting.company if posting else None,
                    "role_name": app.role_name,
                }
            )
        rows.sort(key=lambda r: r["last_blocked_at"], reverse=True)
        return rows

    def override_blocked(self, application_id: str) -> bool:
        """Let the operator proceed with ONE blocked application despite the
        safety flag (dark-engine audit #61).

        Marks the application so the NEXT tick's pre-submit gate skips the G07
        checks and starts the pipeline -- the operator's own informed decision,
        not the engine self-authorizing anything: review-before-submit
        (FR-REVIEW) still gates the actual final submit downstream, so this only
        lets prefill/materials generation begin. Returns ``False`` (a no-op)
        when the application is not currently in the blocked set.
        """
        key = str(application_id)
        with self._presubmit_block_ledger.lock:
            if key not in self._presubmit_blocks:
                return False
            self._presubmit_overridden.add(key)
        log.info("presubmit_block_overridden", application_id=key)
        return True

    def resume_backoff_status(
        self, application_id: str, *, now: datetime | None = None
    ) -> dict | None:
        """Countdown to the next resume attempt for a currently-blocked application
        (dark-engine audit #78).

        Each parked application (``BLOCKED_*``/``AWAITING_*``/``MATERIAL_REVIEW`` --
        see ``_IN_FLIGHT_RESUMABLE``) is re-driven at most every
        ``_resume_backoff_seconds`` (300s) via the SAME process-lived
        ``ResumeLedger`` the tick loop reads/writes (``_resume_due``/``_mark_resumed``)
        -- so after the user clears a blocker (answers a question, supplies a missing
        detail, approves a redline) the application can sit for up to 5 minutes with
        no visible sign anything will happen. This reads ``last_resume`` + the fixed
        backoff window to give a blocked card an honest "retrying at HH:MM:SS"
        instead of silence. ``now`` is injectable for deterministic tests; real
        callers leave it ``None`` (the real wall clock). Returns ``None`` when the
        application isn't currently in a resumable/blocked state, was never resumed
        yet (eligible on the very next tick -- nothing to count down), or has been
        given up on (surfaced instead via the stuck-applications list, #62).
        """
        app = self._storage.applications.get(ApplicationId(str(application_id)))
        if app is None or app.status not in _IN_FLIGHT_RESUMABLE:
            return None
        key = str(application_id)
        with self._resume_ledger.lock:
            last = self._last_resume.get(key)
            given_up = key in self._resume_giveup
        if last is None or given_up:
            return None
        next_retry_at = last + timedelta(seconds=self._resume_backoff_seconds)
        remaining = max(0.0, (next_retry_at - (now or datetime.now(UTC))).total_seconds())
        return {
            "application_id": key,
            "status": app.status.value,
            "last_resume_at": last.isoformat(),
            "next_retry_at": next_retry_at.isoformat(),
            "seconds_remaining": round(remaining),
        }

    def _resume_due(self, application_id: ApplicationId, now: datetime) -> bool:
        """True if enough time has elapsed since this app was last re-driven (#9 backoff)."""
        with self._resume_ledger.lock:
            last = self._last_resume.get(str(application_id))
        if last is None:
            return True
        return (now - last).total_seconds() >= self._resume_backoff_seconds

    def _mark_resumed(self, application_id: ApplicationId, now: datetime) -> None:
        with self._resume_ledger.lock:
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
            ats = self._ats_domain(url)
            # #44 (dark-engine audit) Reflexion recall — READ side, BEFORE the fill
            # attempt: surface any verbal lesson learned from a PRIOR failure on this
            # same ATS so a known-bad domain is handled more carefully instead of
            # blindly repeating what already failed here.
            lessons = self._recall_lessons_for(ats)
            # #4: a re-driven app that is parked at a BLOCKED_* / AWAITING_ACCOUNT state
            # must RESUME from where it stalled, not restart the whole pre-fill. Choose
            # the right ``resume_after_*`` for the persisted blocked state; only a fresh
            # (APPROVED / provisioning) app does a full ``prefill_application``.
            res = self._run_prefill_step(
                current, url, attrs, cautious_hint=bool(lessons)
            )
            # Persist where pre-fill landed so resume/yield see the real §7 state.
            self._sync_status(current, res.state)
            # #44 Reflexion self-reflection — WRITE side, AFTER a real failure: a
            # concrete field-level failure during THIS pass is distilled into a
            # verbal lesson for the next attempt on this ATS (previously written but
            # never invoked anywhere in the loop).
            self._reflect_on_prefill_failure(campaign.id, ats, res)
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

    def _run_prefill_step(
        self, current: Application, url: str, attrs, *, cautious_hint: bool = False
    ):
        """Choose the right pre-fill entry point for the app's §7 state (#4).

        Was: always ``prefill_application`` (a full restart) even for an app already
        parked at AWAITING_ACCOUNT_HUMAN_STEP / BLOCKED_MISSING_ATTR — orphaning the
        in-progress session. Now a re-driven blocked app resumes from where it stalled.

        ``cautious_hint`` (#44 dark-engine audit, Reflexion recall): True when a
        verbal lesson exists for this ATS from a PRIOR failure. It only changes the
        ``BLOCKED_DETECTION`` resume below, where the loop otherwise hard-codes
        ``cautious=False`` on the assumption a human just cleared the block — a
        domain with a recorded failure lesson re-checks for the same signal instead
        of blindly trusting that assumption again.
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
            # immediately re-block the resume — UNLESS a recalled lesson (#44) says
            # this ATS has burned the loop before, in which case stay cautious.
            resume = getattr(self._prefill, "resume_after_detection", None)
            if callable(resume):
                return resume(current, attrs, cautious=bool(cautious_hint))
        # BLOCKED_QUESTION re-drives through the normal loop; a fresh APPROVED app
        # starts the full pre-fill.
        return self._prefill.prefill_application(current, url, attrs)

    # --- Reflexion: verbal failure lessons per ATS (#306, dark-engine audit #44) -
    @staticmethod
    def _ats_domain(url: str) -> str:
        """Derive the same registrable-host key ``PrefillService`` uses for routines.

        Mirrors ``PrefillService._routine_domain`` so recalled lessons key on the
        exact same namespace as the AWM routine store (one ATS == one domain
        string across both learning surfaces). Best-effort: a bare/relative URL
        falls back to the raw string so the key is at least stable.
        """
        from urllib.parse import urlparse

        try:
            host = urlparse(url).netloc
        except Exception:  # noqa: BLE001 — never crash deriving a key
            host = ""
        return (host or url or "").lower()

    def _recall_lessons_for(self, ats: str) -> list:
        """Recall lessons for ``ats`` before a fill attempt (read side, #44).

        Best-effort + defensive: no learning service wired, no ats, or a raising
        store all degrade to "no lessons" rather than blocking the pre-fill.
        """
        if self._learning is None or not ats:
            return []
        try:
            lessons = self._learning.recall_lessons(ats)
        except Exception:  # pragma: no cover - defensive: recall must never break the loop
            return []
        if lessons:
            log.info("prefill_recalled_lessons", ats=ats, lesson_count=len(lessons))
        return lessons

    def _reflect_on_prefill_failure(
        self, campaign_id: CampaignId, ats: str, res
    ) -> None:
        """Write a Reflexion lesson from a real field-level pre-fill failure (#44).

        ``PrefillResult.fields_failed`` is the concrete, already-recorded signal a
        real fill attempt failed on this pass (selector/label/error per field) —
        the most recent one is distilled into a verbal lesson so the NEXT attempt
        on this ATS recalls it before filling. Best-effort: never breaks the loop.
        """
        if self._learning is None or not ats:
            return
        failed = getattr(res, "fields_failed", None)
        if not failed:
            return
        last = failed[-1]
        try:
            self._learning.reflect_on_failure(
                {
                    "ats": ats,
                    "step": str(last.get("selector") or last.get("label") or "fill"),
                    "error": str(last.get("error", "")),
                }
            )
        except Exception:  # pragma: no cover - defensive: reflection must never break the loop
            log.debug("reflect_on_failure raised", exc_info=True)
        # #47 dark-engine audit: additive assisted-reasoning refinement, LOOP_TOOLS-
        # gated. The raw lesson above always echoes the last failed selector/error
        # verbatim; whether that is actually worth generalizing into a reusable
        # per-ATS note (and how to phrase it) is a genuinely ambiguous judgment call
        # the templated write can't make. Best-effort + fully additive: it never
        # replaces the write above, and it is a no-op unless the operator has opted
        # into LOOP_TOOLS with a tool-capable model (default off ⇒ unchanged tick).
        self._maybe_assisted_reflect(campaign_id, ats, last)

    def _maybe_assisted_reflect(
        self, campaign_id: CampaignId, ats: str, last: dict
    ) -> None:
        """Let the loop's tool-capable model optionally refine the failure into a
        reusable playbook note (LOOP_TOOLS, FR-MIND-6 / FR-CUA-2 — dark-engine
        audit #47: the only consumer of ``run_assisted_reasoning``/``tools_for``).

        The model MAY call ``recall`` to check prior lessons for this domain and
        ``save_playbook``/``update_playbook`` a short, reusable note for the next
        attempt here — the SAME guarded chat tools, now reachable from the
        autonomous loop instead of only the chat assistant. It may also do nothing;
        the prompt says so explicitly. ``run_assisted_reasoning`` itself already
        no-ops (returns ``None``) when the setting is off or the model doesn't
        advertise tool calling, so this call is a clean no-op by default. Wrapped in
        its own try/except so a bad turn here can never break the tick (mirrors the
        defensive posture of the raw write above).
        """
        try:
            step = str(last.get("selector") or last.get("label") or "fill")
            error = str(last.get("error", ""))
            system = (
                "You are the autonomous job-application loop's assistant. A "
                "pre-fill attempt just failed on an application-tracking site. "
                "You may call `recall` to check for prior lessons about this exact "
                "domain, then OPTIONALLY call `save_playbook` or `update_playbook` "
                "with a short, reusable note for the next attempt on this domain. "
                "Only save something genuinely useful for next time — it is fine "
                "to do nothing."
            )
            prompt = (
                f"Domain: {ats}\nFailed step: {step}\nError: {error}\n"
                "Decide whether this is worth remembering, and if so, save it."
            )
            self.run_assisted_reasoning(campaign_id, system, prompt)
        except Exception:  # pragma: no cover - defensive: never break the tick
            log.debug("assisted_reflect_failed", exc_info=True)

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
        # dark-engine audit #76: capture WHICH research informed this application's
        # materials (company/query + a short excerpt + up to 5 sources), not just the
        # bare ``research_used`` flag -- populated by ``_maybe_research_company`` only
        # when a fresh/cached report actually came back. This dict is folded into the
        # checkpointed ``material`` step result below, so a read-model can surface real
        # provenance instead of a flag alone.
        research_provenance: dict[str, Any] = {}
        if self._context_is_lacking(true_source, jd_terms):
            research_ctx = self._maybe_research_company(
                campaign, posting, provenance=research_provenance
            )
        if research_ctx:
            true_source = f"{true_source}\n\n{research_ctx}" if true_source else research_ctx
            summary["research_used"] = True
            if research_provenance:
                summary["research_provenance"] = research_provenance
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

    def _maybe_research_company(
        self, campaign, posting, *, provenance: dict[str, Any] | None = None
    ) -> str:
        """Escalate to the capped deep-research tool for a company/role gap (Lane B).

        Returns a short context block (research summary + key findings) to fold into
        material generation, or "" when research is not wired, the channel is off,
        the budget is spent, there is no company to research, or the run fails. The
        ResearchService itself enforces the per-campaign cap + dedupe + cache, so a
        repeated company is served free and a runaway can't burn unbounded runs.

        When ``provenance`` is given and a report actually comes back, it is
        populated in place with the company/query, a short summary excerpt, up to 5
        sources, and whether the report was served from cache (dark-engine audit
        #76) -- the caller folds this into the checkpointed step result so a
        read-model can show WHICH research informed the application, not just that
        research happened.
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
        if provenance is not None:
            provenance["company"] = company
            provenance["query"] = query
            provenance["summary_excerpt"] = report.summary.strip()[:280]
            provenance["cached"] = bool(report.cached)
            provenance["sources"] = [
                {
                    "title": str(s.get("title") or "").strip(),
                    "url": str(s.get("url") or "").strip(),
                }
                for s in (report.sources or [])[:5]
                if isinstance(s, dict) and (s.get("title") or s.get("url"))
            ]
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
        persist across applications. Retries up to 3 times on failure before giving
        up, so a transient error (network blip, container busy) does not leak a
        sandbox session. Idempotent + defensive: a missing session or a
        driver error never breaks the terminal path.
        """
        if self._sandbox is None:
            return
        resolver = getattr(self._sandbox, "for_application", None)
        if resolver is None:
            return
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                session = resolver(application_id)
                if session is not None:
                    self._sandbox.teardown(session.session_id)
                return  # success
            except Exception as exc:  # pragma: no cover - defensive: teardown must never raise
                last_exc = exc
                log.warning(
                    "sandbox_teardown_failed",
                    application_id=str(application_id),
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < 2:
                    time.sleep(1.0 * (2 ** attempt))  # exponential backoff: 1s, 2s
        log.error(
            "sandbox_teardown_gave_up",
            application_id=str(application_id),
            error=str(last_exc),
        )

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
        current = self._storage.applications.get(app.id) or app
        if current.status is to:
            return current
        updated = dataclasses.replace(current, status=to)
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

    def _record_skip_reason(self, campaign, result: TickResult, now: datetime) -> None:
        """Persist a per-tick "why nothing happened" reason (dark-engine audit #64).

        A scheduled tick that stops before any new work starts (run-mode paused/
        stopped, or the automated-work gate still closed) used to ``return`` before
        ``_record_intent`` ran at all — so a paused/gated campaign left NO
        persisted trace of the skip; the status surface just showed whatever the
        last REAL run happened to say, with no visible reason nothing is
        happening now. This persists the reason as a run's intent + a machine
        ``skip_reason`` in its stats (the existing free-form JSON blob — no schema
        change needed).

        Only persists on a reason CHANGE (compared against the campaign's own
        latest persisted run): a 24/7-gated campaign ticks every ~60s, and without
        this dedup guard it would write one row per tick forever. The scheduler's
        own ``last_tick``/``next_tick`` heartbeat (already surfaced) carries the
        "am I still alive" signal; this carries WHY nothing is happening.
        """
        try:
            latest = self._storage.agent_runs.latest(campaign.id)
            prior_reason = (latest.stats or {}).get("skip_reason") if latest is not None else None
            if prior_reason == result.reason:
                return
            sentence = SKIP_REASON_SENTENCES.get(
                result.reason, "Not starting any new work right now."
            )
            result.intent = sentence
            self._runs.start_run(
                campaign.id, sentence, stats={"skip_reason": result.reason}
            )
        except Exception:  # pragma: no cover - defensive: a skip note is best-effort
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
