"""P1-1a live smoke — the verify layer through the REAL ladder (env-flagged).

Runs ONLY when explicitly armed: set ``PARSE_VERIFY_LIVE=1`` plus the ladder env
(``PARSE_VERIFY_LIVE_BASE_URL``, ``PARSE_VERIFY_LIVE_API_KEY``,
``PARSE_VERIFY_LIVE_MODEL`` and optionally ``..._MODEL_T2``) and point
``PARSE_VERIFY_LIVE_RESUME`` at a résumé file. Never runs in CI (integration
marker + env gate) and never embeds a key or personal document in the repo.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

_ARMED = os.environ.get("PARSE_VERIFY_LIVE") == "1"


@pytest.mark.skipif(not _ARMED, reason="live smoke is env-flagged (PARSE_VERIFY_LIVE=1)")
def test_live_verify_corrects_a_real_resume_through_the_real_ladder():
    from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
    from applicant.adapters.resume_parser.llm_verify import LLMVerifiedResumeParser
    from applicant.adapters.resume_parser.resume_parser import ResumeParser
    from applicant.ports.driven.llm import TierConfig, TierLadder

    base_url = os.environ["PARSE_VERIFY_LIVE_BASE_URL"]
    api_key = os.environ["PARSE_VERIFY_LIVE_API_KEY"]
    resume = os.environ["PARSE_VERIFY_LIVE_RESUME"]
    tiers = [
        TierConfig(
            provider="openrouter",
            base_url=base_url,
            model=os.environ["PARSE_VERIFY_LIVE_MODEL"],
            api_key=api_key,
            context_window=32768,
        )
    ]
    t2 = os.environ.get("PARSE_VERIFY_LIVE_MODEL_T2")
    if t2:
        tiers.append(
            TierConfig(
                provider="openrouter",
                base_url=base_url,
                model=t2,
                api_key=api_key,
                context_window=128000,
            )
        )
    llm = OpenAICompatibleLLM(ladder_provider=lambda: TierLadder(tiers=tiers))
    parser = LLMVerifiedResumeParser(ResumeParser(), llm)

    out = parser.parse(resume)
    verify = out.extra["verify"]
    # The layer must come back with an explicit verdict either way; on a live
    # ladder with a reachable model the expectation is a verified, corrected parse.
    assert verify["verified"] is True, f"live verify failed: {verify}"
    assert out.work_history, "a real résumé must yield work history"
    assert verify.get("confidence"), "confidence must be reported"
