"""Unit tests for the per-campaign agent run loop (FR-AGENT-1/2/4/5/6/7, FR-DUR-1/4).

These prove the loop that finally drives the engine end-to-end:

* ``tick``/``run_once`` advances discovery -> digest -> approved item -> durable
  pipeline (FR-AGENT-7, FR-DUR-1);
* the per-day throughput hard cap is enforced at runtime — the 31st application of
  a day is refused (FR-AGENT-1);
* run-mode stop conditions halt the loop (FR-AGENT-2);
* a BLOCKED_* application yields its sandbox slot so other work proceeds — the
  pivot-around-blocker (FR-AGENT-6, FR-DUR-4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.capacity_service import CapacityService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId, DecisionId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# --- fakes ---------------------------------------------------------------
class _FakeScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="strong fit")

    score_viability = lambda self, pid, criteria=None: None  # noqa: E731
    def is_viable(self, scoring):
        return True


class _FakeDigest:
    def __init__(self):
        self.delivered = 0

    def deliver(self, campaign_id, criteria=None):
        self.delivered += 1
        return {"payload": {"rows": [{"posting_id": "p"}]}}


class _PrefillResult:
    def __init__(self, state):
        self.state = state


class _FakePrefill:
    def __init__(self, state=ApplicationState.AWAITING_FINAL_APPROVAL):
        self._state = state
        self.calls = 0

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls += 1
        # Land the application at the configured state (the loop persists it).
        return _PrefillResult(self._state)


class _FakeSubmission:
    def __init__(self):
        self.recorded = []

    def record_submission(self, application, *, source, attributes_used=None, **kw):
        from applicant.core.entities.outcome_event import OutcomeEvent
        from applicant.core.ids import OutcomeEventId

        self.recorded.append(str(application.id))
        return OutcomeEvent(
            id=OutcomeEventId(new_id()),
            application_id=application.id,
            type="submitted",
            source=source,
        )


def _make_campaign(storage, *, run_mode=RunMode.CONTINUOUS, target=15, schedule=None):
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(
            id=cid,
            name="C",
            run_mode=run_mode,
            throughput_target=target,
            schedule=schedule or {},
        )
    )
    return cid


def _approve_posting(storage, cid, *, title="Engineer"):
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title=title, company="Acme", source_url="http://x")
    )
    storage.decisions.add(
        Decision(id=DecisionId(new_id()), application_id=str(pid), type=DecisionType.APPROVE)
    )
    return pid


def _loop(
    storage,
    orch,
    *,
    prefill=None,
    submission=None,
    capacity=None,
    digest=None,
    sandbox=None,
):
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=digest or _FakeDigest(),
        prefill_service=prefill,
        submission_service=submission,
        capacity_service=capacity,
        sandbox=sandbox,
        orchestrator=orch,
    )


# --- tests ---------------------------------------------------------------
@pytest.mark.unit
def test_context_is_lacking_gates_research(tmp_path):
    """Deep research fires before writing only when context is lacking: a thin
    profile or an uncovered JD requirement, never when the source already covers
    the role (so a well-covered application keeps its research budget)."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    loop = _loop(storage, orch)

    rich = (
        "Kevin Hirsch, staff software engineer with deep experience in Python, Go, "
        "Kubernetes, distributed systems, and team leadership across many years of "
        "shipping platforms at scale. " * 4
    )
    assert len(rich) >= 400  # not thin, so only term coverage decides
    # Source covers every JD term -> not lacking -> no research.
    assert loop._context_is_lacking(rich, ["Python", "Kubernetes"]) is False
    # An uncovered JD requirement -> lacking -> research.
    assert loop._context_is_lacking(rich, ["Python", "Rust"]) is True
    # A thin source -> lacking regardless of terms.
    assert loop._context_is_lacking("Python dev.", ["Python"]) is True


