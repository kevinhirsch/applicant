"""Decline-reason rollup: learning-story backlog (PRODUCT_EXHAUSTIVE_AUDIT.md).

The audit's learning-story backlog asks for "narrated insights (not stat dumps)"
and "decline-reasons rolled up". Decline feedback is MANDATORY
(FR-FB-1: ``DigestService.decline`` rejects a blank ``feedback_text``) and
``LearningService.ingest_decline_feedback`` already tokenizes it into
``feature_stats`` under a ``feedback:{token}`` key, counted against a
``{token}:decline`` label, purely to bias future scoring (FR-LEARN-1/3) -- that
signal was write-only: nothing ever read it back for the user.

These tests prove the NEW read-only rollup (``LearningService.decline_reasons``)
surfaces that SAME already-persisted signal as a plain word-frequency list: no new
capture point, no invented semantic taxonomy, no LLM, and it is wired into
``build_summary`` (the exact read-model ``GET /api/admin/learning/{id}`` returns
and the Results front-door proxy forwards).
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.application.services.learning_service import LearningService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId, JobPostingId, new_id


def _wire():
    storage = InMemoryStorage()
    notifier = AppriseNotifier()  # offline default: no real network
    learning = LearningService(storage, LocalEmbedding())
    digest = DigestService(storage, notifier, learning=learning)
    return storage, digest, learning


def _campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    return cid


def _posting(storage, campaign_id, *, source_key: str = "linkedin") -> JobPostingId:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=campaign_id,
            title="Engineer",
            company="Acme",
            source_url="https://acme.example/job",
            source_key=source_key,
        )
    )
    return pid


# --- LearningService.decline_reasons: pure aggregation ---------------------


@pytest.mark.unit
def test_decline_reasons_empty_for_fresh_campaign_not_fabricated():
    storage, _digest, learning = _wire()
    cid = _campaign(storage)
    model = learning.load_model(cid)
    assert learning.decline_reasons(model) == []


@pytest.mark.unit
def test_decline_reasons_counts_words_from_real_decline_feedback():
    storage, digest, learning = _wire()
    cid = _campaign(storage)
    p1 = _posting(storage, cid)
    p2 = _posting(storage, cid)
    p3 = _posting(storage, cid)

    digest.decline(p1, feedback_text="Requires onsite five days a week")
    digest.decline(p2, feedback_text="Fully onsite with no remote option")
    digest.decline(p3, feedback_text="Salary offered was too low")

    model = learning.load_model(cid)
    # A generous limit here so the assertion below is about ranking/counting, not
    # about the default top-N cut (covered separately by the limit test).
    reasons = learning.decline_reasons(model, limit=20)
    by_word = {r["reason"]: r["count"] for r in reasons}
    assert by_word.get("onsite") == 2
    assert by_word.get("salary") == 1
    # Highest count first, deterministic order.
    assert reasons[0]["reason"] == "onsite"
    assert reasons[0]["count"] == 2


@pytest.mark.unit
def test_decline_reasons_filters_common_connector_words_at_read_time():
    """Stopwords are folded into feature_stats (scoring still uses them), but the
    user-facing rollup filters them so the summary is not dominated by words that
    say nothing about WHY a role was declined."""
    storage, digest, learning = _wire()
    cid = _campaign(storage)
    p1 = _posting(storage, cid)
    digest.decline(p1, feedback_text="I don't want this role because it requires onsite work")

    model = learning.load_model(cid)
    # The underlying signal is untouched -- scoring still sees the raw tokens.
    assert "feedback:this" in model.feature_stats
    assert "feedback:onsite" in model.feature_stats

    reasons = learning.decline_reasons(model)
    words = {r["reason"] for r in reasons}
    assert "this" not in words
    assert "role" not in words
    assert "because" not in words
    assert "want" not in words
    assert "onsite" in words


@pytest.mark.unit
def test_decline_reasons_respects_limit():
    storage, digest, learning = _wire()
    cid = _campaign(storage)
    for word in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"):
        p = _posting(storage, cid)
        digest.decline(p, feedback_text=word)

    model = learning.load_model(cid)
    assert len(learning.decline_reasons(model, limit=3)) == 3
    assert len(learning.decline_reasons(model, limit=100)) == 7


# --- build_summary: the read-model the Results front-door surfaces ---------


@pytest.mark.unit
def test_build_summary_decline_reasons_empty_when_nothing_declined_yet():
    storage, _digest, learning = _wire()
    cid = _campaign(storage)
    summary = learning.build_summary(cid)
    assert summary["decline_reasons"] == []


@pytest.mark.unit
def test_build_summary_surfaces_decline_reasons_after_a_real_decline():
    storage, digest, learning = _wire()
    cid = _campaign(storage)
    p1 = _posting(storage, cid)
    digest.decline(p1, feedback_text="Compensation below target range")

    summary = learning.build_summary(cid)
    reasons = {r["reason"]: r["count"] for r in summary["decline_reasons"]}
    assert reasons.get("compensation") == 1
    assert all(isinstance(r["count"], int) for r in summary["decline_reasons"])
    # White-label: never leaks FR-jargon into the read-model.
    assert "FR-" not in str(summary)
