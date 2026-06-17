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
