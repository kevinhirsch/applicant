"""Unit tests for the pre-submit-safety blocked-applications list + override
(dark-engine audit #61).

G07's pre-submit safety checks (scam/ghost-job, duplicate cooldown, per-company
volume cap, eligibility/work-authorization -- ``presubmit_safety.py``) run every
tick against every APPROVED application inside ``AgentLoop._process_approvals``.
Before this fix a block was handled with only ``log.info("presubmit_blocked")``
and a ``continue`` -- the posting stayed APPROVED forever with no user-visible
reason and no way to resolve it short of guessing at a config change. These
prove:

* ``AgentLoop.list_blocked`` reads the SAME process-lived ``PresubmitBlockLedger``
  the tick loop writes to and returns real per-application detail (which check,
  the plain-language reason, how many times it has recurred, campaign/job
  title/company sourced from storage) -- not a fabricated/empty stub.
* ``AgentLoop.override_blocked`` lets the operator's OWN decision skip the G07
  checks on the NEXT tick and actually start the pipeline -- proven end to end
  by re-running a real tick afterward and observing the application leave
  APPROVED and the block bookkeeping clear.

Mirrors ``test_stuck_applications_panel.py`` (#62)'s shape: hermetic
``InMemoryStorage`` + a real ``CheckpointShimOrchestrator``, a shared
``PresubmitBlockLedger`` threaded across separate ``AgentLoop`` instances the
same way the container injects one process-lived ledger into every per-tick
rebuild.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop, PresubmitBlockLedger
from applicant.application.services.agent_run_service import AgentRunService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId, DecisionId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# --- fakes -------------------------------------------------------------------
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


#: Same shape/keys as ``container.py``'s settings-derived dict -- non-None so
#: the G07 checks actually run (``None`` skips them, byte-identical to before).
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


def _loop(storage, orch, *, prefill=None, presubmit_block_ledger=None):
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=prefill,
        orchestrator=orch,
        presubmit_safety_params=_PRESUBMIT_PARAMS,
        presubmit_block_ledger=presubmit_block_ledger,
    )


# --- list_blocked --------------------------------------------------------------


@pytest.mark.unit
def test_list_blocked_is_empty_before_any_block(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    loop = _loop(storage, orch)
    assert loop.list_blocked() == []


@pytest.mark.unit
def test_a_scam_signal_blocks_the_pipeline_and_persists_the_reason(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, title="Backend Engineer", company="Confidential")
    loop = _loop(storage, orch)

    result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert result.ran is True
    assert result.pipelines_started == []

    apps = storage.applications.list_for_campaign(cid)
    assert len(apps) == 1
    app = apps[0]
    assert app.status is ApplicationState.APPROVED, "a block must leave the posting APPROVED"

    rows = loop.list_blocked(cid)
    assert len(rows) == 1
    row = rows[0]
    assert row["application_id"] == str(app.id)
    assert row["campaign_id"] == str(cid)
    assert row["check"] == "company_reputation"
    assert "placeholder" in row["reason"].lower()
    assert row["times_blocked"] == 1
    assert row["job_title"] == "Backend Engineer"
    assert row["company"] == "Confidential"
    assert row["first_blocked_at"] == row["last_blocked_at"]
    assert row["status"] == ApplicationState.APPROVED.value


@pytest.mark.unit
def test_a_later_tick_increments_times_blocked_and_keeps_first_seen(tmp_path):
    """A LATER ``AgentLoop`` instance (the scheduler rebuilds one every tick)
    sharing the SAME injected ledger must see the recurrence -- a per-instance
    dict would have reset the counter to 1 every time."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, company="Confidential")
    ledger = PresubmitBlockLedger()

    loop1 = _loop(storage, orch, presubmit_block_ledger=ledger)
    loop1.run_once(cid, now=datetime(2026, 6, 16, 8, 0, tzinfo=UTC))
    first = loop1.list_blocked(cid)[0]

    loop2 = _loop(storage, orch, presubmit_block_ledger=ledger)
    loop2.run_once(cid, now=datetime(2026, 6, 16, 8, 1, tzinfo=UTC))
    second = loop2.list_blocked(cid)[0]

    assert second["times_blocked"] == 2
    assert second["first_blocked_at"] == first["first_blocked_at"]
    assert second["last_blocked_at"] != first["last_blocked_at"]