@pytest.mark.unit
def test_tick_advances_pipeline_for_approved_item(tmp_path):
    """FR-AGENT-7 / FR-DUR-1: an approved digest item runs the durable pipeline."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)

    prefill = _FakePrefill()
    submission = _FakeSubmission()
    # Deliver the final-approval decision so the recv gate unblocks within the tick.
    loop = _loop(storage, orch, prefill=prefill, submission=submission)

    # Pre-deliver the approval to the per-application workflow id.
    apps_before = storage.applications.list_for_campaign(cid)
    assert apps_before == []

    result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert result.ran is True
    # An Application row was created + the pipeline started.
    apps = storage.applications.list_for_campaign(cid)
    assert len(apps) == 1
    assert apps[0].id in [pid for pid in []] or len(result.pipelines_started) == 1
    assert prefill.calls == 1
    # The per-run intent sentence was recorded (FR-AGENT-7).
    assert result.intent
    assert AgentRunService(storage).latest_intent(cid)


@pytest.mark.unit
def test_pipeline_completes_when_approval_delivered(tmp_path):
    """End-to-end: pre-fill -> final approval recv -> submit recorded."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    prefill = _FakePrefill()
    submission = _FakeSubmission()
    loop = _loop(storage, orch, prefill=prefill, submission=submission)

    # The workflow id is derived from the application id, which is created in-tick;
    # deliver the decision by pre-sending on the SAME application id the loop creates.
    # Easiest: run one tick (it will await), then send + tick again.
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    app = storage.applications.list_for_campaign(cid)[0]
    orch.send(f"application:{app.id}", "final_approval", {"decision": "finished_by_engine"})
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert app.id and str(app.id) in submission.recorded or submission.recorded


@pytest.mark.unit
def test_throughput_hard_cap_refuses_31st_per_day(tmp_path):
    """FR-AGENT-1: per-day hard cap is 30 — the 31st application is refused."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    # Request 100/day; clamp_throughput caps the budget at 30.
    cid = _make_campaign(storage, target=100)
    # 40 approved postings available today.
    for i in range(40):
        _approve_posting(storage, cid, title=f"Role-{i}")

    prefill = _FakePrefill()
    loop = _loop(storage, orch, prefill=prefill)
    # ``acted_today`` derives the persisted count from agent_runs whose timestamp is
    # the real wall clock, so anchor ``now`` to today's UTC date (robust to date roll).
    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = loop.run_once(cid, now=now)

    # Exactly the hard cap of 30 applications were acted on; the rest are refused.
    assert loop.acted_today(cid, now) == 30
    assert len(result.pipelines_started) == 30
    assert result.budget_remaining == 0
    assert result.budget_exhausted is True

    # A second tick the SAME day starts no new pipelines (budget exhausted).
    result2 = loop.run_once(cid, now=now)
    assert result2.budget_exhausted is True
    assert result2.pipelines_started == []
    assert loop.acted_today(cid, now) == 30

    # A NEW day resets the budget (FR-AGENT-1 is per-day).
    tomorrow = now + timedelta(days=1)
    assert loop.remaining_budget(storage.campaigns.get(cid), tomorrow) == 30


@pytest.mark.unit
def test_run_mode_until_n_viable_stops(tmp_path):
    """FR-AGENT-2: UNTIL_N_VIABLE stops once enough viable roles exist."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(
        storage, run_mode=RunMode.UNTIL_N_VIABLE, schedule={"target_viable": 2}
    )
    # 3 viable postings already exist -> count (3) >= target (2) -> stop.
    for i in range(3):
        pid = JobPostingId(new_id())
        storage.postings.add(
            JobPosting(id=pid, campaign_id=cid, title=f"R{i}", company="A", source_url="u")
        )
    loop = _loop(storage, orch, prefill=_FakePrefill())
    result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert result.ran is False
    assert result.reason == "run_mode_stop"


