"""Lane logic tests over the mock workspace backend — deterministic, no network.

Tests that :class:`~applicant.application.services.post_submission_service.PostSubmissionService`
correctly classifies inbound emails and reads/writes calendar events when backed
by :class:`~applicant.adapters.workspace.mock_workspace_client.MockWorkspaceClient`
(a pure-fixture, in-memory implementation of the same
:class:`~applicant.ports.driven.workspace.WorkspacePort` protocol that the real
:class:`HttpWorkspaceClient` implements).

The mock serves four fixture emails: one rejection (Acme Corp), one interview
invite (Globex Inc), one offer (Initech), and one neutral newsletter (no match).
The mock calendar returns a pre-seeded interview event and records write-back
calls with deduplication.

Hermetic: InMemoryStorage + MockWorkspaceClient — no network, no real IMAP/CalDAV.
These tests run on every invocation (no skip guard) because the mock is always
available.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.adapters.workspace.mock_workspace_client import MockWorkspaceClient
from applicant.application.services.post_submission_service import PostSubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_company(storage, cid, *, company: str, title: str = "Engineer") -> tuple[JobPosting, Application]:
    """Create a single posting + application for a given company, in AWAITING_RESPONSE."""
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title=title,
        company=company,
        source_url=f"https://{company.lower().replace(' ', '')}.example.com/jobs/1",
    )
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=posting.id,
        status=ApplicationState.AWAITING_RESPONSE,
    )
    storage.postings.add(posting)
    storage.applications.add(app)
    return posting, app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMockBackendEmailOutcomeScan:
    """scan_inbox_for_outcomes over the mock backend's fixture emails."""

    def test_no_workspace_wired_is_noop(self):
        """Default (no workspace) degrades without error."""
        storage = InMemoryStorage()
        svc = PostSubmissionService(storage)
        result = svc.scan_inbox_for_outcomes(CampaignId(new_id()))
        assert result == {"scanned": 0, "matched": 0, "outcomes": []}

    def test_unavailable_mock_is_noop(self):
        """Mock with available=False should short-circuit like the real backend."""
        ws = MockWorkspaceClient(available=False)
        storage = InMemoryStorage()
        svc = PostSubmissionService(storage, workspace=ws)
        result = svc.scan_inbox_for_outcomes(CampaignId(new_id()))
        assert result == {"scanned": 0, "matched": 0, "outcomes": []}
        # Should never have asked for emails
        assert ws.ping_count == 0
        assert ws.calendar_read_count == 0

    def test_no_matching_companies_skips_all_emails(self):
        """No seeded applications => no company names to match against => all emails skipped."""
        ws = MockWorkspaceClient()
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="Test Campaign"))
        svc = PostSubmissionService(storage, workspace=ws)
        result = svc.scan_inbox_for_outcomes(cid)
        assert result == {"scanned": 0, "matched": 0, "outcomes": []}

    def test_all_three_outcomes_detected_from_fixture_emails(self):
        """
        Seed applications for Acme Corp (rejection), Globex Inc (interview),
        and Initech (offer). The mock's fixture emails include one of each
        plus a neutral email. All three outcomes should be detected.
        """
        ws = MockWorkspaceClient()
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="Test Campaign"))

        acme_posting, acme_app = _seed_company(storage, cid, company="Acme Corp", title="Senior Backend Engineer")
        globex_posting, globex_app = _seed_company(storage, cid, company="Globex Inc", title="Frontend Developer")
        initech_posting, initech_app = _seed_company(storage, cid, company="Initech", title="Data Scientist")
        # A fourth company with no matching fixture email
        nogood_posting, nogood_app = _seed_company(storage, cid, company="NoMatch Co", title="Intern")

        svc = PostSubmissionService(storage, workspace=ws)
        result = svc.scan_inbox_for_outcomes(cid, limit=10)

        # 4 fixture emails, 4 seeded companies; the newsletter (email-004) has
        # no company name match — scanned includes only the 3 that match
        assert result["scanned"] == 3, f"Expected 3 scanned, got {result}"
        assert result["matched"] == 3, f"Expected 3 matched outcomes, got {result}"

        # Build a lookup by application_id for easy assertion
        outcome_by_app: dict[str, str] = {
            o["application_id"]: o["outcome_type"] for o in result["outcomes"]
        }

        # Acme Corp fixture email is a rejection
        assert str(acme_app.id) in outcome_by_app, "Acme app missing from outcomes"
        assert outcome_by_app[str(acme_app.id)] == "rejected"
        # Acme should be status REJECTED
        assert storage.applications.get(acme_app.id).status == ApplicationState.REJECTED

        # Globex Inc fixture email is an interview invite
        assert str(globex_app.id) in outcome_by_app, "Globex app missing from outcomes"
        assert outcome_by_app[str(globex_app.id)] == "interview_invited"

        # Initech fixture email is an offer
        assert str(initech_app.id) in outcome_by_app, "Initech app missing from outcomes"
        assert outcome_by_app[str(initech_app.id)] == "offer"

        # NoMatch Co has no matching fixture email, so it should NOT appear
        assert str(nogood_app.id) not in outcome_by_app

    def test_neutral_email_is_scanned_but_not_recorded(self):
        """The newsletter fixture email matches NoMatch co by accident? Actually
        the newsletter has no company name reachable — let's check it matches
        nothing. Here we seed ONLY NoMatch Co and expect 0 matches because the
        newsletter body doesn't contain 'NoMatch Co'."""
        ws = MockWorkspaceClient()
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="Test Campaign"))

        _seed_company(storage, cid, company="NoMatch Co")

        svc = PostSubmissionService(storage, workspace=ws)
        result = svc.scan_inbox_for_outcomes(cid, limit=10)

        # The newsletter fixture does NOT contain "NoMatch Co" so 0 scanned
        assert result["scanned"] == 0
        assert result["matched"] == 0
        assert result["outcomes"] == []

    def test_rejection_email_short_circuits_positive_detection(self):
        """Acme Corp's fixture email is a rejection. Even if the body contained
        interview/offer keywords (it doesn't), rejection runs first and the
        confident rejection SHOULD short-circuit, preventing a positive match
        on the same application. This test confirms the rejection is recorded
        and no interview/offer outcome is simultaneously created."""
        ws = MockWorkspaceClient()
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="Test Campaign"))

        acme_posting, acme_app = _seed_company(storage, cid, company="Acme Corp")

        svc = PostSubmissionService(storage, workspace=ws)
        result = svc.scan_inbox_for_outcomes(cid, limit=1)

        # Only the Acme Corp rejection should be detected (first email)
        assert result["scanned"] == 1
        assert result["matched"] == 1
        assert result["outcomes"][0]["outcome_type"] == "rejected"
        assert storage.applications.get(acme_app.id).status == ApplicationState.REJECTED


