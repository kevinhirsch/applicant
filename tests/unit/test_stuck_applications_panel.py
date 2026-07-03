"""Unit tests for the paused/stuck-applications list + retry (dark-engine audit
#62).

After ``_RESUME_FAILURE_CAP`` consecutive failed resumes ``AgentLoop.
_record_resume_failure`` adds the application to the process-lived
``ResumeLedger.giveup`` set and fires one deduped notification, but until now
nothing could LIST that set or CLEAR one entry — the only way to unstick an
application was a full process restart, which throws away the ENTIRE
ledger's state for every other application too. These prove:

* ``AgentLoop.list_given_up`` reads the SAME ``ResumeLedger`` the tick loop
  writes to and returns real per-application detail (failure count, campaign,
  job title/company sourced from storage) -- not a fabricated/empty stub.
* ``AgentLoop.retry_given_up`` clears exactly one application's give-up flag
  (+ failure streak + backoff timestamp) in that same shared ledger, so a
  LATER ``AgentLoop`` instance (the scheduler rebuilds a fresh one every tick)
  immediately treats the application as resumable again.
"""

from __future__ import annotations

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import (
    _RESUME_FAILURE_CAP,
    AgentLoop,
    ResumeLedger,
)
from applicant.application.services.agent_run_service import AgentRunService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=15, schedule={})
    )
    return cid


def _posting(storage, cid, *, title="Backend Engineer", company="Acme") -> JobPostingId:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title=title, company=company, source_url="http://x")
    )
    return pid


def _application(storage, cid, pid, *, status=ApplicationState.BLOCKED_QUESTION) -> ApplicationId:
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=pid,
            status=status,
            role_name="Backend Engineer",
        )
    )
    return aid


# --- list_given_up -----------------------------------------------------------


@pytest.mark.unit
def test_list_given_up_is_empty_before_any_failures():
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    assert loop.list_given_up() == []


@pytest.mark.unit
def test_list_given_up_returns_real_details_once_the_cap_is_hit():
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    cid = _campaign(storage)
    pid = _posting(storage, cid, title="Backend Engineer", company="Acme")
    aid = _application(storage, cid, pid)

    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(aid)

    rows = loop.list_given_up()
    assert len(rows) == 1
    row = rows[0]
    assert row["application_id"] == str(aid)
    assert row["campaign_id"] == str(cid)
    assert row["failures"] == _RESUME_FAILURE_CAP
    assert row["job_title"] == "Backend Engineer"
    assert row["company"] == "Acme"
    assert row["status"] == ApplicationState.BLOCKED_QUESTION.value


@pytest.mark.unit
def test_list_given_up_excludes_applications_below_the_cap():
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    cid = _campaign(storage)
    pid = _posting(storage, cid)
    aid = _application(storage, cid, pid)

    for _ in range(_RESUME_FAILURE_CAP - 1):
        loop._record_resume_failure(aid)

    assert loop.list_given_up() == []


@pytest.mark.unit
def test_list_given_up_filters_by_campaign():
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    cid1 = _campaign(storage)
    cid2 = _campaign(storage)
    aid1 = _application(storage, cid1, _posting(storage, cid1))
    aid2 = _application(storage, cid2, _posting(storage, cid2))

    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(aid1)
        loop._record_resume_failure(aid2)

    all_rows = {r["application_id"] for r in loop.list_given_up()}
    assert all_rows == {str(aid1), str(aid2)}
    scoped = {r["application_id"] for r in loop.list_given_up(cid1)}
    assert scoped == {str(aid1)}


@pytest.mark.unit
def test_list_given_up_skips_an_entry_whose_application_no_longer_exists():
    """The ledger key can outlive the row (e.g. the application/campaign was
    since purged) -- the list must skip it rather than raise or fabricate a
    row for it."""
    storage = InMemoryStorage()
    ledger = ResumeLedger()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage), resume_ledger=ledger)
    ledger.giveup.add("ghost-app")
    ledger.failures["ghost-app"] = 9
    assert loop.list_given_up() == []


@pytest.mark.unit
def test_list_given_up_worst_failure_count_first():
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    cid = _campaign(storage)
    pid = _posting(storage, cid)
    aid_a = _application(storage, cid, pid)
    aid_b = _application(storage, cid, pid)

    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(aid_a)
    for _ in range(_RESUME_FAILURE_CAP + 3):
        loop._record_resume_failure(aid_b)

    rows = loop.list_given_up()
    assert [r["application_id"] for r in rows] == [str(aid_b), str(aid_a)]


# --- retry_given_up ------------------------------------------------------------


@pytest.mark.unit
def test_retry_given_up_is_a_noop_for_an_application_never_given_up():
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    assert loop.retry_given_up("never-stuck") is False


@pytest.mark.unit
def test_retry_given_up_clears_the_flag_and_lets_the_loop_resume_it(tmp_path):
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _campaign(storage)
    pid = _posting(storage, cid)
    aid = _application(storage, cid, pid)
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage), orchestrator=orch)

    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(aid)
    assert str(aid) in loop._resume_giveup
    # Excluded from the resumable set while given up (mirrors _resumable_apps'
    # own contract, exercised in test_agent_loop.py).
    assert str(aid) not in [str(a.id) for a in loop._resumable_apps(cid)]

    assert loop.retry_given_up(str(aid)) is True

    assert str(aid) not in loop._resume_giveup
    assert str(aid) not in loop._resume_failures
    assert str(aid) not in loop._last_resume
    # The application is resumable again on the very next tick.
    assert str(aid) in [str(a.id) for a in loop._resumable_apps(cid)]
    assert loop.list_given_up() == []


@pytest.mark.unit
def test_retry_given_up_only_clears_the_named_application():
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    cid = _campaign(storage)
    pid = _posting(storage, cid)
    aid_a = _application(storage, cid, pid)
    aid_b = _application(storage, cid, pid)

    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(aid_a)
        loop._record_resume_failure(aid_b)

    assert loop.retry_given_up(str(aid_a)) is True

    remaining = {r["application_id"] for r in loop.list_given_up()}
    assert remaining == {str(aid_b)}


@pytest.mark.unit
def test_retry_given_up_persists_across_rebuilt_loop_instances():
    """The scheduler rebuilds a fresh AgentLoop every tick (per-tick Session
    isolation), so retry_given_up must mutate the SAME process-lived
    ResumeLedger a LATER loop instance reads -- not just this instance's own
    aliases -- or the retry would silently be forgotten on the very next tick."""
    storage = InMemoryStorage()
    ledger = ResumeLedger()
    cid = _campaign(storage)
    pid = _posting(storage, cid)
    aid = _application(storage, cid, pid)

    def fresh():  # a new AgentLoop, as the scheduler builds per tick
        return AgentLoop(
            storage=storage, agent_run_service=AgentRunService(storage), resume_ledger=ledger
        )

    for _ in range(_RESUME_FAILURE_CAP):
        fresh()._record_resume_failure(aid)
    assert aid in {ApplicationId(k) for k in ledger.giveup}

    assert fresh().retry_given_up(str(aid)) is True

    assert str(aid) not in ledger.giveup
    assert fresh().list_given_up() == []