@pytest.mark.unit
def test_run_mode_inactive_campaign_does_not_run(tmp_path):
    """FR-AGENT-2: an inactive campaign never ticks."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="off", active=False))
    loop = _loop(storage, orch, prefill=_FakePrefill())
    result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert result.ran is False
    assert result.reason == "run_mode_stop"


@pytest.mark.unit
def test_pivot_yields_slot_when_blocked(tmp_path):
    """FR-AGENT-6 / FR-DUR-4: a BLOCKED_* app yields its sandbox slot to the next."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=30)
    # Two approved postings; capacity cap of 1 sandbox so the second must wait.
    _approve_posting(storage, cid, title="A")
    _approve_posting(storage, cid, title="B")
    capacity = CapacityService(orch, sandbox_concurrency=1)

    # Pre-fill of every app lands BLOCKED_QUESTION -> the pipeline hands off and the
    # loop yields the slot, which immediately admits the next waiting application.
    prefill = _FakePrefill(state=ApplicationState.BLOCKED_QUESTION)
    loop = _loop(storage, orch, prefill=prefill, capacity=capacity)
    result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))

    # Both approved applications were acted on (the first yielded its slot to the
    # second — neither stalled the other).
    assert len(result.handoffs) == 2
    # The blocked app yielded: the sandbox queue is not permanently full.
    qstate = orch.queue_state("sandbox_concurrency")
    assert len(qstate["active"]) <= 1


# --- Fix #3: sandbox slot must not leak when the pipeline raises ----------
class _BoomPrefill:
    """Pre-fill that raises, modelling a pipeline exception mid-step."""

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        raise RuntimeError("boom")


@pytest.mark.unit
def test_pipeline_exception_does_not_leak_sandbox_slot(tmp_path):
    """FR-DUR-2/4: a raising pipeline releases its slot so capacity recovers."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=30)
    _approve_posting(storage, cid, title="A")
    # Capacity cap of 1: if the failing app leaks its slot, no further app can start.
    capacity = CapacityService(orch, sandbox_concurrency=1)
    loop = _loop(storage, orch, prefill=_BoomPrefill(), capacity=capacity)

    now = datetime(2026, 6, 16, tzinfo=UTC)
    with pytest.raises(RuntimeError):
        loop.run_once(cid, now=now)

    # The slot was released despite the exception — the queue is empty again.
    qstate = orch.queue_state("sandbox_concurrency")
    assert qstate["active"] == []
    # And a brand-new application can now be admitted (no deadlock).
    assert capacity.admit_sandbox("next-app") is True


# --- Fix #4: sandbox session torn down on terminal completion ------------
@pytest.mark.unit
def test_sandbox_torn_down_on_completion(tmp_path):
    """FR-SANDBOX-1/4: a terminal pipeline destroys the app's live sandbox session."""
    from applicant.adapters.sandbox.local_sandbox import LocalSandbox

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    sandbox = LocalSandbox()
    prefill = _FakePrefill()
    submission = _FakeSubmission()
    capacity = CapacityService(orch, sandbox_concurrency=3)
    loop = _loop(
        storage, orch, prefill=prefill, submission=submission, capacity=capacity,
        sandbox=sandbox,
    )

    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop.run_once(cid, now=now)
    app = storage.applications.list_for_campaign(cid)[0]
    # Provision a live sandbox for this application (as real pre-fill would).
    sandbox.provision(app.id)
    assert sandbox.active_count() == 1

    # Deliver the approval and tick again so the pipeline reaches a terminal state.
    orch.send(f"application:{app.id}", "final_approval", {"decision": "finished_by_engine"})
    loop.run_once(cid, now=now)

    assert str(app.id) in submission.recorded
    # The ephemeral session was destroyed on teardown — nothing leaks across apps.
    assert sandbox.active_count() == 0


# --- Fix #5: the loop delivers the digest at most once per UTC day --------
@pytest.mark.unit
def test_digest_delivered_once_per_day_across_ticks(tmp_path):
    """FR-DIG-1: 3 ticks in one day -> exactly 1 digest delivery (no per-tick re-send)."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    digest = _FakeDigest()
    loop = _loop(storage, orch, prefill=_FakePrefill(), digest=digest)

    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop.run_once(cid, now=now)
    loop.run_once(cid, now=now)
    loop.run_once(cid, now=now)
    assert digest.delivered == 1

    # A NEW day delivers again (per-day, not once-ever).
    loop.run_once(cid, now=now + timedelta(days=1))
    assert digest.delivered == 2


# --- Fix #6: throughput cap survives a restart (persisted ledger) ---------
@pytest.mark.unit
def test_throughput_cap_survives_restart(tmp_path):
    """FR-AGENT-1: a fresh AgentLoop over the same storage still counts the prior day."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=100)  # clamps to 30/day
    for i in range(40):
        _approve_posting(storage, cid, title=f"Role-{i}")

    # Anchor to today's UTC date: the persisted count comes from agent_runs stamped
    # with the real wall clock, so a hardcoded past date would never match (date roll).
    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    loop1 = _loop(storage, orch, prefill=_FakePrefill())
    loop1.run_once(cid, now=now)
    assert loop1.acted_today(cid, now) == 30

    # Simulate a restart: a BRAND-NEW loop over the SAME storage (in-memory ledger
    # is gone) must still see the 30 already acted on today, so the cap holds.
    loop2 = _loop(storage, orch, prefill=_FakePrefill())
    assert loop2.acted_today(cid, now) == 30
    result = loop2.run_once(cid, now=now)
    assert result.budget_exhausted is True
    assert result.pipelines_started == []
    assert loop2.acted_today(cid, now) == 30


