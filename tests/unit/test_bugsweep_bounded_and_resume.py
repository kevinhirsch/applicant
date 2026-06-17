"""Bounded-maps (CONC-3) + resilient-resume bug-sweep tests (bugfix-sweep-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.capacity_service import CapacityService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.notification import Notification


# --- CONC-3: agent loop _digest_sent / _acted are pruned across days --------
def test_conc3_agent_loop_prunes_daily_maps():
    """CONC-3: ticking across simulated days does not grow the loop's per-day dedup
    maps unbounded — old days are pruned, leaving only today's entries."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        orchestrator=CheckpointShimOrchestrator_tmp(),
    )

    base = datetime(2026, 1, 1, tzinfo=UTC)
    for d in range(10):
        loop.tick(cid, base + timedelta(days=d))

    # Only the most recent day's keys remain (no unbounded accumulation).
    assert all(k[1] == (base + timedelta(days=9)).date() for k in loop._digest_sent)
    assert len(loop._digest_sent) <= 1


# --- CONC-3: notifier inbox/captured are bounded ----------------------------
def test_conc3_notifier_inbox_and_captured_bounded():
    """CONC-3: the in-app inbox + capture lists rotate so they stay bounded."""
    notifier = AppriseNotifier(in_app=True)
    notifier._max_inbox = 5
    notifier._max_captured = 5
    for i in range(50):
        notifier.notify(Notification(title=f"t{i}", body="b", dedup_key=f"k{i}"))
    assert len(notifier.inbox()) <= 5
    assert len(notifier.captured()) <= 5


# --- resume failure must release the slot + not abort the tick --------------
class CheckpointShimOrchestrator_tmp(CheckpointShimOrchestrator):
    def __init__(self):
        import tempfile

        super().__init__(tempfile.mkdtemp())


class _RaisingOnResumeOrch(CheckpointShimOrchestrator_tmp):
    """Orchestrator whose workflow start raises (simulates a resume pipeline failure)."""

    def start_workflow(self, *a, **k):
        raise RuntimeError("boom during resume")


def test_resume_failure_releases_slot_and_continues_tick():
    """A resume that raises releases the sandbox slot and does NOT abort the rest of
    the tick (one failing in-flight app must not deadlock capacity or stall others)."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))

    orch = _RaisingOnResumeOrch()
    capacity = CapacityService(orch, sandbox_concurrency=1)

    # An in-flight app parked at a resumable waiting state, holding the only slot.
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.BLOCKED_QUESTION,
    )
    storage.applications.add(app)
    assert capacity.admit_sandbox(str(app.id)) is True  # holds the slot

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        capacity_service=capacity,
        orchestrator=orch,
    )

    # The tick must not raise even though the resume start_workflow raises.
    result = loop.tick(cid, datetime(2026, 6, 16, tzinfo=UTC))
    assert result is not None

    # The slot was released so a new application can be admitted (no leak/deadlock).
    assert capacity.admit_sandbox("other-app") is True
