"""Bugsweep-2 Fix 1: the 24/7 loop/scheduler honor the automated-work gate.

[FR-ONBOARD-2 / FR-OOBE-3] The background scheduler + agent loop must NOT start any
new automated work (discovery / digest delivery / pipeline starts) while the
automated-work gate is closed — i.e. before onboarding is complete AND notification
channels are configured AND the LLM gate is open. The gate was previously enforced
only at the HTTP layer (``require_automated_work``); the 24/7 loop ran regardless.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId, DecisionId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


class _Gate:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls = 0

    def is_automated_work_allowed(self) -> bool:
        self.calls += 1
        return self.allowed


class _FakeScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="fit")

    def score_viability(self, pid, criteria=None):
        return None

    def is_viable(self, scoring):
        return True


class _CountingDiscovery:
    def __init__(self):
        self.calls = 0

    def run_discovery(self, campaign_id):
        self.calls += 1
        return []


class _CountingDigest:
    def __init__(self):
        self.delivered = 0

    def deliver(self, campaign_id, criteria=None):
        self.delivered += 1
        return {"payload": {"rows": [{"posting_id": "p"}]}}


class _FakePrefill:
    def __init__(self):
        self.calls = 0

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls += 1

        class _R:
            state = ApplicationState.AWAITING_FINAL_APPROVAL

        return _R()


def _campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=15)
    )
    return cid


def _approve_posting(storage, cid):
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title="Engineer", company="Acme", source_url="http://x")
    )
    storage.decisions.add(
        Decision(id=DecisionId(new_id()), application_id=str(pid), type=DecisionType.APPROVE)
    )
    return pid


def _loop(storage, orch, gate, *, discovery, digest, prefill):
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        discovery_service=discovery,
        scoring_service=_FakeScoring(),
        digest_service=digest,
        prefill_service=prefill,
        orchestrator=orch,
        setup_service=gate,
    )


@pytest.mark.unit
def test_loop_tick_starts_no_new_work_when_gate_closed(tmp_path):
    """FR-ONBOARD-2/FR-OOBE-3: gate closed -> no discovery, no digest, no pipeline."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _campaign(storage)
    _approve_posting(storage, cid)
    discovery, digest, prefill = _CountingDiscovery(), _CountingDigest(), _FakePrefill()
    loop = _loop(storage, orch, _Gate(False), discovery=discovery, digest=digest, prefill=prefill)

    result = loop.tick(cid, now=datetime(2026, 6, 16, tzinfo=UTC))

    assert result.reason == "automated_work_gated"
    assert discovery.calls == 0
    assert digest.delivered == 0
    assert prefill.calls == 0
    assert result.pipelines_started == []
    # No Application row was created (no new automated work started).
    assert storage.applications.list_for_campaign(cid) == []


@pytest.mark.unit
def test_loop_tick_proceeds_when_gate_open(tmp_path):
    """Once LLM + channels + onboarding are satisfied the tick proceeds normally."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _campaign(storage)
    _approve_posting(storage, cid)
    discovery, digest, prefill = _CountingDiscovery(), _CountingDigest(), _FakePrefill()
    loop = _loop(storage, orch, _Gate(True), discovery=discovery, digest=digest, prefill=prefill)

    result = loop.tick(cid, now=datetime(2026, 6, 16, tzinfo=UTC))

    assert result.reason != "automated_work_gated"
    assert discovery.calls == 1
    assert digest.delivered == 1
    assert prefill.calls == 1
    assert len(result.pipelines_started) == 1


@pytest.mark.unit
def test_scheduler_tick_drives_no_new_work_when_gate_closed(tmp_path):
    """A scheduler tick performs NO discovery/digest/pipeline start while gated."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _campaign(storage)
    _approve_posting(storage, cid)
    discovery, digest, prefill = _CountingDiscovery(), _CountingDigest(), _FakePrefill()
    gate = _Gate(False)
    loop = _loop(storage, orch, gate, discovery=discovery, digest=digest, prefill=prefill)
    sched = Scheduler(storage=storage, agent_loop=loop, setup_service=gate)

    sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    assert discovery.calls == 0
    assert digest.delivered == 0
    assert prefill.calls == 0
    assert storage.applications.list_for_campaign(cid) == []