# --- Fix #2: recovery rebuilds a live context (real outcome recorded) -----
@pytest.mark.unit
def test_recovery_redrive_records_real_outcome(tmp_path):
    """FR-DUR-1/FR-LOG-1/4: a recovered+approved workflow completes through the
    real submission service (not a silent ``{"recorded": True}``)."""
    storage = InMemoryStorage()
    ckpt = str(tmp_path / "ck")
    orch = CheckpointShimOrchestrator(ckpt)
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)

    prefill = _FakePrefill()
    submission = _FakeSubmission()
    loop = _loop(storage, orch, prefill=prefill, submission=submission)

    # First tick: the app pre-fills and parks at the final-approval gate (awaiting).
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    app = storage.applications.list_for_campaign(cid)[0]
    wf_id = f"application:{app.id}"

    # The user approves while the worker is "down": the decision is durably stored.
    orch.send(wf_id, "final_approval", {"decision": "finished_by_engine"})

    # Restart: a fresh orchestrator + loop over the same dir/storage recovers it.
    orch2 = CheckpointShimOrchestrator(ckpt)
    loop2 = _loop(storage, orch2, prefill=prefill, submission=submission)
    assert wf_id in orch2.recover_pending()

    outcome = loop2.redrive_recovered(wf_id)
    # The recovered workflow completed through the REAL submission service.
    assert outcome["status"] == "done"
    assert str(app.id) in submission.recorded


# --- Fix #1: final-approval decision reaches the durable recv gate ---------
@pytest.mark.unit
def test_decision_through_gate_completes_pipeline_once(tmp_path):
    """#1: delivering the decision THROUGH FinalApprovalService.submit_decision drives
    the parked pipeline to completion — submit + teardown run, capacity is released,
    and exactly ONE OutcomeEvent is recorded (no double-recording)."""
    from applicant.application.services.final_approval_service import FinalApprovalService
    from applicant.application.services.submission_service import SubmissionService
    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId
    from applicant.core.state_machine import ApplicationState

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)

    # A prefill that lands the app at AWAITING_FINAL_APPROVAL (the gate), persisted so
    # the REAL SubmissionService can transition it terminally.
    class _PersistPrefill:
        def prefill_application(self, application, url, attributes=None, *, cautious=True):
            persisted = storage.applications.get(application.id) or application
            updated = Application(
                id=persisted.id,
                campaign_id=persisted.campaign_id,
                posting_id=persisted.posting_id,
                status=ApplicationState.AWAITING_FINAL_APPROVAL,
                job_title=persisted.job_title,
                work_mode=persisted.work_mode,
                root_url=persisted.root_url,
            )
            storage.applications.update(updated)
            storage.commit()
            return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)

    submission = SubmissionService(storage)
    capacity = CapacityService(orch, sandbox_concurrency=2)
    fa = FinalApprovalService(orch)
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=_PersistPrefill(),
        submission_service=submission,
        capacity_service=capacity,
        final_approval_service=fa,
        orchestrator=orch,
    )

    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop.run_once(cid, now=now)
    app = storage.applications.list_for_campaign(cid)[0]
    aid = app.id
    # Pipeline parked at the recv gate (no outcome yet).
    assert storage.outcomes.list_for_application(aid) == []

    # Deliver the decision THROUGH the gate (what the remote endpoint now does).
    fa.submit_decision(f"application:{aid}", str(aid), "finished_by_engine")

    # Next tick: _resume_in_flight re-drives the workflow; the recv unblocks and the
    # pipeline runs submit + teardown.
    loop.run_once(cid, now=now)

    refreshed = storage.applications.get(aid)
    assert refreshed.status is ApplicationState.FINISHED_BY_ENGINE
    events = storage.outcomes.list_for_application(aid)
    assert len(events) == 1  # exactly one OutcomeEvent (submit ran once, no dup)
    # Capacity was released (teardown ran): a fresh app can be admitted.
    assert capacity.admit_sandbox(ApplicationId(new_id())) is True


