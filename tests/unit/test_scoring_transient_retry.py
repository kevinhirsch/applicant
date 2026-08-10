"""P0 durability fix: a TRANSIENT LLM failure must not permanently bury a good
posting below the viability threshold.

Live symptom this guards against: ``_base_score`` degrades to the local embedding
signal on ANY LLM exception (timeout/transport/parse); embedding similarity almost
never clears the viability threshold, and the old code persisted that degraded
value unconditionally via ``_persist_score``. Once persisted, ``viability_score``
is no longer NULL, so ``agent_loop._unscored_postings`` (backed by
``list_unscored_for_campaign``, which filters on ``viability_score IS NULL``)
never revisits the posting — a one-off LLM hiccup (e.g. a cold-start vLLM call
exceeding the HTTP timeout) permanently sinks the posting with zero retries.

These tests prove the fix in ``ScoringService._persist_or_defer``:

* an LLM-configured-but-failing call leaves the posting UNSCORED (retryable) —
  ``list_unscored_for_campaign`` still returns it, and no "scored" event fires;
* the two legitimate cases (LLM success; no LLM configured at all) persist
  immediately, byte-identical to before;
* a bounded retry budget (``SCORING_MAX_TRANSIENT_RETRIES`` /
  ``max_transient_retries``) eventually accepts the degraded value so a
  persistently-failing posting still makes progress instead of looping forever;
* ``score_for_digest`` shows the transient in-memory value for immediate display
  without durably poisoning the persisted score.
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.events import event_bus
from applicant.core.ids import CampaignId, JobPostingId, new_id


class _FailingLLM:
    """Configured, but every ``complete()`` call raises (simulated timeout)."""

    def is_configured(self) -> bool:
        return True

    def complete(self, *a, **k):
        raise TimeoutError("simulated vLLM cold-start timeout")


class _NotConfiguredLLM:
    def is_configured(self) -> bool:
        return False

    def complete(self, *a, **k):  # pragma: no cover - must never be called
        raise AssertionError("complete() must not be called when unconfigured")


class _SucceedingLLM:
    def is_configured(self) -> bool:
        return True

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        from applicant.ports.driven.llm import LLMResult

        return LLMResult(
            text='{"score": 85, "rationale": "strong fit"}', tier=1, model="fake"
        )


def _posting(cid: CampaignId) -> JobPosting:
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        source_url="https://example.com/jobs/1",
        title="Senior Backend Engineer",
        company="Acme",
        description="Build Python services with Django and Postgres.",
    )


def _criteria(cid: CampaignId) -> SearchCriteria:
    return SearchCriteria(
        campaign_id=cid, titles=("Backend Engineer",), keywords=("Python", "Django")
    )


@pytest.mark.unit
class TestTransientLlmFailureLeavesPostingRetryable:
    def test_degraded_fallback_is_not_persisted_when_llm_configured(self):
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, _FailingLLM(), LocalEmbedding())
        scoring = svc.score_viability(posting.id, _criteria(cid))

        # The in-memory return value still carries the (degraded) embedding score
        # for any immediate caller that wants it...
        assert scoring.degraded is True
        # ...but nothing was durably persisted: the posting stays NULL/unscored.
        stored = storage.postings.get(posting.id)
        assert stored.viability_score is None

    def test_unscored_postings_still_returns_it_for_retry(self):
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, _FailingLLM(), LocalEmbedding())
        svc.score_viability(posting.id, _criteria(cid))

        unscored_ids = {p.id for p in storage.postings.list_unscored_for_campaign(cid)}
        assert posting.id in unscored_ids

    def test_no_scored_event_fires_while_deferred(self, monkeypatch):
        """``ScoringService`` imports the PROCESS singleton ``event_bus`` at module
        load time, so intercepting it means patching that singleton's ``emit`` in
        place (monkeypatch auto-reverts) rather than swapping the module attribute
        (which the already-bound reference in scoring_service.py would not see).
        """
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        emitted: list = []
        monkeypatch.setattr(event_bus, "emit", lambda ev: emitted.append(ev))

        svc = ScoringService(storage, _FailingLLM(), LocalEmbedding())
        svc.score_viability(posting.id, _criteria(cid))

        assert emitted == [], "a deferred/unscored posting must not emit ViabilityScored"

    def test_scored_event_fires_once_persisted(self, monkeypatch):
        """Sanity companion: the legitimate LLM-success path still fires the event
        (the gating in ``score_viability`` must not silence real scores)."""
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        emitted: list = []
        monkeypatch.setattr(event_bus, "emit", lambda ev: emitted.append(ev))

        svc = ScoringService(storage, _SucceedingLLM(), LocalEmbedding())
        svc.score_viability(posting.id, _criteria(cid))

        assert len(emitted) == 1
        assert emitted[0].posting_id == posting.id


@pytest.mark.unit
class TestLegitimateCasesStillPersistImmediately:
    def test_llm_success_persists_immediately(self):
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, _SucceedingLLM(), LocalEmbedding())
        scoring = svc.score_viability(posting.id, _criteria(cid))

        assert scoring.degraded is False
        stored = storage.postings.get(posting.id)
        assert stored.viability_score == pytest.approx(0.85)

    def test_no_llm_configured_persists_embedding_score_immediately(self):
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, _NotConfiguredLLM(), LocalEmbedding())
        scoring = svc.score_viability(posting.id, _criteria(cid))

        assert scoring.degraded is False
        stored = storage.postings.get(posting.id)
        assert stored.viability_score == pytest.approx(scoring.score)
        assert stored.viability_score is not None


@pytest.mark.unit
class TestBoundedRetryValve:
    def test_repeated_failures_eventually_accept_the_degraded_score(self):
        """With ``max_transient_retries=3`` (matching the documented default), the
        valve defers the first two consecutive failures and accepts the degraded
        value on the 3rd — "after N consecutive transient failures ... fall back"."""
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(
            storage, _FailingLLM(), LocalEmbedding(), max_transient_retries=3
        )
        criteria = _criteria(cid)

        # Attempts 1 and 2: deferred (still unscored) — under the budget of 3.
        svc.score_viability(posting.id, criteria)
        assert storage.postings.get(posting.id).viability_score is None
        svc.score_viability(posting.id, criteria)
        assert storage.postings.get(posting.id).viability_score is None

        # Attempt 3: the 3rd consecutive failure spends the budget; the resilience
        # valve accepts the degraded value so the posting isn't stuck forever.
        final = svc.score_viability(posting.id, criteria)
        stored = storage.postings.get(posting.id)
        assert stored.viability_score == pytest.approx(final.score)
        assert stored.viability_score is not None

    def test_env_override_is_honored(self, monkeypatch):
        """A tighter ``SCORING_MAX_TRANSIENT_RETRIES=2`` spends the budget sooner
        than the default of 3 — proving the env var is actually read (fresh, no
        restart needed) rather than only the constructor kwarg."""
        monkeypatch.setenv("SCORING_MAX_TRANSIENT_RETRIES", "2")
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, _FailingLLM(), LocalEmbedding())
        criteria = _criteria(cid)

        svc.score_viability(posting.id, criteria)  # 1st failure: within budget
        assert storage.postings.get(posting.id).viability_score is None

        svc.score_viability(posting.id, criteria)  # 2nd failure: budget spent
        assert storage.postings.get(posting.id).viability_score is not None


@pytest.mark.unit
class TestScoreForDigestDeferral:
    def test_score_for_digest_shows_transient_value_without_persisting_it(self):
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, _FailingLLM(), LocalEmbedding())
        scoring = svc.score_for_digest(posting, _criteria(cid))

        # Shown in-memory for the caller...
        assert scoring.degraded is True
        # ...but not durably poisoned.
        assert storage.postings.get(posting.id).viability_score is None
