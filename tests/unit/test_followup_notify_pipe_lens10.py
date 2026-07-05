"""Lens 10 (notifications audit) findings #1 / #53 — the follow-up notify pipe.

``send_scheduled_follow_ups`` (``post_submission_service.py``) routes each due,
owner-approved follow-up through the notification port so the owner is told it
went out. Two things were wrong with that pipe (`docs/design/audits/exhaustive2/
10_notifications.md`, findings #1 and #53):

#1 — dead pipe: the call used to target a nonexistent ``NotificationService
.notify(...)`` method. Every call raised ``AttributeError``, silently swallowed
by the surrounding ``try/except: continue``, so the follow-up was never
appended to ``sent`` and the application never transitioned to
``FOLLOWING_UP`` — due follow-ups retried forever. (A prior commit already
repointed the call at the REAL ``notify_decision`` method; this suite pins
that down as a still-required regression guard.)

#53 — even once the pipe is alive, the notification TITLE was the raw
follow-up subject/body content ("Thank you for your time" / "Checking in on
my application") — first-person text ADDRESSED TO THE EMPLOYER — routed
verbatim into the user-facing notification title. That reads as the PRODUCT
itself thanking the user, not a message FROM the product. This suite asserts
the title is now reframed in the product's own decision-style voice ("Follow-
up drafted for {company} — review & send") with the actual follow-up copy
carried in the notification BODY instead.

Hermetic: ``InMemoryStorage`` + a hand-rolled notification spy, no DB/browser.
Every assertion below was hand-verified RED before the fix (either raising
via a spy that only implements ``notify_decision`` -- reproducing the dead
``.notify()`` pipe -- or asserting the NEW title copy against the OLD
``title=fup.subject`` code path) and GREEN after, per the dispatch brief.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.post_submission_service import PostSubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.follow_up import FollowUpTemplate
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _posting(cid, *, company="Acme Corp", title="Senior Engineer"):
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title=title,
        company=company,
        source_url="https://acme.example.com/jobs/1",
    )


def _app(cid, posting_id, status=ApplicationState.AWAITING_RESPONSE):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=posting_id,
        status=status,
        root_url="https://acme.myworkdayjobs.com/job/1",
    )


class _NotifyDecisionOnlySpy:
    """Exposes ONLY ``notify_decision`` — the real ``NotificationService``
    method used by every other decision-shaped emit site in the engine
    (``material_service.py``, ``final_approval_service.py``, etc).

    If ``send_scheduled_follow_ups`` regressed to calling a nonexistent
    ``.notify(...)`` again (the original dead-pipe bug, finding #1), that call
    would raise ``AttributeError`` on this spy — caught by the service's own
    ``try/except: continue`` — and every assertion below (calls recorded,
    ``sent`` populated, state transitioned) would fail exactly as it did
    before the fix.
    """

    def __init__(self):
        self.calls: list[dict] = []

    def notify_decision(self, decision_ref, *, title, body, deep_link=None):
        self.calls.append(
            {"decision_ref": decision_ref, "title": title, "body": body, "deep_link": deep_link}
        )
        return "handle"


@pytest.mark.unit
class TestFollowUpNotifyPipeAlive:
    """Finding #1: the pipe must actually deliver and drive state, not swallow."""

    def test_due_followup_is_emitted_appended_and_transitions_state(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting = _posting(cid)
        storage.postings.add(posting)
        app = _app(cid, posting.id, status=ApplicationState.AWAITING_RESPONSE)
        storage.applications.add(app)
        spy = _NotifyDecisionOnlySpy()
        service = PostSubmissionService(storage, notification_service=spy)

        fup = service.schedule_follow_up(
            app.id,
            template=FollowUpTemplate.CHECK_IN,
            delay_hours=-1,  # already due
            subject="Checking in on my application",
            body="I wanted to check in on the status of my application.",
        )

        sent = service.send_scheduled_follow_ups()

        # Was actually emitted (not swallowed by AttributeError) ...
        assert len(spy.calls) == 1
        # ... appended to the returned batch ...
        assert [f.id for f in sent] == [fup.id]
        # ... and the application transitioned AWAITING_RESPONSE -> FOLLOWING_UP.
        updated = storage.applications.get(app.id)
        assert updated.status == ApplicationState.FOLLOWING_UP

    def test_notify_decision_receives_the_correct_ref_body_and_deep_link(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting = _posting(cid)
        storage.postings.add(posting)
        app = _app(cid, posting.id)
        storage.applications.add(app)
        spy = _NotifyDecisionOnlySpy()
        service = PostSubmissionService(storage, notification_service=spy)

        fup = service.schedule_follow_up(
            app.id,
            template=FollowUpTemplate.CHECK_IN,
            delay_hours=-1,
            body="I wanted to check in on the status of my application.",
        )

        service.send_scheduled_follow_ups()

        call = spy.calls[0]
        assert call["decision_ref"] == str(fup.id)
        assert call["body"] == fup.body
        assert call["deep_link"] == f"/applications/{fup.application_id}"

    def test_no_due_followups_is_a_noop_and_never_calls_notify(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting = _posting(cid)
        storage.postings.add(posting)
        app = _app(cid, posting.id)
        storage.applications.add(app)
        spy = _NotifyDecisionOnlySpy()
        service = PostSubmissionService(storage, notification_service=spy)
        service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=999
        )  # not due yet

        sent = service.send_scheduled_follow_ups()

        assert sent == []
        assert spy.calls == []
        assert storage.applications.get(app.id).status == ApplicationState.AWAITING_RESPONSE


@pytest.mark.unit
class TestFollowUpNotifyPipeProductVoiceTitle:
    """Finding #53: the notification TITLE must be product-voice, not the raw
    follow-up thank-you/check-in text sent to the employer."""

    def test_title_is_not_the_raw_followup_subject_or_body(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting = _posting(cid, company="Acme Corp")
        storage.postings.add(posting)
        app = _app(cid, posting.id)
        storage.applications.add(app)
        spy = _NotifyDecisionOnlySpy()
        service = PostSubmissionService(storage, notification_service=spy)
        raw_subject = "Thank you for your time"
        raw_body = "Thank you for the opportunity to apply. I look forward to hearing about next steps."
        service.schedule_follow_up(
            app.id,
            template=FollowUpTemplate.THANK_YOU,
            delay_hours=-1,
            subject=raw_subject,
            body=raw_body,
        )

        service.send_scheduled_follow_ups()

        title = spy.calls[0]["title"]
        # This is the crux of #53: naively wiring the pipe (title=fup.subject)
        # would make the notification buzz "Thank you for your time" as if the
        # PRODUCT were thanking the user. That must never be the title again.
        assert title != raw_subject
        assert raw_body not in title

    def test_title_uses_product_voice_review_and_send_framing_with_company(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting = _posting(cid, company="Acme Corp")
        storage.postings.add(posting)
        app = _app(cid, posting.id)
        storage.applications.add(app)
        spy = _NotifyDecisionOnlySpy()
        service = PostSubmissionService(storage, notification_service=spy)
        service.schedule_follow_up(
            app.id,
            template=FollowUpTemplate.CHECK_IN,
            delay_hours=-1,
            subject="Checking in on my application",
            body="I wanted to check in on the status of my application.",
        )

        service.send_scheduled_follow_ups()

        title = spy.calls[0]["title"]
        assert "Acme Corp" in title
        assert "review & send" in title
        # The follow-up's actual employer-facing copy still travels in the body.
        assert spy.calls[0]["body"] == "I wanted to check in on the status of my application."

    def test_title_falls_back_to_generic_label_when_company_unresolvable(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        # No posting stored at all -- the company lookup must degrade, never raise.
        app = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=None,
            status=ApplicationState.AWAITING_RESPONSE,
            root_url="https://acme.myworkdayjobs.com/job/1",
        )
        storage.applications.add(app)
        spy = _NotifyDecisionOnlySpy()
        service = PostSubmissionService(storage, notification_service=spy)
        service.schedule_follow_up(
            app.id, template=FollowUpTemplate.CHECK_IN, delay_hours=-1
        )

        service.send_scheduled_follow_ups()

        title = spy.calls[0]["title"]
        assert "your application" in title
        assert "review & send" in title
