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


def _loop(storage, orch, *, prefill=None, submission=None, capacity=None, digest=None):
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=digest or _FakeDigest(),
        prefill_service=prefill,
        submission_service=submission,
        capacity_service=capacity,
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
    now = datetime(2026, 6, 16, tzinfo=UTC)
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
