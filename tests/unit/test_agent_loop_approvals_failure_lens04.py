"""Lens 04 findings #31/#32 — the APPROVED-application pipeline-start path must
isolate a single poison posting and give up on a persistently-failing one.

FAIL-BEFORE (both): ``_process_approvals`` called ``_start_pipeline`` with no
try/except of its own. A raise from ``_start_pipeline`` (the pipeline start itself,
after the sandbox slot was already released internally) propagated straight out of
``_process_approvals``'s for-loop, so (#31) any approved posting still waiting its
turn in the SAME tick was never even attempted, and (#32) since the application row
is left APPROVED with nothing recorded, the very next tick retried it from scratch
forever with no bound and no operator visibility.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import (
    _APPROVAL_START_FAILURE_CAP,
    AgentLoop,
    ApprovalStartLedger,
)
from applicant.application.services.agent_run_service import AgentRunService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId, DecisionId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# --- fakes (mirrors tests/unit/test_agent_loop.py's own fakes) ------------
class _FakeScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="strong fit")

    score_viability = lambda self, pid, criteria=None: None  # noqa: E731

    def is_viable(self, scoring):
        return True


class _FakeDigest:
    def deliver(self, campaign_id, criteria=None):
        return {"payload": {"rows": [{"posting_id": "p"}]}}


class _PrefillResult:
    def __init__(self, state):
        self.state = state


class _FakePrefill:
    def __init__(self, state=ApplicationState.AWAITING_FINAL_APPROVAL):
        self._state = state

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        return _PrefillResult(self._state)


class _NotifSpy:
    def __init__(self):
        self.errors: list[str | None] = []

    def notify_error(self, *, title, body, dedup_key=None):
        self.errors.append(dedup_key)
        return "nid"


def _make_campaign(storage, *, run_mode=RunMode.CONTINUOUS, target=15):
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=run_mode, throughput_target=target, schedule={})
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


def _loop(storage, orch, *, prefill=None, notifications=None):
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=prefill,
        orchestrator=orch,
        notification_service=notifications,
    )


# --- #31: isolation ---------------------------------------------------------
@pytest.mark.unit
def test_poison_approved_posting_does_not_abort_sibling_approvals(tmp_path):
    """A raising pipeline start for ONE approved posting must not stop the loop from
    attempting the OTHER approved posting in the same tick, and must not raise out of
    ``run_once`` at all — it is isolated, logged, and counted toward the give-up cap."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, title="Poison")
    _approve_posting(storage, cid, title="Healthy")

    loop = _loop(storage, orch, prefill=_FakePrefill())

    real_start = orch.start_workflow
    calls = {"n": 0}

    def _first_call_raises(name, wf_id, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom: poison posting")
        return real_start(name, wf_id, **kw)

    orch.start_workflow = _first_call_raises

    now = datetime(2026, 6, 16, tzinfo=UTC)
    result = loop.run_once(cid, now=now)  # must NOT raise: isolated, not fatal

    apps = storage.applications.list_for_campaign(cid)
    assert len(apps) == 2  # both applications were created regardless of the failure

    started = [a for a in apps if a.status is not ApplicationState.APPROVED]
    still_approved = [a for a in apps if a.status is ApplicationState.APPROVED]
    # The healthy sibling's pipeline actually started even though it was processed
    # AFTER the poison one — it was not stranded by the earlier failure.
    assert len(started) == 1
    assert len(result.pipelines_started) == 1
    # The poison one is isolated: left APPROVED (for a later retry) rather than
    # crashing the batch, and its failure was recorded (not silently dropped).
    assert len(still_approved) == 1
    assert loop._approval_start_failures.get(str(still_approved[0].id)) == 1
    assert str(still_approved[0].id) not in loop._approval_start_giveup


# --- #32: bounded give-up ----------------------------------------------------
@pytest.mark.unit
def test_persistent_approval_start_failure_gives_up_and_alerts(tmp_path):
    """An approved application whose pipeline start ALWAYS raises is retried up to
    the cap, then the loop stops retrying it and surfaces exactly ONE deduped error —
    instead of retrying a permanently-poison posting every tick forever."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    notif = _NotifSpy()

    calls = {"n": 0}

    def _always_raise(name, wf_id, **kw):
        calls["n"] += 1
        raise RuntimeError("cannot start")

    orch.start_workflow = _always_raise

    loop = _loop(storage, orch, prefill=_FakePrefill(), notifications=notif)

    now = datetime(2026, 6, 16, tzinfo=UTC)
    for i in range(_APPROVAL_START_FAILURE_CAP + 2):
        loop.run_once(cid, now=now + timedelta(minutes=i))

    app = storage.applications.list_for_campaign(cid)[0]
    assert str(app.id) in loop._approval_start_giveup
    # Exactly ONE deduped alert, even though the cap was exceeded by 2 extra ticks.
    assert notif.errors == [f"stuck_approval_start:{app.id}"]
    # No longer retried past the cap: the start attempt count stops growing.
    assert calls["n"] == _APPROVAL_START_FAILURE_CAP
    # Given up on, not started — still APPROVED, waiting for an operator to look.
    assert app.status is ApplicationState.APPROVED


@pytest.mark.unit
def test_approval_start_failure_streak_resets_on_success(tmp_path):
    """A transient start failure followed by a clean start clears the streak, so
    intermittent blips never accumulate toward the give-up cap."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    loop = _loop(storage, orch, prefill=_FakePrefill())

    real_start = orch.start_workflow
    state = {"raise": True}

    def _flaky(name, wf_id, **kw):
        if state["raise"]:
            raise RuntimeError("transient")
        return real_start(name, wf_id, **kw)

    orch.start_workflow = _flaky

    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop.run_once(cid, now=now)
    loop.run_once(cid, now=now + timedelta(minutes=1))
    app = storage.applications.list_for_campaign(cid)[0]
    assert loop._approval_start_failures.get(str(app.id)) == 2

    # The posting recovers — the next attempt succeeds and clears the streak.
    state["raise"] = False
    loop.run_once(cid, now=now + timedelta(minutes=2))
    assert str(app.id) not in loop._approval_start_failures
    assert str(app.id) not in loop._approval_start_giveup


# --- process-lived ledger (mirrors ResumeLedger) -----------------------------
@pytest.mark.unit
def test_approval_start_ledger_persists_across_loop_instances():
    """The scheduler rebuilds a fresh AgentLoop every tick, so the approval-start
    failure streak + give-up set must live in a shared ledger or they reset every
    tick and the give-up cap would never trip. A shared ``ApprovalStartLedger``
    carries ``failures``/``giveup`` across instances; a loop given its OWN separate
    ledger keeps isolated state (regression guard)."""
    storage = InMemoryStorage()
    ledger = ApprovalStartLedger()

    def fresh():  # a new AgentLoop, as the scheduler builds per tick
        return AgentLoop(
            storage=storage,
            agent_run_service=AgentRunService(storage),
            approval_start_ledger=ledger,
        )

    aid = "app-shared-approval-start"
    for _ in range(_APPROVAL_START_FAILURE_CAP):
        fresh()._record_approval_start_failure(aid)
    assert aid in ledger.giveup

    # A loop given an explicit, DIFFERENT ledger keeps its own empty state (not
    # contaminated by the shared one above).
    isolated = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        approval_start_ledger=ApprovalStartLedger(),
    )
    assert aid not in isolated._approval_start_giveup


@pytest.mark.unit
def test_default_ledger_is_shared_across_instances_without_explicit_injection():
    """Regression guard for the #180 footgun this file's ``ResumeLedger`` et al.
    document: an ``AgentLoop`` built with NO explicit ``approval_start_ledger`` must
    still share failure bookkeeping across separate instances (the module-level
    process-lived default), or the scheduler's per-tick rebuild would silently reset
    the give-up cap every ~60s and #32 would never actually take effect in
    production."""
    storage = InMemoryStorage()
    # A key unique to this test run so it cannot collide with any other test's use
    # of the shared process-lived default ledger in the same pytest session.
    aid = f"app-default-ledger-{new_id()}"

    def fresh():
        return AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))

    for _ in range(_APPROVAL_START_FAILURE_CAP):
        fresh()._record_approval_start_failure(aid)
    assert aid in fresh()._approval_start_giveup
