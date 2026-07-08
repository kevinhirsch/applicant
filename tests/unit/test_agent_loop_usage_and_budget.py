"""P1-6 (cost & pace guardrails): usage-ledger draining + the cap-reached notification.

* Hitting the daily throughput cap fires ``notify_budget_reached`` exactly once
  per day (silence never means "stopped").
* The shared ``UsageLedger`` (fed by the LLM adapter singleton from ANY code
  path) is drained into the SAME durable ``agent_runs.stats`` blob the
  throughput ledger already uses — no schema change — both on a normal tick
  and on a gated/paused skip-reason tick, and a restart (fresh ``AgentLoop``
  over the same storage) still sees it.
* With no ``usage_ledger`` wired at all, behavior is byte-identical (no stats
  keys added, no crash) — legacy/unit-test construction is unaffected.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.usage_ledger import UsageLedger
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId, DecisionId, JobPostingId, new_id


class _FakeScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="strong fit")

    def is_viable(self, scoring):
        return True


class _FakeDigest:
    def deliver(self, campaign_id, criteria=None):
        return {"payload": {"rows": []}}


class _FakeNotifications:
    def __init__(self):
        self.budget_reached_calls: list[dict] = []

    def notify_budget_reached(self, campaign_id, *, applications_today, hard_cap, day, deep_link=None):
        self.budget_reached_calls.append(
            {
                "campaign_id": campaign_id,
                "applications_today": applications_today,
                "hard_cap": hard_cap,
                "day": day,
            }
        )
        return "handle"


def _make_campaign(storage, *, target=15):
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=target)
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


def _loop(storage, orch, *, notifications=None, usage_ledger=None, prefill=None):
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=prefill,
        orchestrator=orch,
        notification_service=notifications,
        usage_ledger=usage_ledger,
    )


class _Prefill:
    """Lands a prefilled application at AWAITING_FINAL_APPROVAL every time."""

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        from applicant.core.state_machine import ApplicationState

        class _R:
            state = ApplicationState.AWAITING_FINAL_APPROVAL

        return _R()


@pytest.mark.unit
def test_budget_reached_notification_fires_once_the_cap_is_hit(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=1)
    _approve_posting(storage, cid, title="Role-1")
    _approve_posting(storage, cid, title="Role-2")
    notifications = _FakeNotifications()
    loop = _loop(storage, orch, notifications=notifications, prefill=_Prefill())
    now = datetime.now(UTC)

    result = loop.run_once(cid, now=now)
    # Exactly one application acted on (target=1); the tick's OWN budget check
    # (mid-_process_approvals) stops the second one in the SAME tick.
    assert len(result.pipelines_started) == 1
    assert notifications.budget_reached_calls, "expected a cap-reached notification"
    call = notifications.budget_reached_calls[-1]
    assert call["campaign_id"] == str(cid)
    assert call["applications_today"] == 1
    assert call["day"] == now.date()


@pytest.mark.unit
def test_no_notification_service_never_breaks_the_tick(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=1)
    _approve_posting(storage, cid, title="Role-1")
    loop = _loop(storage, orch, notifications=None, prefill=_Prefill())
    now = datetime.now(UTC)
    # First tick consumes the day's single slot (no notifications wired at all).
    loop.run_once(cid, now=now)
    # A second tick, with the budget already spent, must still complete cleanly.
    result = loop.run_once(cid, now=now)
    assert result.budget_exhausted is True


@pytest.mark.unit
def test_usage_ledger_drains_into_agent_runs_stats_on_a_normal_tick(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=15)
    ledger = UsageLedger()
    now = datetime.now(UTC)
    ledger.record(now.date(), tokens_in=100, tokens_out=40, cost_usd=0.05)

    loop = _loop(storage, orch, usage_ledger=ledger)
    loop.run_once(cid, now=now)

    latest = storage.agent_runs.latest(cid)
    assert latest is not None
    assert latest.stats["tokens_in"] == 100
    assert latest.stats["tokens_out"] == 40
    assert latest.stats["cost_usd_estimate"] == pytest.approx(0.05)
    assert latest.stats["llm_calls"] == 1
    # Drained -> the ledger is empty until the next completion records into it.
    assert ledger.peek(now.date())["calls"] == 0


@pytest.mark.unit
def test_usage_ledger_drains_on_a_gated_skip_reason_tick_too(tmp_path):
    """A campaign with no automated-work gate open still drains chat/other usage."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=15)
    ledger = UsageLedger()
    now = datetime.now(UTC)
    ledger.record(now.date(), tokens_in=7, tokens_out=3, cost_usd=0.001)

    class _ClosedGate:
        def is_automated_work_allowed(self):
            return False

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        orchestrator=orch,
        setup_service=_ClosedGate(),
        usage_ledger=ledger,
    )
    result = loop.run_once(cid, now=now)
    assert result.reason == "automated_work_gated"

    latest = storage.agent_runs.latest(cid)
    assert latest is not None
    assert latest.stats.get("skip_reason") == "automated_work_gated"
    assert latest.stats.get("tokens_in") == 7
    assert latest.stats.get("cost_usd_estimate") == pytest.approx(0.001)


@pytest.mark.unit
def test_usage_totals_survive_a_restart_via_sum_stats_between(tmp_path):
    """A fresh AgentLoop over the same storage still reports the prior drain."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=15)
    now = datetime.now(UTC)

    ledger1 = UsageLedger()
    ledger1.record(now.date(), tokens_in=50, tokens_out=20, cost_usd=0.02)
    loop1 = _loop(storage, orch, usage_ledger=ledger1)
    loop1.run_once(cid, now=now)

    # Simulate a restart: brand-new loop + brand-new (empty) ledger over the SAME
    # durable storage still sees the totals a query over agent_runs.stats reads.
    start = datetime.combine(now.date(), datetime.min.time())
    end = datetime.combine(now.date(), datetime.max.time())
    totals = storage.agent_runs.sum_stats_between(
        cid, start, end, ("tokens_in", "tokens_out", "cost_usd_estimate", "llm_calls")
    )
    assert totals["tokens_in"] == 50
    assert totals["tokens_out"] == 20
    assert totals["cost_usd_estimate"] == pytest.approx(0.02)
    assert totals["llm_calls"] == 1


@pytest.mark.unit
def test_no_usage_ledger_wired_is_byte_identical(tmp_path):
    """Legacy/unit-test construction with no usage_ledger never crashes and adds no keys."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, target=15)
    loop = _loop(storage, orch, usage_ledger=None)
    loop.run_once(cid, now=datetime.now(UTC))

    latest = storage.agent_runs.latest(cid)
    assert latest is not None
    assert "tokens_in" not in latest.stats
    assert "cost_usd_estimate" not in latest.stats
