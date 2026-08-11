"""Model-resiliency (Kevin's explicit requirement): viability scoring must not
degrade straight to the weak local-embedding signal on a local-tier failure.

Symptom this closes: ``ScoringService._base_score`` scores with the LLM ladder's
tier 1 (local qwen, cheap default) via ``start_tier=1``. The local model is SLOW
and intermittently 500s / times out on the large scoring prompt. On ANY failure
the code used to degrade straight to the local embedding signal — a weak,
zero-token lexical-overlap fallback that produces wrong scores for real
in-domain roles.

The fix: when the tier-1 (local) call fails/times-out/returns no usable score,
``_base_score`` makes ONE deterministic escalation to the configured DeepSeek
cloud fallback tier — the SAME rung ``material_service.py`` already relies on
for drafting (``config.py``'s ``LLM_FALLBACK_*`` settings, appended as the last
ladder rung by ``SetupService.build_ladder``) — via ``_fallback_start_tier()``
duck-typing the shared adapter's ``.ladder`` length. Only when BOTH the local
AND the fallback attempts fail does it fall back to the embedding signal.

These tests use fakes for the LLM tiers (no network) and assert:

* local failure -> the fallback tier is actually called and its real score wins
  (not the embedding signal);
* local failure AND fallback failure -> degrades to the embedding signal without
  crashing;
* local success -> the fallback tier is NEVER called (cost guard: DeepSeek is a
  paid escalation, not a default);
* a local reply that parses but carries no usable ``score`` field (the case the
  adapter's own tier-ladder climb can't see, since ``complete()`` already
  "succeeded") ALSO escalates to the fallback, closing the specific gap generic
  HTTP-failure climbing doesn't cover;
* when no fallback tier is configured at all (a single-tier ladder, or an LLM
  double exposing no ``.ladder``), a local failure degrades directly to the
  embedding signal WITHOUT a wasted second call to the same failing local tier.
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.ports.driven.llm import LLMResult


class _TieredFakeLLM:
    """Configured fake LLM whose behavior differs by ``start_tier``.

    ``tier1``/``tier2`` are zero-arg callables that either return an
    ``LLMResult`` or raise (simulating a timeout/500/transport failure).
    ``tier_count`` drives ``ScoringService._fallback_start_tier()`` via the
    duck-typed ``.ladder`` attribute (mirrors ``WedgeDetectingLLM``'s own
    ``_tier_count`` pattern) — 1 means "no fallback configured", 2 means "the
    DeepSeek fallback is the second rung", exactly like the real ladder
    ``SetupService.build_ladder`` builds.
    """

    def __init__(self, *, tier1, tier2=None, tier_count=2):
        self._tier1 = tier1
        self._tier2 = tier2
        self._tier_count = tier_count
        self.calls: list[int] = []

    def is_configured(self) -> bool:
        return True

    @property
    def ladder(self):
        # Only needs __len__ for the duck-typed check; a plain list is enough.
        return list(range(self._tier_count))

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        self.calls.append(start_tier)
        if start_tier == 1:
            return self._tier1()
        assert self._tier2 is not None, "tier2 called but not scripted"
        return self._tier2()


class _NoLadderFailingLLM:
    """Configured, failing, and exposes NO ``.ladder`` at all (plain double).

    Proves the escalation guard degrades gracefully (no AttributeError) when
    the wired LLM object doesn't even advertise a ladder — same defensive
    posture as ``WedgeDetectingLLM``'s ``getattr(..., "ladder", None)`` duck
    typing.
    """

    def is_configured(self) -> bool:
        return True

    def complete(self, *a, **k):
        raise TimeoutError("simulated local timeout, no ladder attribute")


def _posting(cid: CampaignId) -> JobPosting:
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        source_url="https://example.com/jobs/1",
        # NOT "Senior Backend Engineer" -- role_domain_fit's gate is now an
        # ALLOWLIST (round 2 of the miscalibration fix): the title must
        # plainly match an in-domain role family or it short-circuits
        # before the LLM is ever called, regardless of whether it also
        # names a KNOWN off-domain family. Use the same in-domain title the
        # transient-retry/fallback-tier test suites rely on.
        title="Senior Delivery Manager",
        company="Acme",
        description="Build Python services with Django and Postgres.",
    )


def _criteria(cid: CampaignId) -> SearchCriteria:
    return SearchCriteria(
        campaign_id=cid, titles=("Backend Engineer",), keywords=("Python", "Django")
    )


def _score_result(score: int, rationale: str, *, tier: int) -> LLMResult:
    return LLMResult(
        text=f'{{"score": {score}, "rationale": "{rationale}"}}',
        tier=tier,
        model="fake",
    )


@pytest.mark.unit
class TestLocalFailureEscalatesToDeepSeekFallback:
    def test_local_failure_escalates_and_returns_real_deepseek_score(self):
        llm = _TieredFakeLLM(
            tier1=lambda: (_ for _ in ()).throw(TimeoutError("local vLLM timeout")),
            tier2=lambda: _score_result(88, "great fit via deepseek", tier=2),
        )
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, llm, LocalEmbedding())
        scoring = svc.score_viability(posting.id, _criteria(cid))

        assert llm.calls == [1, 2], "must try local first, then escalate to the fallback"
        assert scoring.degraded is False, "a real fallback score is NOT a degraded score"
        assert scoring.score == pytest.approx(0.88)
        stored = storage.postings.get(posting.id)
        assert stored.viability_score == pytest.approx(0.88)

    def test_local_reply_with_no_usable_score_also_escalates(self):
        """The gap generic HTTP-failure ladder-climbing can't see: tier 1
        answers 200 OK but the JSON carries no ``score`` field — ``complete()``
        already "succeeded" so the adapter never climbs on its own. The
        explicit second attempt in ``_base_score`` must still reach the
        fallback tier."""
        llm = _TieredFakeLLM(
            tier1=lambda: LLMResult(text="not valid json at all", tier=1, model="fake"),
            tier2=lambda: _score_result(75, "solid fit via deepseek", tier=2),
        )
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, llm, LocalEmbedding())
        scoring = svc.score_viability(posting.id, _criteria(cid))

        assert llm.calls == [1, 2]
        assert scoring.degraded is False
        assert scoring.score == pytest.approx(0.75)


@pytest.mark.unit
class TestBothTiersFailingDegradesToEmbedding:
    def test_local_and_deepseek_both_failing_degrades_without_crashing(self):
        llm = _TieredFakeLLM(
            tier1=lambda: (_ for _ in ()).throw(TimeoutError("local vLLM timeout")),
            tier2=lambda: (_ for _ in ()).throw(ConnectionError("deepseek unreachable")),
        )
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, llm, LocalEmbedding())
        # Should not raise.
        scoring = svc.score_viability(posting.id, _criteria(cid))

        assert llm.calls == [1, 2], "both tiers must actually be attempted"
        assert scoring.degraded is True
        assert 0.0 <= scoring.score <= 1.0
        # The degraded (embedding) value is NOT persisted immediately -- the
        # existing P0 transient-retry guard defers it for retry, exactly as
        # before this change (byte-identical downstream behavior).
        assert storage.postings.get(posting.id).viability_score is None


@pytest.mark.unit
class TestLocalSuccessNeverCallsDeepSeek:
    def test_local_success_skips_the_fallback_call_entirely(self):
        llm = _TieredFakeLLM(
            tier1=lambda: _score_result(85, "strong fit locally", tier=1),
            tier2=lambda: (_ for _ in ()).throw(
                AssertionError("DeepSeek must not be called when local succeeds")
            ),
        )
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, llm, LocalEmbedding())
        scoring = svc.score_viability(posting.id, _criteria(cid))

        assert llm.calls == [1], "cost guard: no fallback call when local succeeds"
        assert scoring.degraded is False
        assert scoring.score == pytest.approx(0.85)


@pytest.mark.unit
class TestNoFallbackTierConfigured:
    def test_local_failure_with_single_tier_ladder_degrades_without_retry(self):
        """No DeepSeek fallback configured (a 1-tier ladder, e.g. LLM_FALLBACK_
        API_KEY unset): a local failure must degrade straight to the embedding
        signal WITHOUT a wasted duplicate call to the same already-failing
        local tier under a different index."""
        llm = _TieredFakeLLM(
            tier1=lambda: (_ for _ in ()).throw(TimeoutError("local vLLM timeout")),
            tier_count=1,
        )
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, llm, LocalEmbedding())
        scoring = svc.score_viability(posting.id, _criteria(cid))

        assert llm.calls == [1], "must not retry the same tier when no fallback exists"
        assert scoring.degraded is True

    def test_local_failure_with_no_ladder_attribute_degrades_without_crashing(self):
        """An LLM double that exposes no ``.ladder`` at all (defensive duck
        typing) must still degrade cleanly rather than raising."""
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = _posting(cid)
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, _NoLadderFailingLLM(), LocalEmbedding())
        scoring = svc.score_viability(posting.id, _criteria(cid))

        assert scoring.degraded is True
        assert 0.0 <= scoring.score <= 1.0
