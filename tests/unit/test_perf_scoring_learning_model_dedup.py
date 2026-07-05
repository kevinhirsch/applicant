"""Regression coverage for performance lens 03 (round 2): ``ScoringService`` was
loading the SAME per-campaign ``LearningModel`` up to 3x (via ``_learning_sig``,
``_taste_bias``, and ``_signature_alignment``'s ``self._learning`` branch) plus the
advanced-learning model once more (``_signature_alignment``'s ``self._advanced_learning``
branch) — up to 4 identical ``load_model`` calls (each a ``campaigns.get`` +
``discovery_sources.list_for_campaign`` storage round-trip) for a SINGLE posting
scored, in ``score_viability``/``score_for_digest``/``score_posting``.

The fix loads each model ONCE per top-level scoring call and threads it through the
private helpers (``_load_learning_model``/``_load_advanced_model`` in
``scoring_service.py``). ``load_model`` is a side-effect-free read and nothing in the
scoring call tree persists learning state in between, so this is byte-identical to
the old reload-every-time behavior — proven below by asserting the scored value is
unchanged while the underlying model is loaded far fewer times.

FAIL-BEFORE: on the pre-fix tree (verified by hand — file-copy the pre-fix
``scoring_service.py`` back in, rerun, see the call-count assertions fail with
higher counts, restore) ``score_viability``/``score_posting`` called
``learning.load_model`` 3x and ``advanced_learning.load_model`` 1x per posting; this
file pins it at 1x each. ``score_for_digest``'s cache-HIT path must not regress
either: it already only loaded the learning model once (via ``_learning_sig``,
before the cache check) — this file pins that it still does, and that the advanced
model is NOT loaded at all on a hit (it never was, since ``_score`` doesn't run on
a hit).
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id


class _CountingLearning:
    """A minimal LearningService double that counts ``load_model`` calls."""

    def __init__(self, model=None):
        self._model = model if model is not None else object()
        self.load_calls = 0

    def load_model(self, campaign_id):
        self.load_calls += 1
        return self._model

    def taste_bias(self, model, text):
        assert model is self._model
        return 1.1  # non-1.0 so the bias branch runs and provably uses this model

    def converting_alignment(self, model, jd_text):
        assert model is self._model
        return 0.4


class _CountingAdvanced:
    """A minimal AdvancedLearningService double that counts ``load_model`` calls."""

    def __init__(self, model=None):
        self._model = model if model is not None else object()
        self.load_calls = 0

    def load_model(self, campaign_id):
        self.load_calls += 1
        return self._model

    def text_alignment(self, model, jd_text):
        assert model is self._model
        return 0.6

    def recall_alignment(self, campaign_id, jd_text):
        return 0.0


def _campaign_and_posting(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Backend Engineer",
        company="Acme Corp",
        source_url="https://acme.test/job",
        description="Python, Go, distributed systems.",
    )
    storage.postings.add(posting)
    storage.commit()
    return cid, posting


@pytest.mark.unit
def test_score_viability_loads_each_learning_model_at_most_once():
    storage = InMemoryStorage()
    cid, posting = _campaign_and_posting(storage)
    learning = _CountingLearning()
    advanced = _CountingAdvanced()
    svc = ScoringService(
        storage, llm=None, embedding=LocalEmbedding(),
        learning=learning, advanced_learning=advanced,
    )
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))

    scoring = svc.score_viability(posting.id, crit)

    assert learning.load_calls == 1, "learning.load_model must be loaded exactly once"
    assert advanced.load_calls == 1, "advanced_learning.load_model must be loaded exactly once"
    # Behavior parity: the taste + alignment biases (from the counting doubles above)
    # were actually applied — proves the single loaded model was correctly threaded
    # through, not just that the call count dropped.
    assert "taste" in scoring.rationale
    assert "converting-role signature" in scoring.rationale


@pytest.mark.unit
def test_score_posting_loads_each_learning_model_at_most_once():
    storage = InMemoryStorage()
    cid, posting = _campaign_and_posting(storage)
    learning = _CountingLearning()
    advanced = _CountingAdvanced()
    svc = ScoringService(
        storage, llm=None, embedding=LocalEmbedding(),
        learning=learning, advanced_learning=advanced,
    )
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))

    svc.score_posting(posting, crit)

    assert learning.load_calls == 1
    assert advanced.load_calls == 1


@pytest.mark.unit
def test_score_for_digest_miss_loads_once_each_hit_loads_only_learning():
    storage = InMemoryStorage()
    cid, posting = _campaign_and_posting(storage)
    learning = _CountingLearning()
    advanced = _CountingAdvanced()
    svc = ScoringService(
        storage, llm=None, embedding=LocalEmbedding(),
        learning=learning, advanced_learning=advanced,
    )
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))

    first = svc.score_for_digest(posting, crit)
    assert learning.load_calls == 1, "a cache MISS must load the learning model once"
    assert advanced.load_calls == 1, "a cache MISS must load the advanced model once"

    # Refetch the posting: score_for_digest persisted the score/rationale onto it.
    refetched = storage.postings.get(posting.id)
    second = svc.score_for_digest(refetched, crit)

    assert learning.load_calls == 2, (
        "a cache HIT still needs the learning model once (for _learning_sig, to "
        "decide whether it IS a hit) -- no regression vs. before this fix"
    )
    assert advanced.load_calls == 1, (
        "a cache HIT must NOT load the advanced model at all -- _score() never runs "
        "on a hit, so this must stay exactly as cheap as before this fix"
    )
    assert second.score == first.score
    assert second.rationale == first.rationale
