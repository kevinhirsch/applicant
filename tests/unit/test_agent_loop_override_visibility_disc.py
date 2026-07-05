"""Discovered-issues DISC-9 / DISC-11 regressions (docs/design/audits/discovered-issues.md).

DISC-9 (med) — pre-submit override lost when the pipeline can't start. In
``_process_approvals`` the presubmit-safety override used to be cleared the
MOMENT it was seen, before ``_start_pipeline`` confirmed the pipeline actually
started. When ``_start_pipeline`` returns ``False`` for a NORMAL, non-exception
reason (sandbox capacity full), the override bookkeeping was already gone, so
the very next tick re-ran the safety checks from scratch and re-blocked the
application — it looked brand-new to the operator even though they had
already overridden it once. Fixed: the override/block bookkeeping is now only
cleared AFTER ``_start_pipeline`` returns ``True`` (a confirmed start).

DISC-11 (low) — approval-start give-ups were invisible to the operator
surface. The ``ApprovalStartLedger`` give-up set (added for lens 04 #32) was
never read by ``AgentLoop.list_given_up``/``retry_given_up`` (the listing +
retry surface built for ``ResumeLedger`` give-ups, #62), so a permanently
poison APPROVED application that gave up on START was invisible and had no
retry path. Fixed: both give-up ledgers are merged into ``list_given_up``
(tagged by ``give_up_reason``) and both are checked/cleared by
``retry_given_up``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import (
    _APPROVAL_START_FAILURE_CAP,
    _RESUME_FAILURE_CAP,
    AgentLoop,
    ApprovalStartLedger,
    PresubmitBlockLedger,
)
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.capacity_service import CapacityService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, DecisionId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# --- fakes (mirrors test_blocked_applications_panel.py / test_agent_loop_approvals_failure_lens04.py) --
class _FakeScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="strong fit")

    def is_viable(self, scoring):
        return True


class _FakeDigest:
    def deliver(self, campaign_id, criteria=None):
        return {"payload": {"rows": []}}


class _PrefillResult:
    def __init__(self, state):
        self.state = state


class _FakePrefill:
    def __init__(self, state=ApplicationState.AWAITING_FINAL_APPROVAL):
        self._state = state
        self.calls = 0

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls += 1
        return _PrefillResult(self._state)


#: Non-None so the G07 checks actually run (mirrors test_blocked_applications_panel.py).
_PRESUBMIT_PARAMS = {
    "max_age_days": 90,
    "duplicate_cooldown_days": 30,
    "max_apps_per_company_per_day": 3,
    "eligibility_enabled": True,
}


def _make_campaign(storage, *, run_mode=RunMode.CONTINUOUS, target=15) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=run_mode, throughput_target=target, schedule={})
    )
    return cid


def _approve_posting(storage, cid, *, title="Engineer", company="Acme") -> JobPostingId:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title=title, company=company, source_url="http://x")
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
    presubmit_block_ledger=None,
    approval_start_ledger=None,
    capacity=None,
    notifications=None,
):
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=prefill,
        orchestrator=orch,
        presubmit_safety_params=_PRESUBMIT_PARAMS,
        presubmit_block_ledger=presubmit_block_ledger,
        approval_start_ledger=approval_start_ledger,
        capacity_service=capacity,
        notification_service=notifications,
    )


# --- DISC-9: override must survive a capacity-full (non-exception) failed start ---
@pytest.mark.unit
def test_override_survives_capacity_full_start_and_is_honored_on_retry(tmp_path):
    """A presubmit-block override must not be lost when ``_start_pipeline`` defers
    for a NORMAL reason (sandbox capacity full — not an exception): it must still
    be present (and honored, skipping the checks) on the very next tick, and only
    get cleared once the pipeline actually starts."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    # "Confidential" trips check_scam_or_ghost_job's company-reputation signal.
    _approve_posting(storage, cid, company="Confidential")
    ledger = PresubmitBlockLedger()
    prefill = _FakePrefill()
    capacity = CapacityService(orch, sandbox_concurrency=1)

    # Tick 1: the presubmit check blocks (no override yet).
    loop1 = _loop(
        storage, orch, prefill=prefill, presubmit_block_ledger=ledger, capacity=capacity
    )
    loop1.run_once(cid, now=datetime(2026, 6, 16, 8, 0, tzinfo=UTC))
    app = storage.applications.list_for_campaign(cid)[0]
    assert app.status is ApplicationState.APPROVED
    assert loop1.list_blocked(cid), "the block must be recorded before an override"

    # The operator overrides it.
    assert loop1.override_blocked(str(app.id)) is True
    assert str(app.id) in ledger.overridden

    # Occupy the campaign's ONLY sandbox slot with an unrelated app so the next
    # ``admit_sandbox`` call for OUR app returns False — a NORMAL "capacity full"
    # deferral, never an exception.
    assert capacity.admit_sandbox("occupier") is True

    # Tick 2 (a FRESH AgentLoop, exactly as the scheduler rebuilds one every tick):
    # the override should be honored (checks skipped, no re-block) even though the
    # start itself is deferred by capacity.
    loop2 = _loop(
        storage, orch, prefill=prefill, presubmit_block_ledger=ledger, capacity=capacity
    )
    result2 = loop2.run_once(cid, now=datetime(2026, 6, 16, 8, 1, tzinfo=UTC))

    app_after_tick2 = storage.applications.get(app.id)
    assert app_after_tick2.status is ApplicationState.APPROVED, "still waiting on capacity"
    assert str(app.id) not in result2.pipelines_started
    # The checks were SKIPPED (the override was honored), not re-run: pre-fill was
    # never even reached because admission failed before the pipeline started.
    assert prefill.calls == 0
    # THE FIX: the override must survive an unconfirmed (capacity-deferred) start —
    # before the fix this would already be gone, and the block/override would be
    # created fresh (looking brand-new) on the very next tick's re-run of the checks.
    assert str(app.id) in ledger.overridden, (
        "an override must not be cleared until the pipeline actually starts"
    )

    # Free the slot; the NEXT tick can actually admit + start the pipeline.
    capacity.release_sandbox("occupier")
    loop3 = _loop(
        storage, orch, prefill=prefill, presubmit_block_ledger=ledger, capacity=capacity
    )
    result3 = loop3.run_once(cid, now=datetime(2026, 6, 16, 8, 2, tzinfo=UTC))

    app_after_tick3 = storage.applications.get(app.id)
    assert app_after_tick3.status is not ApplicationState.APPROVED, (
        "the override, once honored by a CONFIRMED start, must actually admit it"
    )
    assert str(app.id) in result3.pipelines_started
    assert prefill.calls == 1
    # NOW (only now) the override + block bookkeeping is cleared.
    assert str(app.id) not in ledger.overridden
    assert loop3.list_blocked(cid) == []


