"""P1-11 — Easy Apply: detect & tag.

Discovery detects Easy-Apply-style postings server-side and tags them
(``JobPosting.easy_apply``); the tag then flows to the digest (per-role
channel) and the tracker board rows. Detection ONLY — nothing here drives
automation or a login (the DoD's zero-risk requirement): the tag is computed
purely from the scraped row that discovery already had.

Hermetic: InMemoryStorage, no DB/network/LLM.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.jobspy_searxng import (
    SampleSource,
    detect_easy_apply,
    normalize_row,
)
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.application.services.post_submission_service import PostSubmissionService
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState

CID = CampaignId(new_id())


# --- detection (server-side, pure) ------------------------------------------


@pytest.mark.unit
class TestDetectEasyApply:
    def test_explicit_truthy_attribute_tags(self):
        assert detect_easy_apply({"easy_apply": True}) is True
        assert detect_easy_apply({"easy_apply": "true"}) is True
        assert detect_easy_apply({"easy_apply": "1"}) is True

    def test_explicit_false_or_absent_does_not_tag(self):
        assert detect_easy_apply({"easy_apply": False}) is False
        assert detect_easy_apply({"easy_apply": "false"}) is False
        assert detect_easy_apply({}) is False
        # An unrecognized junk value (e.g. a scraped NaN) never tags.
        assert detect_easy_apply({"easy_apply": "nan"}) is False

    def test_linkedin_hosted_apply_flow_tags(self):
        # Detail page fetched (description present) and NO external apply URL
        # -> the apply flow is hosted on LinkedIn (its built-in quick apply).
        raw = {
            "title": "Staff Engineer",
            "job_url": "https://www.linkedin.com/jobs/view/12345",
            "job_url_direct": None,
            "description": "Real fetched description.",
        }
        assert detect_easy_apply(raw) is True

    def test_linkedin_with_external_apply_url_does_not_tag(self):
        raw = {
            "job_url": "https://www.linkedin.com/jobs/view/12345",
            "job_url_direct": "https://acme.example/careers/apply/1",
            "description": "Real fetched description.",
        }
        assert detect_easy_apply(raw) is False

    def test_linkedin_without_fetched_detail_stays_untagged(self):
        # H-series honesty: a row whose detail page was never fetched (pandas
        # NaN description + NaN job_url_direct) proves nothing — never guess.
        raw = {
            "job_url": "https://www.linkedin.com/jobs/view/12345",
            "job_url_direct": float("nan"),
            "description": float("nan"),
        }
        assert detect_easy_apply(raw) is False

    def test_non_linkedin_row_without_attribute_stays_untagged(self):
        raw = {
            "job_url": "https://indeed.test/jobs/1",
            "job_url_direct": None,
            "description": "A fetched description.",
        }
        assert detect_easy_apply(raw) is False


@pytest.mark.unit
class TestNormalizeRowTagsPosting:
    def test_normalize_row_sets_easy_apply(self):
        raw = {
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "source_url": "https://www.linkedin.com/jobs/view/999",
            "easy_apply": True,
        }
        posting = normalize_row(raw, CID, "jobspy:linkedin")
        assert posting is not None
        assert posting.easy_apply is True

    def test_normalize_row_defaults_untagged(self):
        raw = {
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "source_url": "https://indeed.test/jobs/1",
        }
        posting = normalize_row(raw, CID, "jobspy:indeed")
        assert posting is not None
        assert posting.easy_apply is False

    def test_sample_source_passes_the_attribute_through(self):
        src = SampleSource(
            postings=[
                {
                    "title": "Senior Backend Engineer",
                    "company": "Acme",
                    "source_url": "https://example.test/jobs/1",
                    "easy_apply": True,
                }
            ]
        )
        criteria = SearchCriteria(campaign_id=CID, titles=("engineer",), keywords=())
        postings = src.fetch(CID, criteria)
        assert len(postings) == 1
        assert postings[0].easy_apply is True


# --- digest: the channel shows per role --------------------------------------


def _posting(cid, *, easy_apply=False, url="https://example.test/jobs/1"):
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Backend Engineer",
        company="Acme",
        source_url=url,
        work_mode="remote",
        description="python backend",
        source_key="jobspy:linkedin",
        easy_apply=easy_apply,
    )


@pytest.mark.unit
class TestDigestShowsChannel:
    def test_digest_row_carries_easy_apply(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        tagged = _posting(cid, easy_apply=True)
        plain = _posting(cid, url="https://example.test/jobs/2")
        storage.postings.add(tagged)
        storage.postings.add(plain)
        storage.commit()
        digest = DigestService(storage, notification=None)

        payload = digest.build_digest_payload(cid, None)

        by_id = {r["posting_id"]: r for r in payload["rows"]}
        assert by_id[tagged.id]["easy_apply"] is True
        assert by_id[plain.id]["easy_apply"] is False

    def test_digest_email_meta_line_shows_the_channel(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        storage.postings.add(_posting(cid, easy_apply=True))
        storage.commit()
        digest = DigestService(storage, notification=None)

        html = digest.render_email(cid, None)["html"]

        assert "Easy Apply" in html

    def test_untagged_digest_email_omits_the_channel(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        storage.postings.add(_posting(cid))
        storage.commit()
        digest = DigestService(storage, notification=None)

        html = digest.render_email(cid, None)["html"]

        assert "Easy Apply" not in html


# --- tracker: the tag rides the board row -------------------------------------


@pytest.mark.unit
class TestTrackerRowCarriesTag:
    def test_tracker_row_easy_apply_from_posting(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        posting = _posting(cid, easy_apply=True)
        storage.postings.add(posting)
        app = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=posting.id,
            status=ApplicationState.AWAITING_RESPONSE,
        )
        storage.applications.add(app)
        storage.commit()
        service = PostSubmissionService(storage)

        rows = service.list_tracker_rows(cid)

        row = next(r for r in rows if r["application_id"] == str(app.id))
        assert row["easy_apply"] is True

    def test_tracker_row_untagged_when_posting_missing(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        app = Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),  # dangling — no such posting
            status=ApplicationState.AWAITING_RESPONSE,
        )
        storage.applications.add(app)
        storage.commit()
        service = PostSubmissionService(storage)

        rows = service.list_tracker_rows(cid)

        row = next(r for r in rows if r["application_id"] == str(app.id))
        assert row["easy_apply"] is False


# --- demo seed: the surface is visible in demo mode ---------------------------


@pytest.mark.unit
def test_demo_seed_tags_exactly_one_posting():
    from applicant.application.services.dev_seed import build_demo_postings

    postings = build_demo_postings()
    tagged = [p for p in postings if p.easy_apply]
    assert len(tagged) == 1