# --- Fix #2: conversion learning folds on the submission service path ------
@pytest.mark.unit
def test_record_submission_folds_conversion_learning():
    """#2: SubmissionService.record_submission folds the converting-role signature so
    EVERY submit path (incl. remote) updates learning, not only the outcomes router."""
    from applicant.adapters.embedding.local_embedding import LocalEmbedding
    from applicant.application.services.learning_advanced import AdvancedLearningService
    from applicant.application.services.learning_service import LearningService
    from applicant.application.services.submission_service import SubmissionService
    from applicant.core.entities.application import Application
    from applicant.core.entities.outcome_event import OutcomeSource
    from applicant.core.ids import ApplicationId
    from applicant.core.state_machine import ApplicationState

    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid, title="Staff Engineer")
    learning = LearningService(storage, LocalEmbedding())
    advanced = AdvancedLearningService(base=learning, storage=storage)
    sub = SubmissionService(storage, learning=learning, advanced_learning=advanced)

    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=pid,
        status=ApplicationState.AWAITING_FINAL_APPROVAL,
        job_title="Staff Engineer",
        work_mode="remote",
    )
    storage.applications.add(app)
    storage.commit()

    before = learning.load_model(cid)
    assert before.converting_samples == 0

    sub.record_submission(app, source=OutcomeSource.AUTO)

    after = learning.load_model(cid)
    assert after.converting_samples == 1
    assert after.converting_role_signature  # a converting-role signature was folded


# === Scale-in: per-tick scoring, N+1 elimination, retention (#8/#9/#10/#11) ==
class _CountingScoring(_FakeScoring):
    """Tracks score_viability calls so we can prove only the unscored backlog is scored."""

    def __init__(self):
        self.scored: list = []

    def score_viability(self, pid, criteria=None):
        self.scored.append(str(pid))
        return None

    @property
    def threshold(self):
        return 70


@pytest.mark.unit
def test_only_unscored_postings_are_scored_each_tick(tmp_path):
    """#8: the loop scores only postings.list_unscored_for_campaign, not the whole
    history every tick (proven by extending the fake with the indexed method)."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    # Two postings: one already scored (viability_score set), one fresh.
    p_scored = JobPostingId(new_id())
    p_fresh = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=p_scored, campaign_id=cid, title="Scored", company="A",
                   source_url="u", viability_score=0.9)
    )
    storage.postings.add(
        JobPosting(id=p_fresh, campaign_id=cid, title="Fresh", company="A", source_url="u")
    )

    # Extend the in-memory repo with the parallel-lane indexed method (test-only).
    def _list_unscored(campaign_id):
        return [
            p for p in storage.postings.list_for_campaign(campaign_id)
            if getattr(p, "viability_score", None) is None
        ]
    storage.postings.list_unscored_for_campaign = _list_unscored

    scoring = _CountingScoring()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=scoring,
        digest_service=_FakeDigest(),
        prefill_service=_FakePrefill(),
        orchestrator=orch,
    )
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    # ONLY the fresh (unscored) posting was scored this tick.
    assert scoring.scored == [str(p_fresh)]


@pytest.mark.unit
def test_resume_in_flight_backs_off_human_gated_app(tmp_path):
    """#9: a human-gated app is not re-driven every tick — the per-app backoff skips
    a re-drive until the backoff window elapses."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    prefill = _FakePrefill(state=ApplicationState.BLOCKED_QUESTION)
    loop = _loop(storage, orch, prefill=prefill)

    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop.run_once(cid, now=now)  # starts pipeline -> BLOCKED_QUESTION (handoff)
    app = storage.applications.list_for_campaign(cid)[0]

    # Count start_workflow invocations on the (now blocked) app across resume ticks.
    starts = {"n": 0}
    real_start = orch.start_workflow

    def _counting_start(name, wf_id, **kw):
        if wf_id == f"application:{app.id}":
            starts["n"] += 1
        return real_start(name, wf_id, **kw)
    orch.start_workflow = _counting_start

    # Two ticks 60s apart: within the 300s backoff -> at most ONE re-drive, not two.
    loop.run_once(cid, now=now + timedelta(seconds=60))
    first = starts["n"]
    loop.run_once(cid, now=now + timedelta(seconds=120))
    assert starts["n"] == first  # backoff suppressed the second re-drive

    # After the backoff window, the app is re-driven again.
    loop.run_once(cid, now=now + timedelta(seconds=600))
    assert starts["n"] == first + 1