@pytest.mark.unit
def test_override_cleared_immediately_when_start_confirms_on_the_same_tick(tmp_path):
    """Regression guard: when nothing defers the start (capacity is free), the
    override must still clear on a confirmed start exactly as before — the fix
    only delays the clear past an UNCONFIRMED start, it must not leave a
    permanently-lingering override once the app has actually started."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, company="Confidential")
    ledger = PresubmitBlockLedger()
    prefill = _FakePrefill()

    loop1 = _loop(storage, orch, prefill=prefill, presubmit_block_ledger=ledger)
    loop1.run_once(cid, now=datetime(2026, 6, 16, 8, 0, tzinfo=UTC))
    app = storage.applications.list_for_campaign(cid)[0]
    assert loop1.override_blocked(str(app.id)) is True

    loop2 = _loop(storage, orch, prefill=prefill, presubmit_block_ledger=ledger)
    result2 = loop2.run_once(cid, now=datetime(2026, 6, 16, 8, 1, tzinfo=UTC))

    app_after = storage.applications.get(app.id)
    assert app_after.status is not ApplicationState.APPROVED
    assert str(app.id) in result2.pipelines_started
    assert str(app.id) not in ledger.overridden
    assert loop2.list_blocked(cid) == []


@pytest.mark.unit
def test_override_survives_an_exception_failed_start_too(tmp_path):
    """An exception (poison posting) is likewise not a confirmed start — the
    override must survive it as well, not just the capacity-deferred case."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, company="Confidential")
    ledger = PresubmitBlockLedger()
    prefill = _FakePrefill()

    loop1 = _loop(storage, orch, prefill=prefill, presubmit_block_ledger=ledger)
    loop1.run_once(cid, now=datetime(2026, 6, 16, 8, 0, tzinfo=UTC))
    app = storage.applications.list_for_campaign(cid)[0]
    assert loop1.override_blocked(str(app.id)) is True

    real_start = orch.start_workflow

    def _raises(name, wf_id, **kw):
        raise RuntimeError("boom: poison posting")

    orch.start_workflow = _raises

    loop2 = _loop(storage, orch, prefill=prefill, presubmit_block_ledger=ledger)
    loop2.run_once(cid, now=datetime(2026, 6, 16, 8, 1, tzinfo=UTC))
    assert str(app.id) in ledger.overridden, (
        "an exception is not a confirmed start either -- the override must survive it"
    )

    # Restore a working start and let a later tick actually succeed + clear it.
    orch.start_workflow = real_start
    loop3 = _loop(storage, orch, prefill=prefill, presubmit_block_ledger=ledger)
    result3 = loop3.run_once(cid, now=datetime(2026, 6, 16, 8, 2, tzinfo=UTC))
    assert str(app.id) in result3.pipelines_started
    assert str(app.id) not in ledger.overridden


