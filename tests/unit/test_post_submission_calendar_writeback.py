"""Engine-side write-back: a detected interview lands on the workspace calendar
(dark-engine audit item 69).

Before this, ``HttpWorkspaceClient.calendar_interviews`` could only READ the
owner's workspace calendar to notice an interview (lane A); nothing ever wrote
one. ``PostSubmissionService.scan_email_for_interview`` already detects a
confident interview invite from an inbound email and records an
``interview_invited`` ``OutcomeEvent`` -- this file pins that a confident
detection ALSO calls ``WorkspacePort.create_calendar_event`` (best-effort), and
that the write can never break outcome recording, whether the workspace is
unconfigured, disabled, or a live call raises.

Hermetic: ``InMemoryStorage`` + a fake ``WorkspacePort`` (no network).
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.post_submission_service import PostSubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.workspace import WorkspaceError


class _FakeWorkspace:
    """Records every ``create_calendar_event`` call; can simulate every
    failure mode a real ``HttpWorkspaceClient`` would surface."""

    def __init__(self, *, available=True, raises=False):
        self._available = available
        self._raises = raises
        self.calls: list[dict] = []

    def available(self) -> bool:
        return self._available

    def create_calendar_event(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise WorkspaceError("workspace down")
        return {"ok": True, "uid": "evt-1", "created": True}


def _wire(*, workspace=None):
    storage = InMemoryStorage()
    svc = PostSubmissionService(storage, workspace=workspace)
    return storage, svc


def _seed_app(storage, *, company="Acme Corp", title="Backend Engineer", source_url="https://example.com/job"):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="c"))
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title=title,
        company=company,
        source_url=source_url,
    )
    storage.postings.add(posting)
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=posting.id,
        status=ApplicationState.AWAITING_RESPONSE,
    )
    storage.applications.add(app)
    return app, posting


@pytest.mark.unit
class TestCalendarWriteback:
    def test_confident_detection_writes_a_calendar_event(self):
        ws = _FakeWorkspace()
        storage, svc = _wire(workspace=ws)
        app, posting = _seed_app(storage, company="Acme Corp", title="Backend Engineer")

        event = svc.scan_email_for_interview(
            "Next steps for your application",
            "We would like to schedule a call for a phone screen -- this is an interview.",
            app.id,
        )

        assert event is not None  # the OutcomeEvent is still recorded
        assert len(ws.calls) == 1
        call = ws.calls[0]
        assert call["title"] == "Interview invite: Acme Corp — Backend Engineer"
        assert call["all_day"] is True
        assert call["dedupe_key"] == str(app.id)
        assert "https://example.com/job" in call["notes"]
        assert call["location"] == "https://example.com/job"
        assert call["start"]  # some ISO timestamp was supplied

    def test_no_confident_detection_never_calls_the_workspace(self):
        ws = _FakeWorkspace()
        storage, svc = _wire(workspace=ws)
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_interview("Hi", "Thanks for your interview interest.", app.id)

        assert event is None
        assert ws.calls == []

    def test_none_workspace_is_a_silent_no_op(self):
        """The default -- every existing caller before this change constructs
        PostSubmissionService with no workspace -- must behave byte-identical."""
        storage, svc = _wire(workspace=None)
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_interview(
            "Next steps", "Let's schedule a call for a phone screen interview.", app.id
        )

        assert event is not None
        assert event.type == "interview_invited"

    def test_disabled_channel_is_a_silent_no_op(self):
        ws = _FakeWorkspace(available=False)
        storage, svc = _wire(workspace=ws)
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_interview(
            "Next steps", "Let's schedule a call for a phone screen interview.", app.id
        )

        assert event is not None
        assert ws.calls == []  # available() gate short-circuits before any call

    def test_calendar_write_failure_never_breaks_outcome_recording(self):
        """A flaky/unreachable workspace must NEVER un-record the interview --
        the OutcomeEvent is the authoritative record; the calendar entry is a
        best-effort nicety layered on top."""
        ws = _FakeWorkspace(raises=True)
        storage, svc = _wire(workspace=ws)
        app, _ = _seed_app(storage)

        event = svc.scan_email_for_interview(
            "Next steps", "Let's schedule a call for a phone screen interview.", app.id
        )

        assert event is not None
        assert event.type == "interview_invited"
        stored = list(storage.outcomes.list_for_application(app.id))
        assert any(e.type == "interview_invited" for e in stored)
        assert len(ws.calls) == 1  # it WAS attempted, just failed harmlessly

    def test_missing_posting_still_writes_a_generic_event(self):
        """No resolvable posting -> no company/role/link, but the write-back
        still happens with a generic label (never raises)."""
        ws = _FakeWorkspace()
        storage = InMemoryStorage()
        svc = PostSubmissionService(storage, workspace=ws)
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="c"))
        app = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=None,
            status=ApplicationState.AWAITING_RESPONSE,
        )
        storage.applications.add(app)

        event = svc.scan_email_for_interview(
            "Next steps", "Let's schedule a call for a phone screen interview.", app.id
        )

        assert event is not None
        assert len(ws.calls) == 1
        assert ws.calls[0]["title"] == "Interview invite: your application"
        assert ws.calls[0]["location"] == ""
