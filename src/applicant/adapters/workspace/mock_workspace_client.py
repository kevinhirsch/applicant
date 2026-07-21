"""Deterministic mock WorkspacePort — pure fixtures, no network.

Implements :class:`~applicant.ports.driven.workspace.WorkspacePort` by serving
realistic fixture data from in-memory structures, so lane logic (email outcome
scanning, calendar read + write-back) is testable without real IMAP/CalDAV or
Google credentials. The real :class:`HttpWorkspaceClient` and this mock share
the SAME port/protocol — swapping one for the other at the container seam
is the only change needed to run the same lane code against real credentials.

Fixture emails include a rejection, an interview invite, and an offer, each
with realistic subjects/bodies that exercise the keyword classifiers in
:class:`~applicant.application.services.post_submission_service.PostSubmissionService`.
The mock calendar supports read (returns pre-seeded events) and write-back
(records events in memory with deduplication via ``dedupe_key``).
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any


# ---------------------------------------------------------------------------
# Fixture data — deterministic, realistic, exercise all three classifiers
# ---------------------------------------------------------------------------

_FIXTURE_EMAILS: list[dict[str, str]] = [
    {
        "uid": "email-001-rejection",
        "subject": "Update on your application to Acme Corp",
        "from": "hr@acmecorp.com",
        "body": (
            "Thank you for your interest in the Senior Backend Engineer position at "
            "Acme Corp. Unfortunately, after careful review we regret to inform you "
            "that we have decided to move forward with other candidates. Your "
            "application has not been selected for this role.\n\n"
            "We wish you the best in your job search.\n\n"
            "Best regards,\nAcme Corp Talent Team"
        ),
        "date": "2026-07-20T10:00:00Z",
    },
    {
        "uid": "email-002-interview",
        "subject": "Interview invitation — Globex Inc",
        "from": "recruiting@globex.com",
        "body": (
            "Hi there,\n\n"
            "Congratulations! We were impressed by your resume and would like to "
            "schedule an interview for the Frontend Developer role at Globex Inc. "
            "This would be a phone screen with the hiring manager.\n\n"
            "Please let us know your availability for next week. The interview "
            "should take about 45 minutes.\n\n"
            "Best,\nGlobex Talent Acquisition"
        ),
        "date": "2026-07-19T14:30:00Z",
    },
    {
        "uid": "email-003-offer",
        "subject": "Job offer — Initech",
        "from": "jobs@initech.com",
        "body": (
            "Dear Candidate,\n\n"
            "We are pleased to offer you the position of Data Scientist at Initech. "
            "We were excited to extend this offer after a great interview process. "
            "Please find the offer letter attached.\n\n"
            "We welcome you to the team and look forward to having you on board.\n\n"
            "Sincerely,\nInitech HR"
        ),
        "date": "2026-07-18T09:00:00Z",
    },
    {
        "uid": "email-004-no-match",
        "subject": "Your weekly newsletter",
        "from": "newsletter@somewhere.com",
        "body": (
            "Here are this week's tech news highlights. Nothing about job "
            "applications here."
        ),
        "date": "2026-07-17T08:00:00Z",
    },
]

_FIXTURE_CALENDAR_INTERVIEWS: dict = {
    "events": [
        {
            "uid": "cal-evt-001",
            "title": "Phone screen — Acme Corp",
            "start": "2026-07-25T14:00:00",
            "end": "2026-07-25T14:45:00",
            "all_day": False,
            "notes": "Initial phone screen for Senior Backend Engineer role",
            "location": "Zoom",
        }
    ]
}


class MockWorkspaceClient:
    """Mock WorkspacePort — deterministic fixture data, in-memory write-back.

    Implements the full :class:`~applicant.ports.driven.workspace.WorkspacePort`
    protocol (``available``, ``ping``, ``calendar_interviews``,
    ``create_calendar_event``, ``recent_emails``) with no network I/O.

    ``recent_emails`` returns :data:`_FIXTURE_EMAILS` — a set of four messages
    that exercise each outcome classifier: one clear rejection, one confident
    interview invite, one confident offer, and one neutral email that should
    match nothing.

    ``calendar_interviews`` returns :data:`_FIXTURE_CALENDAR_INTERVIEWS` — a
    pre-seeded single interview event.

    ``create_calendar_event`` stores the event in an in-memory list
    (``written_events``) with deduplication: if ``dedupe_key`` matches an
    existing stored event, that event is updated rather than appended.
    """

    def __init__(
        self,
        *,
        available: bool = True,
        emails: list[dict[str, str]] | None = None,
        calendar_events: dict | None = None,
    ) -> None:
        """
        Args:
            available: Mock value for :meth:`available()`. Set ``False`` to
                simulate a disabled/unconfigured channel.
            emails: Override the default fixture emails. ``None`` uses
                :data:`_FIXTURE_EMAILS`.
            calendar_events: Override the default fixture calendar events.
                ``None`` uses :data:`_FIXTURE_CALENDAR_INTERVIEWS`.
        """
        self._available = available
        self._emails = list(emails if emails is not None else _FIXTURE_EMAILS)
        self._calendar_events = copy.deepcopy(
            calendar_events if calendar_events is not None else _FIXTURE_CALENDAR_INTERVIEWS
        )
        #: List of events written via :meth:`create_calendar_event`, in the
        #: order they were received. Deduped by ``dedupe_key``: a second call
        #: with the same key updates the existing entry instead of appending.
        self.written_events: list[dict[str, Any]] = []
        #: Number of ``ping`` calls received.
        self.ping_count: int = 0
        #: Number of ``calendar_interviews`` calls received.
        self.calendar_read_count: int = 0

    # --- config gate -------------------------------------------------------

    def available(self) -> bool:
        """Return the mock availability flag (``True`` by default)."""
        return self._available

    # --- liveness probe ----------------------------------------------------

    def ping(self, *, owner: str | None = None) -> dict:
        """Record the ping and return a success payload."""
        self.ping_count += 1
        return {"ok": True, "owner": owner or "mock-owner"}

    # --- Lane A: calendar ---------------------------------------------------

    def calendar_interviews(self, *, owner: str | None = None) -> dict:
        """Return the pre-seeded fixture interview events."""
        self.calendar_read_count += 1
        return copy.deepcopy(self._calendar_events)

    def create_calendar_event(
        self,
        *,
        title: str,
        start: str,
        owner: str | None = None,
        end: str | None = None,
        notes: str | None = None,
        location: str | None = None,
        all_day: bool = False,
        dedupe_key: str | None = None,
    ) -> dict:
        """Store an event in-memory with deduplication by ``dedupe_key``.

        Dedup logic: if ``dedupe_key`` is provided and matches an existing
        entry's ``dedupe_key``, that entry is UPDATED in place (simulating the
        real workspace's upsert behaviour). Otherwise the event is appended.

        Returns a dict matching the real endpoint's shape.
        """
        event: dict[str, Any] = {
            "title": title,
            "start": start,
            "all_day": bool(all_day),
        }
        if end is not None:
            event["end"] = end
        if notes is not None:
            event["notes"] = notes
        if location is not None:
            event["location"] = location
        if dedupe_key is not None:
            event["dedupe_key"] = dedupe_key

        if dedupe_key is not None:
            for i, existing in enumerate(self.written_events):
                if existing.get("dedupe_key") == dedupe_key:
                    self.written_events[i] = event
                    return {"ok": True, "uid": f"evt-{dedupe_key}", "created": False, "updated": True}

        self.written_events.append(event)
        uid = f"evt-{len(self.written_events)}"
        return {"ok": True, "uid": uid, "created": True, "updated": False}

    # --- Lane C: email inbox -------------------------------------------------

    def recent_emails(self, *, owner: str | None = None, limit: int = 20) -> dict:
        """Return fixture emails (newest first), respecting ``limit``."""
        limited = self._emails[:max(0, limit)]
        return {"emails": copy.deepcopy(limited)}

    # --- Memory bridge stubs (not needed for lane tests) ---------------------

    def memory_snapshot(self, **kwargs) -> dict:
        return {"snapshot": []}

    def memory_add(self, **kwargs) -> dict:
        return {"ok": True}

    def memory_replace(self, **kwargs) -> dict:
        return {"ok": True}

    def memory_remove(self, **kwargs) -> dict:
        return {"ok": True}

    def skills_list(self, **kwargs) -> dict:
        return {"skills": []}

    def skill_load(self, name: str, **kwargs) -> dict:
        return {"skill": {"name": name, "body": ""}}

    def skill_create(self, **kwargs) -> dict:
        return {"ok": True}

    def skill_patch(self, name: str, **kwargs) -> dict:
        return {"ok": True}

    def skill_edit(self, name: str, **kwargs) -> dict:
        return {"ok": True}

    def skill_delete(self, name: str, **kwargs) -> dict:
        return {"ok": True}

    def recall(self, **kwargs) -> dict:
        return {"results": []}

    def run_research(
        self,
        *,
        query: str,
        owner: str | None = None,
        company: str | None = None,
        role: str | None = None,
        context: str | None = None,
        max_time: int | None = None,
    ) -> dict:
        return {
            "query": query,
            "summary": f"Mock research result for {query}",
            "key_findings": ["Mock finding 1", "Mock finding 2"],
            "sources": [],
        }