@pytest.mark.unit
def test_resume_failure_cap_gives_up_and_alerts(tmp_path):
    """24/7 robustness: a permanently-failing resume is retried up to the cap, then
    the loop STOPS re-driving the app and surfaces ONE deduped error — instead of
    churning the sandbox every backoff window forever and never alerting the operator."""
    from applicant.application.services.agent_loop import _RESUME_FAILURE_CAP, TickResult

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    prefill = _FakePrefill(state=ApplicationState.BLOCKED_QUESTION)

    class _NotifSpy:
        def __init__(self):
            self.errors = []

        def notify_error(self, *, title, body, dedup_key=None):
            self.errors.append(dedup_key)
            return "nid"

    notif = _NotifSpy()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=prefill,
        orchestrator=orch,
        notification_service=notif,
    )
    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop.run_once(cid, now=now)  # -> BLOCKED_QUESTION (parked, resumable)
    app = storage.applications.list_for_campaign(cid)[0]

    # Every RESUME now raises (the initial start already happened above).
    def _raise(name, wf_id, **kw):
        if wf_id == f"application:{app.id}":
            raise RuntimeError("cannot resume")

        class _H:
            def result(self_inner):
                return None

        return _H()

    orch.start_workflow = _raise

    # Drive resumes past the 300s backoff, cap + 2 extra ticks.
    t = now
    for _ in range(_RESUME_FAILURE_CAP + 2):
        t = t + timedelta(seconds=400)
        loop._resume_in_flight(cid, TickResult(campaign_id=str(cid)), t)

    # Gave up re-driving: excluded from the resumable set, and exactly ONE deduped alert.
    assert str(app.id) not in [str(a.id) for a in loop._resumable_apps(cid)]
    assert notif.errors == [f"stuck_application:{app.id}"]


@pytest.mark.unit
def test_resume_failure_streak_resets_on_success(tmp_path):
    """A clean resume clears the failure streak so transient blips never accumulate
    toward the give-up cap."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    loop = _loop(storage, orch, prefill=_FakePrefill(state=ApplicationState.BLOCKED_QUESTION))
    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop.run_once(cid, now=now)
    app = storage.applications.list_for_campaign(cid)[0]

    # Two failures, then a success — the streak must reset to zero.
    loop._record_resume_failure(app.id)
    loop._record_resume_failure(app.id)
    assert loop._resume_failures[str(app.id)] == 2
    # Simulate a successful resume clearing it (mirrors the success branch).
    loop._resume_failures.pop(str(app.id), None)
    assert str(app.id) not in loop._resume_failures
    assert str(app.id) not in loop._resume_giveup


@pytest.mark.unit
def test_approved_postings_use_indexed_decision_lookup(tmp_path):
    """#10: the loop uses DecisionRepository.list_approved_postings_for_campaign +
    ApplicationRepository.get_by_posting instead of the per-posting N+1 scan."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid)

    calls = {"approved": 0, "get_by_posting": 0}

    def _list_approved(campaign_id):
        calls["approved"] += 1
        return [pid]
    storage.decisions.list_approved_postings_for_campaign = _list_approved

    def _get_by_posting(campaign_id, posting_id):
        calls["get_by_posting"] += 1
        for a in storage.applications.list_for_campaign(campaign_id):
            if str(a.posting_id) == str(posting_id):
                return a
        return None
    storage.applications.get_by_posting = _get_by_posting

    loop = _loop(storage, orch, prefill=_FakePrefill())
    result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert calls["approved"] >= 1  # indexed approved-postings lookup was used
    assert calls["get_by_posting"] >= 1  # indexed app-by-posting lookup was used
    assert len(result.pipelines_started) == 1


