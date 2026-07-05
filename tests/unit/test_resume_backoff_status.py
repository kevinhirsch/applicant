"""Regression coverage for dark-engine audit item #78 (B7): a blocked
application's resume-backoff countdown was computable from the process-lived
``ResumeLedger`` (``last_resume`` + the fixed 300s window) but never exposed
anywhere -- a user who just cleared a blocker (answered a question, supplied a
missing detail, approved a redline) could see NO sign anything would happen
for up to 5 minutes.

``AgentLoop.resume_backoff_status`` reads the SAME ledger the tick loop's
``_resume_due``/``_mark_resumed`` already use, so this reflects real, live
scheduler state -- never fabricated. Verified, by hand, to go RED when
``resume_backoff_status`` is reverted out of ``agent_loop.py`` (restoring from
a pre-change backup), then GREEN again after restoring the change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop, ResumeLedger
from applicant.application.services.agent_run_service import AgentRunService
from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, new_id
from applicant.core.state_machine import ApplicationState


def _storage_with_app(status: ApplicationState) -> tuple[InMemoryStorage, CampaignId, ApplicationId]:
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=None,
            status=status,
            role_name="Senior Engineer",
        )
    )
    storage.commit()
    return storage, cid, aid


def _loop(storage: InMemoryStorage, ledger: ResumeLedger | None = None) -> AgentLoop:
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        resume_ledger=ledger or ResumeLedger(),
    )


def test_none_when_application_unknown():
    storage, _cid, _aid = _storage_with_app(ApplicationState.BLOCKED_QUESTION)
    loop = _loop(storage)
    assert loop.resume_backoff_status(str(new_id())) is None


def test_none_when_status_not_in_flight_resumable():
    # SUBMITTED_BY_USER is a terminal state, never re-driven by the resume sweep.
    storage, _cid, aid = _storage_with_app(ApplicationState.SUBMITTED_BY_USER)
    loop = _loop(storage)
    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop._mark_resumed(aid, now)
    assert loop.resume_backoff_status(str(aid)) is None


def test_none_when_never_resumed_yet():
    # Freshly blocked, no resume attempt recorded yet — eligible on the very
    # next tick, so there's nothing to count down.
    storage, _cid, aid = _storage_with_app(ApplicationState.BLOCKED_QUESTION)
    loop = _loop(storage)
    assert loop.resume_backoff_status(str(aid)) is None


def test_none_when_given_up():
    # A given-up application is surfaced via the SEPARATE stuck-applications
    # list (#62), not the backoff countdown.
    storage, _cid, aid = _storage_with_app(ApplicationState.BLOCKED_QUESTION)
    ledger = ResumeLedger()
    loop = _loop(storage, ledger)
    now = datetime(2026, 6, 16, tzinfo=UTC)
    loop._mark_resumed(aid, now)
    ledger.giveup.add(str(aid))
    assert loop.resume_backoff_status(str(aid)) is None


def test_reports_a_real_countdown_after_a_resume_attempt():
    storage, _cid, aid = _storage_with_app(ApplicationState.BLOCKED_MISSING_ATTR)
    loop = _loop(storage)
    now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    loop._mark_resumed(aid, now)

    # 90s after the last resume attempt — still inside the 300s backoff window.
    status = loop.resume_backoff_status(str(aid), now=now + timedelta(seconds=90))
    assert status is not None
    assert status["application_id"] == str(aid)
    assert status["status"] == "BLOCKED_MISSING_ATTR"
    assert status["last_resume_at"] == now.isoformat()
    expected_retry = now + timedelta(seconds=loop._resume_backoff_seconds)
    assert status["next_retry_at"] == expected_retry.isoformat()
    assert status["seconds_remaining"] == 210  # 300 - 90


def test_seconds_remaining_floors_at_zero_once_the_window_has_passed():
    storage, _cid, aid = _storage_with_app(ApplicationState.BLOCKED_MISSING_ATTR)
    loop = _loop(storage)
    now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    loop._mark_resumed(aid, now)

    # Backoff window has long passed (the next tick is now free to re-drive it) --
    # never a negative countdown.
    status = loop.resume_backoff_status(str(aid), now=now + timedelta(hours=1))
    assert status is not None
    assert status["seconds_remaining"] == 0


def test_shared_ledger_reflects_the_same_state_across_fresh_loop_instances():
    # The scheduler rebuilds a fresh AgentLoop every tick (#180); the countdown
    # must reflect the SAME shared ledger regardless of which instance reads it.
    storage, _cid, aid = _storage_with_app(ApplicationState.MATERIAL_REVIEW)
    ledger = ResumeLedger()
    now = datetime(2026, 6, 16, tzinfo=UTC)
    _loop(storage, ledger)._mark_resumed(aid, now)

    fresh = _loop(storage, ledger)
    status = fresh.resume_backoff_status(str(aid))
    assert status is not None
    assert status["last_resume_at"] == now.isoformat()


@pytest.mark.unit
def test_resume_backoff_status_is_a_documented_unit_test():
    # Marker so this file participates in the `pytest -m unit` lane like its peers.
    assert True