@pytest.mark.unit
def test_list_blocked_filters_by_campaign(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    ledger = PresubmitBlockLedger()
    cid1 = _make_campaign(storage)
    cid2 = _make_campaign(storage)
    _approve_posting(storage, cid1, title="Backend Engineer", company="Confidential")
    _approve_posting(storage, cid2, title="Frontend Engineer", company="Confidential")
    loop = _loop(storage, orch, presubmit_block_ledger=ledger)

    loop.run_once(cid1, now=datetime(2026, 6, 16, tzinfo=UTC))
    loop.run_once(cid2, now=datetime(2026, 6, 16, tzinfo=UTC))

    all_campaigns = {r["campaign_id"] for r in loop.list_blocked()}
    assert all_campaigns == {str(cid1), str(cid2)}
    scoped = loop.list_blocked(cid1)
    assert len(scoped) == 1
    assert scoped[0]["campaign_id"] == str(cid1)


@pytest.mark.unit
def test_list_blocked_skips_an_entry_whose_application_no_longer_exists():
    """The ledger key can outlive the row (e.g. purged data) -- the list must
    skip it rather than raise or fabricate a row for it (mirrors #62's
    ``test_list_given_up_skips_an_entry_whose_application_no_longer_exists``)."""
    storage = InMemoryStorage()
    ledger = PresubmitBlockLedger()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        presubmit_safety_params=_PRESUBMIT_PARAMS,
        presubmit_block_ledger=ledger,
    )
    ledger.blocks["ghost-app"] = {
        "application_id": "ghost-app",
        "campaign_id": "ghost-campaign",
        "check": "duplicate_cooldown",
        "reason": "stale",
        "first_blocked_at": "2026-01-01T00:00:00+00:00",
        "last_blocked_at": "2026-01-01T00:00:00+00:00",
        "times_blocked": 1,
    }
    assert loop.list_blocked() == []


@pytest.mark.unit
def test_list_blocked_excludes_an_application_that_has_moved_past_approved(tmp_path):
    """A stale ledger entry for an application that has since moved on (e.g. a
    later, un-modeled path advanced it) must not keep showing as blocked."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, company="Confidential")
    loop = _loop(storage, orch)
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    app = storage.applications.list_for_campaign(cid)[0]
    assert loop.list_blocked(cid)

    moved = dataclasses.replace(app, status=ApplicationState.FAILED)
    storage.applications.update(moved)

    assert loop.list_blocked(cid) == []


# --- override_blocked ----------------------------------------------------------


@pytest.mark.unit
def test_override_blocked_is_a_noop_for_an_application_never_blocked(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    loop = _loop(storage, orch)
    assert loop.override_blocked("never-blocked") is False


@pytest.mark.unit
def test_override_blocked_lets_a_later_tick_start_the_pipeline(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, company="Confidential")
    ledger = PresubmitBlockLedger()
    prefill = _FakePrefill()

    loop1 = _loop(storage, orch, prefill=prefill, presubmit_block_ledger=ledger)
    loop1.run_once(cid, now=datetime(2026, 6, 16, 8, 0, tzinfo=UTC))
    app = storage.applications.list_for_campaign(cid)[0]
    assert app.status is ApplicationState.APPROVED
    assert loop1.list_blocked(cid)

    assert loop1.override_blocked(str(app.id)) is True
    assert str(app.id) in ledger.overridden

    # A LATER AgentLoop instance (the scheduler rebuilds one every tick) shares
    # the SAME injected ledger, so it honors the override too.
    loop2 = _loop(storage, orch, prefill=prefill, presubmit_block_ledger=ledger)
    result = loop2.run_once(cid, now=datetime(2026, 6, 16, 8, 1, tzinfo=UTC))

    app_after = storage.applications.get(app.id)
    assert app_after.status is not ApplicationState.APPROVED, (
        "an override must let the pipeline actually start"
    )
    assert str(app.id) in result.pipelines_started
    assert prefill.calls == 1
    # The block bookkeeping is cleared now that it actually started -- no
    # stale row, no stale override flag left behind.
    assert loop2.list_blocked(cid) == []
    assert str(app.id) not in ledger.overridden


@pytest.mark.unit
def test_override_blocked_404_style_noop_does_not_touch_an_unrelated_block(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid, company="Confidential")
    loop = _loop(storage, orch)
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    app = storage.applications.list_for_campaign(cid)[0]

    assert loop.override_blocked("some-other-application") is False
    # The real block is untouched.
    assert len(loop.list_blocked(cid)) == 1
    assert loop.list_blocked(cid)[0]["application_id"] == str(app.id)