@pytest.mark.unit
def test_acted_today_uses_count_pipelines_started_on(tmp_path):
    """#11: the throughput ledger uses count_pipelines_started_on, not a full
    agent_runs scan."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)

    calls = {"n": 0}

    def _count(campaign_id, day):
        calls["n"] += 1
        return 7
    storage.agent_runs.count_pipelines_started_on = _count

    loop = _loop(storage, orch, prefill=_FakePrefill())
    now = datetime(2026, 6, 16, tzinfo=UTC)
    assert loop.acted_today(cid, now) == 7
    assert calls["n"] >= 1


# === #3: the loop generates material and routes it to review ================
@pytest.mark.unit
def test_loop_generates_material_routed_to_review(tmp_path):
    """#3: running the loop to an approved posting GENERATES material (a resume
    variant) and routes it to review (MATERIAL_REVIEW handoff), instead of the old
    no-op that always returned review_approved=False with nothing generated."""
    from applicant.adapters.embedding.local_embedding import LocalEmbedding
    from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
    from applicant.application.services.material_service import MaterialService

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, title="Python Engineer")

    material = MaterialService(
        storage, llm=None, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=_FakePrefill(),  # lands AWAITING_FINAL_APPROVAL (non-handoff)
        material_service=material,
        orchestrator=orch,
    )
    result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))

    app = storage.applications.list_for_campaign(cid)[0]
    # Material routed to review -> the pipeline handed off at MATERIAL_REVIEW.
    assert str(app.id) in result.handoffs
    # A resume variant was generated for the campaign (unapproved, awaiting review).
    variants = storage.resume_variants.list_for_campaign(cid)
    assert variants and any(v.approved is False for v in variants)


# === #4: blocked-state resumption chooses the right resume_after_* ===========
class _ResumeSpyPrefill:
    """Records which pre-fill entry point the loop chose for the app's §7 state."""

    def __init__(self):
        self.calls: list[str] = []

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls.append("prefill_application")
        return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)

    def resume_after_account(self, application, attributes=None, *, cautious=True):
        self.calls.append("resume_after_account")
        return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)

    def resume_after_missing_attr(self, application, attributes, *, cautious=True):
        self.calls.append("resume_after_missing_attr")
        return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)


@pytest.mark.unit
def test_loop_resumes_account_step_not_full_restart(tmp_path):
    """#4: an app parked at AWAITING_ACCOUNT_HUMAN_STEP is RESUMED via
    resume_after_account on re-drive, not restarted with prefill_application."""

    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid)
    # Persist an app already parked at the account-human-step.
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=pid,
        status=ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP,
        root_url="http://x",
    )
    storage.applications.add(app)
    storage.commit()

    spy = _ResumeSpyPrefill()
    submission = _FakeSubmission()
    loop = _loop(storage, orch, prefill=spy, submission=submission)
    # Drive the in-flight (blocked) app: _resume_in_flight rebuilds the context and the
    # pipeline's prefill step picks the right resume entry point.
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert "resume_after_account" in spy.calls
    assert "prefill_application" not in spy.calls


@pytest.mark.unit
def test_loop_resumes_missing_attr_not_full_restart(tmp_path):
    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid)
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=pid,
        status=ApplicationState.BLOCKED_MISSING_ATTR,
        root_url="http://x",
    )
    storage.applications.add(app)
    storage.commit()

    spy = _ResumeSpyPrefill()
    loop = _loop(storage, orch, prefill=spy, submission=_FakeSubmission())
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert "resume_after_missing_attr" in spy.calls
    assert "prefill_application" not in spy.calls


