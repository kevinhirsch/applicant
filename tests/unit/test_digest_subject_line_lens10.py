"""Lens 10 finding #30: the digest email subject must be informative.

Before the fix, ``render_email``'s subject was always the literal string
"Your daily digest" (with only the empty-day case carrying a variant) — ten of
these in an inbox were indistinguishable. This pins the fix: the subject now
degrades gracefully using data ``render_email`` already has in hand (row
count + the highest-scored row's title/company) — no re-query, no new
dependency.
"""

from __future__ import annotations

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.viability_scoring import ViabilityScoring
from applicant.core.ids import CampaignId, JobPostingId, new_id


class _FakeScoring:
    """Deterministic stand-in for ScoringService: score is keyed off the
    posting's own ``viability_score`` field (set explicitly per test row) so
    the "top match" is pinned without depending on real embedding similarity.
    """

    def score_for_digest(self, posting, criteria=None):
        return self.score_posting(posting, criteria)

    def score_posting(self, posting, criteria=None):
        score = float(getattr(posting, "viability_score", None) or 0.0) / 100.0
        return ViabilityScoring(posting_id=posting.id, score=score, rationale="fits well")

    def is_viable(self, scoring):
        return True


def _wire():
    storage = InMemoryStorage()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    digest = DigestService(storage, notifier, _FakeScoring())
    return storage, digest


def _add_posting(storage, cid, *, title, company, score):
    storage.postings.add(
        JobPosting(
            id=JobPostingId(new_id()),
            campaign_id=cid,
            title=title,
            company=company,
            source_url="https://example.test/job",
            work_mode="remote",
            description="",
            source_key="jobspy:indeed",
            viability_score=score,
        )
    )


def test_subject_names_count_and_top_match_for_multiple_matches():
    storage, digest = _wire()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    # Highest score is the second one added — the subject must still surface it
    # (proves the top-match pick is by SCORE, not insertion order).
    _add_posting(storage, cid, title="Backend Engineer", company="Widgets Inc", score=40)
    _add_posting(storage, cid, title="Senior SRE", company="Acme", score=95)
    _add_posting(storage, cid, title="DevOps Engineer", company="Contoso", score=60)
    storage.commit()

    email = digest.render_email(cid)

    assert "3 new matches" in email["subject"]
    assert "top: Senior SRE at Acme" in email["subject"]
    assert email["subject"].startswith("Your daily digest")


def test_subject_uses_singular_grammar_for_one_match():
    storage, digest = _wire()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    _add_posting(storage, cid, title="Staff Engineer", company="Initech", score=70)
    storage.commit()

    email = digest.render_email(cid)

    assert "1 new match" in email["subject"]
    assert "1 new matches" not in email["subject"]
    assert "top: Staff Engineer at Initech" in email["subject"]


def test_subject_keeps_existing_empty_day_copy_for_zero_matches():
    storage, digest = _wire()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()

    email = digest.render_email(cid)

    assert email["subject"] == "Daily digest — no new matches today"
