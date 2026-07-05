"""Digest email BODY styling (audit lens 10 #31).

Pins the fix for: no preheader, no mobile styling, a raw ``border='1'`` table —
the daily digest email was unstyled and unreadable at phone width. ``render_email``
now emits a hidden preheader (preview-text) span plus an inline-styled,
single-column card list instead of the bare multi-column grid table. This lane
only asserts the BODY; the subject line is covered elsewhere and left untouched.
"""

from __future__ import annotations

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id


def _wire():
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    digest = DigestService(storage, AppriseNotifier(), scoring)
    return storage, digest


def _seed(storage, *, with_posting=True):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    if with_posting:
        storage.postings.add(
            JobPosting(
                id=JobPostingId(new_id()),
                campaign_id=cid,
                title="Senior Python Engineer",
                company="Acme",
                source_url="https://acme.test/job",
                work_mode="remote",
                description="python fastapi",
                source_key="jobspy:indeed",
            )
        )
    storage.commit()
    return cid


def test_email_body_has_hidden_preheader_span():
    """A hidden preview-text span is present so the inbox list shows a real
    summary instead of raw markup (lens 10 #31)."""
    storage, digest = _wire()
    cid = _seed(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    html_ = digest.render_email(cid, crit)["html"]
    assert "display:none" in html_
    assert "mso-hide:all" in html_
    # The preheader mentions the match count, not just static boilerplate.
    assert "1 new role match" in html_


def test_email_body_uses_inline_styles_not_bare_border_table():
    """The old ``<table border='1' cellpadding='6'>`` raw grid must be gone —
    replaced by inline ``style=`` attributes (mail clients strip <style> blocks
    and don't support flex/grid, so inline style= is the only robust option)."""
    storage, digest = _wire()
    cid = _seed(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    html_ = digest.render_email(cid, crit)["html"]
    assert "border='1'" not in html_
    assert "cellpadding='6'" not in html_
    assert "style='" in html_
    # No <style> block — mail clients strip it; the fix must be inline.
    assert "<style" not in html_


def test_email_body_still_lists_title_company_and_link():
    """Restyling must not drop any of the per-row data the email carries."""
    storage, digest = _wire()
    cid = _seed(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    html_ = digest.render_email(cid, crit)["html"]
    assert "Senior Python Engineer" in html_
    assert "Acme" in html_
    assert "https://acme.test/job" in html_
    assert "remote" in html_
    # Still exactly one row-card for the one viable posting (bare <tr><td>
    # wraps each card; the perf-cap test elsewhere counts on this literal
    # shape staying stable).
    assert html_.count("<tr><td>") == 1


def test_empty_day_variant_preserved_with_preheader():
    """The empty-day note path (FR-DIG-6) still renders, now with its own
    preheader carrying the same note text."""
    storage, digest = _wire()
    cid = _seed(storage, with_posting=False)
    email = digest.render_email(cid)
    html_ = email["html"]
    assert "no new matches" in email["subject"].lower()
    assert "<h1>Your daily digest</h1>" in html_
    assert "No new viable roles today" in html_
    assert "display:none" in html_  # preheader present on the empty-day path too
    assert "<tr><td>" not in html_  # no role cards to render


def test_email_body_still_starts_with_h1_heading():
    """Preserve the existing heading-first contract other tests rely on."""
    storage, digest = _wire()
    cid = _seed(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    html_ = digest.render_email(cid, crit)["html"]
    assert html_.startswith("<h1>")