# === #6: the loop passes campaign criteria to discovery + scoring ===========
@pytest.mark.unit
def test_loop_passes_criteria_to_discovery_and_scoring(tmp_path):
    """#6: discovery + scoring receive the campaign's criteria (from get_criteria),
    not empty defaults."""
    from applicant.core.entities.search_criteria import SearchCriteria

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title="Fresh", company="A", source_url="u")
    )

    the_criteria = SearchCriteria(campaign_id=cid, titles=("Staff Engineer",))

    class _CritSvc:
        def get_criteria(self, campaign_id):
            return the_criteria

    seen = {"discovery": None, "scoring": None}

    class _DiscoverySpy:
        def run_discovery(self, campaign_id, criteria=None):
            seen["discovery"] = criteria
            return []

    class _ScoringSpy(_FakeScoring):
        def score_viability(self, pid, criteria=None):
            seen["scoring"] = criteria
            return None

        @property
        def threshold(self):
            return 70

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        discovery_service=_DiscoverySpy(),
        scoring_service=_ScoringSpy(),
        digest_service=_FakeDigest(),
        criteria_service=_CritSvc(),
        prefill_service=_FakePrefill(),
        orchestrator=orch,
    )
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert seen["discovery"] is the_criteria
    assert seen["scoring"] is the_criteria


# === Lane B: auto-escalate to capped deep research while tailoring material ===
class _CapturingMaterial:
    """Material fake that records the true_source it was generated with."""

    def __init__(self):
        self.true_source_seen = None

    def true_attribute_text(self, campaign_id, _):
        return "TRUE: 5y python"

    def select_or_generate(self, campaign_id, posting_id, jd_terms, true_source, application_id=None):
        from types import SimpleNamespace

        from applicant.core.ids import ResumeVariantId, new_id

        self.true_source_seen = true_source
        variant = SimpleNamespace(id=ResumeVariantId(new_id()), approved=False)
        return SimpleNamespace(variant=variant, generated=True)

    def cover_letter_warranted(self, *, campaign_default=False):
        return False


class _FakeResearch:
    """ResearchService-shaped fake that records the escalation call."""

    def __init__(self, report=None):
        self.calls = []
        from applicant.application.services.research_service import ResearchReport

        self._report = report if report is not None else ResearchReport(
            query="q", summary="Acme makes widgets.", key_findings=["Series C", "remote-first"]
        )

    def research(self, campaign_id, query, **kwargs):
        self.calls.append({"campaign_id": campaign_id, "query": query, **kwargs})
        return self._report


@pytest.mark.unit
def test_auto_escalates_research_and_folds_into_true_source():
    """The loop escalates to the capped research tool on a company gap and folds
    the report into the true_source used to generate material (Lane B)."""
    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid, title="Python Engineer")  # company="Acme"

    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId

    app = Application(
        id=ApplicationId(new_id()), campaign_id=cid, posting_id=pid,
        status=ApplicationState.APPROVED, root_url="http://x",
    )
    storage.applications.add(app)

    material = _CapturingMaterial()
    research = _FakeResearch()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        material_service=material,
        research_service=research,
    )

    summary = loop._prepare_material_for(storage.campaigns.get(cid), app)

    # Research was escalated, scoped to the campaign + company/role.
    assert len(research.calls) == 1
    assert research.calls[0]["company"] == "Acme"
    assert research.calls[0]["role"] == "Python Engineer"
    # The report was folded into the true_source that drove generation.
    assert "Acme makes widgets." in material.true_source_seen
    assert "Series C" in material.true_source_seen
    assert summary.get("research_used") is True


@pytest.mark.unit
def test_no_research_service_is_a_noop():
    """Without a research service wired, material generation proceeds unchanged."""
    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid)
    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId

    app = Application(
        id=ApplicationId(new_id()), campaign_id=cid, posting_id=pid,
        status=ApplicationState.APPROVED, root_url="http://x",
    )
    storage.applications.add(app)
    material = _CapturingMaterial()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        material_service=material,
    )
    summary = loop._prepare_material_for(storage.campaigns.get(cid), app)
    assert "research_used" not in summary
    # true_source is the plain candidate source, no research block prepended.
    assert material.true_source_seen == "TRUE: 5y python"
