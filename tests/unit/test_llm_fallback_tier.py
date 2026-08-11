"""Deterministic cloud FALLBACK tier for the LLM ladder (P0 durability, added scope).

Today the engine's tier ladder normally holds only ONE tier (the local model).
When it fails/times out/is unavailable, the ladder exhausts and (before the
companion ``scoring_service.py`` fix) viability scoring silently degraded to the
local embedding signal. This composes an ADDITIONAL cloud rung (default DeepSeek's
OpenAI-compatible endpoint) into the ladder, appended BELOW the local tier(s), so
the EXISTING climb-on-failure escalation logic in ``OpenAICompatibleLLM`` has a
real model to fall through to.

Covers, hermetically:

* ``SetupService.build_ladder()`` appends the fallback tier only when one is wired
  (``LLM_FALLBACK_API_KEY`` configured) — absent it, the ladder is byte-identical
  to local-only;
* the fallback tier flows through the SAME local-only-mode (P2-11) filter as any
  other tier — dropped when the mode is on, exactly like a cloud tier the operator
  configured by hand;
* end-to-end: a simulated local-tier transport failure ESCALATES to the fallback
  tier and returns its real result — not the embedding degrade — proving this
  composes with the transient-retry guard in ``scoring_service.py`` (belt-and-
  suspenders: the fallback tier fixes the common case; the retry guard is the
  backstop for when both tiers are down or no fallback is configured).
"""

from __future__ import annotations

import json

import httpx
import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scoring_service import ScoringService
from applicant.application.services.setup_service import SetupService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.ports.driven.llm import ChatMessage, TierConfig, TierLadder
from applicant.ports.driving.setup_wizard import LLMSettings


def _local_llm() -> LLMSettings:
    return LLMSettings(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3.6:27b",
        api_key="",
    )


def _fallback_record() -> dict:
    return {
        "provider": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-fallback-test-key",
        "context_window": 65536,
    }


# ── SetupService.build_ladder() wiring ───────────────────────────────────────


@pytest.mark.unit
class TestFallbackTierWiring:
    def test_no_fallback_configured_is_byte_identical_to_local_only(self):
        svc = SetupService()  # fallback_tier defaults to None
        svc.configure_llm(_local_llm())

        ladder = svc.build_ladder()
        assert ladder is not None
        assert len(ladder.tiers) == 1
        assert ladder.tiers[0].base_url == "http://127.0.0.1:11434"

    def test_fallback_tier_appended_below_local_when_configured(self):
        svc = SetupService(fallback_tier=_fallback_record())
        svc.configure_llm(_local_llm())

        ladder = svc.build_ladder()
        assert ladder is not None
        assert len(ladder.tiers) == 2
        assert ladder.tiers[0].base_url == "http://127.0.0.1:11434"
        assert ladder.tiers[1].base_url == "https://api.deepseek.com/v1"
        assert ladder.tiers[1].model == "deepseek-chat"
        assert ladder.tiers[1].api_key == "sk-fallback-test-key"

    def test_fallback_tier_never_persisted_or_surfaced_via_get_tiers(self):
        """The fallback tier is env-sourced and transient — it must not leak into
        the persisted ladder store or the UI ladder editor (which strips api_key
        for STORED tiers but never even sees this one)."""
        svc = SetupService(fallback_tier=_fallback_record())
        svc.configure_llm(_local_llm())

        assert len(svc.get_tiers()) == 1  # only the persisted local tier

    def test_fallback_tier_alone_when_no_local_tier_configured(self):
        """No local tier configured yet, but a fallback key is set: the ladder is
        still buildable (the fallback becomes the only rung) rather than None."""
        svc = SetupService(fallback_tier=_fallback_record())
        ladder = svc.build_ladder()
        assert ladder is not None
        assert len(ladder.tiers) == 1
        assert ladder.tiers[0].base_url == "https://api.deepseek.com/v1"

    def test_fallback_tier_dropped_under_local_only_private_mode(self):
        """P2-11: the fallback (a cloud host) must be excluded by the SAME filter
        that drops any other non-private tier — no special-casing needed."""
        svc = SetupService(local_only=True, fallback_tier=_fallback_record())
        svc.configure_llm(_local_llm())

        ladder = svc.build_ladder()
        assert ladder is not None
        assert len(ladder.tiers) == 1
        assert ladder.tiers[0].base_url == "http://127.0.0.1:11434"


# ── end-to-end escalation: local fails, fallback answers ────────────────────


@pytest.mark.unit
class TestEscalationToFallbackTier:
    def test_local_transport_failure_escalates_to_fallback_not_embeddings(self):
        """The core promise: with BOTH tiers wired, a broken local model still
        yields a REAL model score via the fallback — never the embedding degrade."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if "deepseek" not in str(request.url):
                raise httpx.ConnectError("local model unreachable (simulated)")
            assert body["model"] == "deepseek-chat"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"score": 88, "rationale": "great fit"}'}}
                    ]
                },
            )

        ladder = TierLadder(
            tiers=[
                TierConfig(
                    provider="ollama",
                    base_url="http://127.0.0.1:11434",
                    model="qwen3.6:27b",
                    context_window=32768,
                ),
                TierConfig(
                    provider="openai",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-chat",
                    api_key="sk-fallback-test-key",
                    context_window=65536,
                ),
            ]
        )
        llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))

        result = llm.complete(
            [ChatMessage(role="user", content="score this")],
            start_tier=1,
            json_schema={"type": "object", "required": ["score", "rationale"]},
        )
        assert result.tier == 2
        assert result.structured["score"] == 88

    def test_scoring_service_persists_a_real_score_not_a_degraded_one(self):
        """Wires the 2-tier ladder into ScoringService directly (same shape the
        composition root builds): a local failure must not leave ``degraded=True``
        or defer persistence — the fallback tier answered for real."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "deepseek" not in str(request.url):
                raise httpx.ConnectError("local model unreachable (simulated)")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"score": 82, "rationale": "strong match"}'}}
                    ]
                },
            )

        ladder = TierLadder(
            tiers=[
                TierConfig(
                    provider="ollama",
                    base_url="http://127.0.0.1:11434",
                    model="qwen3.6:27b",
                    context_window=32768,
                ),
                TierConfig(
                    provider="openai",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-chat",
                    api_key="sk-fallback-test-key",
                    context_window=65536,
                ),
            ]
        )
        llm = OpenAICompatibleLLM(ladder=ladder, transport=httpx.MockTransport(handler))

        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        posting = JobPosting(
            id=JobPostingId(new_id()),
            campaign_id=cid,
            source_url="https://example.com/jobs/1",
            # NOT "Senior Backend Engineer" -- this test pins tier-escalation
            # fallback behavior, which requires the LLM tiers to actually be
            # reached; a real "<discipline> Engineer" title now
            # short-circuits OUT_OF_DOMAIN before any tier is ever called
            # (applicant.core.rules.role_domain_fit).
            title="Senior Backend Specialist",
            company="Acme",
            description="Build Python services.",
        )
        storage.postings.add(posting)
        storage.commit()

        svc = ScoringService(storage, llm, LocalEmbedding())
        criteria = SearchCriteria(campaign_id=cid, titles=("Backend Engineer",))
        scoring = svc.score_viability(posting.id, criteria)

        assert scoring.degraded is False
        assert scoring.score == pytest.approx(0.82)
        stored = storage.postings.get(posting.id)
        assert stored.viability_score == pytest.approx(0.82)