class TestMockBackendCalendarWriteback:
    """Calendar read + write-back over the mock backend."""

    def test_confident_interview_detection_writes_calendar_event(self):
        """A confident interview invite should also write a calendar event
        via _write_interview_to_calendar, which calls create_calendar_event
        on the mock workspace."""
        ws = MockWorkspaceClient()
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="Test Campaign"))

        globex_posting, globex_app = _seed_company(
            storage, cid, company="Globex Inc", title="Frontend Developer",
        )

        svc = PostSubmissionService(storage, workspace=ws)
        result = svc.scan_inbox_for_outcomes(cid, limit=2)

        # The second fixture email (Globex interview invite) should have
        # triggered both the outcome AND the calendar write-back
        assert result["matched"] == 1
        assert result["outcomes"][0]["outcome_type"] == "interview_invited"

        # Verify the calendar event was written
        assert len(ws.written_events) == 1
        ev = ws.written_events[0]
        assert "Globex Inc" in ev["title"]
        assert "Frontend Developer" in ev["title"]
        assert ev["all_day"] is True
        assert ev["dedupe_key"] == str(globex_app.id)

    def test_calendar_write_dedup(self):
        """Calling scan_inbox_for_outcomes TWICE with the same mock should
        NOT create a duplicate event — the dedupe_key keeps it singletons."""
        ws = MockWorkspaceClient()
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="Test Campaign"))

        globex_posting, globex_app = _seed_company(
            storage, cid, company="Globex Inc", title="Frontend Developer",
        )

        svc = PostSubmissionService(storage, workspace=ws)
        # First scan — should create the event
        result1 = svc.scan_inbox_for_outcomes(cid, limit=2)
        assert result1["matched"] == 1
        assert len(ws.written_events) == 1

        # Second scan — the outcome is already recorded so scan_email won't
        # fire again, but let's call scan_email_for_interview directly to
        # verify dedup on the calendar side
        _ = svc.scan_email_for_interview(
            "Interview invitation — Globex Inc",
            "We would like to schedule an interview for the Frontend Developer role...",
            globex_app.id,
        )

        # Still one event — the second call updated it (deduped)
        assert len(ws.written_events) == 1

    def test_calendar_read_returns_fixture_events(self):
        """The mock's calendar_interviews returns the pre-seeded fixture."""
        ws = MockWorkspaceClient()
        events = ws.calendar_interviews()
        assert "events" in events
        assert len(events["events"]) == 1
        ev = events["events"][0]
        assert ev["title"] == "Phone screen — Acme Corp"
        assert ev["start"] == "2026-07-25T14:00:00"
        assert ev["end"] == "2026-07-25T14:45:00"