# --- DISC-11: approval-start give-ups must be visible + retryable ------------
@pytest.mark.unit
def test_list_given_up_includes_approval_start_giveups():
    """An application given up on PIPELINE START (never resumed, never even
    started) must show up in ``list_given_up`` — before the fix only resume
    give-ups (``ResumeLedger``) were surfaced, so this class of stuck
    application was completely invisible to the operator."""
    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid, title="Backend Engineer", company="Acme")
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))

    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=pid,
            status=ApplicationState.APPROVED,
            role_name="Backend Engineer",
        )
    )

    for _ in range(_APPROVAL_START_FAILURE_CAP):
        loop._record_approval_start_failure(aid)
    assert str(aid) in loop._approval_start_giveup

    rows = loop.list_given_up(cid)
    assert len(rows) == 1
    row = rows[0]
    assert row["application_id"] == str(aid)
    assert row["campaign_id"] == str(cid)
    assert row["failures"] == _APPROVAL_START_FAILURE_CAP
    assert row["give_up_reason"] == "approval_start"
    assert row["status"] == ApplicationState.APPROVED.value


@pytest.mark.unit
def test_list_given_up_merges_resume_and_approval_start_giveups():
    """Both give-up ledgers surface side by side, each correctly tagged."""
    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid)
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))

    resume_aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=resume_aid,
            campaign_id=cid,
            posting_id=pid,
            status=ApplicationState.BLOCKED_QUESTION,
            role_name="R",
        )
    )
    approval_aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=approval_aid,
            campaign_id=cid,
            posting_id=pid,
            status=ApplicationState.APPROVED,
            role_name="R",
        )
    )

    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(resume_aid)
    for _ in range(_APPROVAL_START_FAILURE_CAP):
        loop._record_approval_start_failure(approval_aid)

    rows = {r["application_id"]: r["give_up_reason"] for r in loop.list_given_up(cid)}
    assert rows[str(resume_aid)] == "resume"
    assert rows[str(approval_aid)] == "approval_start"


@pytest.mark.unit
def test_retry_given_up_clears_an_approval_start_giveup_and_unblocks_the_next_tick(tmp_path):
    """``retry_given_up`` must clear an approval-start give-up too (not just a
    resume give-up), so the very next tick actually re-attempts the pipeline
    start instead of silently skipping it forever."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    prefill = _FakePrefill()

    real_start = orch.start_workflow

    def _always_raise(name, wf_id, **kw):
        raise RuntimeError("cannot start")

    orch.start_workflow = _always_raise
    ledger = ApprovalStartLedger()
    loop = _loop(storage, orch, prefill=prefill, approval_start_ledger=ledger)

    now = datetime(2026, 6, 16, tzinfo=UTC)
    for i in range(_APPROVAL_START_FAILURE_CAP + 1):
        loop.run_once(cid, now=now + timedelta(minutes=i))

    app = storage.applications.list_for_campaign(cid)[0]
    assert str(app.id) in ledger.giveup
    assert loop.list_given_up(cid), "must be visible before the retry"

    assert loop.retry_given_up(str(app.id)) is True
    assert str(app.id) not in ledger.giveup
    assert str(app.id) not in ledger.failures
    assert loop.list_given_up(cid) == []

    # The posting "recovers" (the real start works again) and a LATER loop
    # instance sharing the SAME ledger (mirrors the scheduler's per-tick rebuild)
    # actually re-attempts + completes the start on the very next tick.
    orch.start_workflow = real_start
    loop2 = _loop(storage, orch, prefill=prefill, approval_start_ledger=ledger)
    result = loop2.run_once(
        cid, now=now + timedelta(minutes=_APPROVAL_START_FAILURE_CAP + 5)
    )
    assert str(app.id) in result.pipelines_started
    app_after = storage.applications.get(app.id)
    assert app_after.status is not ApplicationState.APPROVED


@pytest.mark.unit
def test_retry_given_up_is_a_noop_for_an_application_never_given_up_either_way():
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    assert loop.retry_given_up("never-given-up") is False
