"""Labeled-eval regression test for the agile-delivery viability rubric.

Calibrates/guards ``ScoringService._llm_base``'s ``system_text`` (the LLM
scoring rubric) against a hand-labeled set of REAL postings pulled from a live
campaign, plus one hand-authored posting filling a gap the live data did not
cover. The goal the rubric must hit, cleanly, without regressing any one
category (see the backlog item that motivated this file):

* RELEVANT  (real agile-delivery roles: SM/RTE/Agile Coach/Delivery Manager,
  or a TPM/PgM whose core IS agile delivery) -> score >= 75.
* OFF_DOMAIN (senior/remote/well-paid but NOT agile-delivery-core: software-
  engineering management, IC engineering, solutions/enterprise architecture,
  general technical/product TPM) -> score < 50.
* NON_REMOTE (a real agile-delivery posting that is confirmed onsite/hybrid,
  non-US, or requires a security clearance) -> score < 50.
* NON_POSTING (search-index/aggregator pages, comparison/guide articles, a
  methodology's own reference/glossary page, or a captured "description" that
  is really site-navigation boilerplate) -> score < 50, regardless of how
  keyword-dense the title is.

This is a LIVE-MODEL eval, not a hermetic unit test: the rubric's substance
lives in the natural-language ``system_text`` sent to an LLM, so the only way
to verify it actually holds up is to run it against a real model. It requires
a reachable OpenAI-compatible chat endpoint and is marked ``@pytest.mark.eval``
(auto-promoted to ``integration`` by ``tests/eval/conftest.py``), so it is
SKIPPED in the default ``-m "not integration"`` CI lane and only runs when
explicitly invoked with a model configured, e.g.::

    SCORING_EVAL_LLM_BASE_URL=http://localhost:8000/v1 \\
    SCORING_EVAL_LLM_MODEL=qwen3.6:27b \\
    LLM_DISABLE_THINKING=1 \\
    pytest tests/eval/test_scoring_calibration.py -m eval -v

``LLM_DISABLE_THINKING=1`` (an existing opt-in on
``OpenAICompatibleLLM._apply_thinking_toggle``) is strongly recommended for a
reasoning-mode model such as Qwen3 — without it the model's hidden reasoning
trace can consume the whole ``max_tokens`` budget the scoring call uses
(250), producing an empty ``content`` and forcing every posting to fall back
to the local embedding signal instead of exercising the rubric at all.

The complementary, ALWAYS-run structural guard lives in
``tests/unit/test_scoring_service_rubric.py`` — it asserts the key gate
language is present in ``system_text`` without any network call, so an
accidental gutting of the rubric is still caught in the default lane even
when this eval is not run.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "agile_delivery_scoring_labels.json"

#: The candidate profile this rubric is calibrated for (mirrors the live
#: campaign criteria): senior Agile delivery leader targeting SM/RTE/Agile
#: Coach/Delivery Manager/agile-core TPM roles, Remote US, salary >= $120k.
_CRITERIA_HUMAN_READABLE = (
    "Senior Agile delivery leader targeting Scrum Master, Release Train Engineer, "
    "Agile Coach, Delivery Manager, or Technical Program Manager roles whose core "
    "responsibility IS agile/scrum delivery facilitation and coaching (not general "
    "software engineering management, not solutions/enterprise architecture, not "
    "IC engineering, not sales/account management, not data science). Must be fully "
    "remote within the United States. Minimum salary $120,000. Domain: Agile, Scrum, "
    "Kanban, SAFe, LeSS, PI Planning, Release Train, servant leadership, agile "
    "coaching, agile transformation."
)

#: A RELEVANT posting must score at least this high; every other label must
#: score below the "50" half of the gap, so nothing sits ambiguously between
#: the two — matches the campaign's ``DEFAULT_VIABILITY_THRESHOLD`` (60) with
#: headroom on both sides for LLM sampling variance.
_HIGH_FLOOR = 75
_LOW_CEILING = 50

#: How many times to retry a single posting when the LLM call transiently
#: fails and ``ScoringService`` degrades to the local-embedding fallback —
#: that fallback reflects lexical overlap, not the rubric under test, so a
#: degraded score must never be accepted as this eval's verdict.
_MAX_DEGRADED_RETRIES = 5


def _load_fixture() -> list[dict]:
    return json.loads(_FIXTURE_PATH.read_text())


def _llm_configured() -> tuple[str, str, str, str] | None:
    base_url = os.getenv("SCORING_EVAL_LLM_BASE_URL", "").strip()
    model = os.getenv("SCORING_EVAL_LLM_MODEL", "").strip()
    if not base_url or not model:
        return None
    provider = os.getenv("SCORING_EVAL_LLM_PROVIDER", "openai").strip() or "openai"
    api_key = os.getenv("SCORING_EVAL_LLM_API_KEY", "").strip()
    return provider, base_url, model, api_key


_LLM_CONFIG = _llm_configured()

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        _LLM_CONFIG is None,
        reason=(
            "set SCORING_EVAL_LLM_BASE_URL and SCORING_EVAL_LLM_MODEL (and "
            "optionally SCORING_EVAL_LLM_PROVIDER/SCORING_EVAL_LLM_API_KEY) to "
            "run the live scoring-rubric calibration eval against a real model"
        ),
    ),
]


@pytest.fixture(scope="module")
def _criteria() -> SearchCriteria:
    return SearchCriteria(
        campaign_id=CampaignId(new_id()),
        human_readable=_CRITERIA_HUMAN_READABLE,
        titles=(
            "Scrum Master",
            "Release Train Engineer",
            "Agile Coach",
            "Delivery Manager",
            "Technical Program Manager",
        ),
        work_modes=("remote",),
        locations=("United States",),
        salary_floor=120000,
        keywords=("Agile", "Scrum", "Kanban", "SAFe", "LeSS", "PI Planning", "SAFe RTE"),
    )


@pytest.fixture(scope="module")
def _scoring_service() -> ScoringService:
    provider, base_url, model, api_key = _LLM_CONFIG  # type: ignore[misc]
    llm = OpenAICompatibleLLM(
        provider=provider, base_url=base_url, api_key=api_key, model=model, timeout=120.0
    )
    storage = InMemoryStorage()
    return ScoringService(storage, llm, LocalEmbedding())


def _fixture_rows() -> list[dict]:
    return _load_fixture() if _LLM_CONFIG is not None else []


def _row_id(row: dict) -> str:
    return f"{row['label']}-{row['id'][:12]}"


@pytest.mark.parametrize("row", _fixture_rows(), ids=_row_id)
def test_posting_scores_on_the_correct_side_of_the_gap(
    row: dict, _criteria: SearchCriteria, _scoring_service: ScoringService
) -> None:
    """Each labeled posting must land on the correct side of the HIGH/LOW gap.

    RELEVANT postings must score >= 75; OFF_DOMAIN/NON_REMOTE/NON_POSTING
    postings must all score < 50 REGARDLESS of keyword density, seniority,
    pay, or how confidently worded the JD reads — see the module docstring
    for the full rationale per category, and ``row["note"]`` (surfaced in the
    assertion message on failure) for what this SPECIFIC posting is testing.
    """
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=CampaignId(new_id()),
        title=row["title"],
        company=row.get("company") or "",
        source_url=row["source_url"],
        location=row.get("location"),
        work_mode=row.get("work_mode"),
        salary=row.get("salary"),
        description=row.get("description") or "",
        source_key=row.get("source_key"),
    )

    scoring = _scoring_service.score_posting(posting, _criteria)
    attempts = 1
    while scoring.degraded and attempts < _MAX_DEGRADED_RETRIES:
        time.sleep(2)
        scoring = _scoring_service.score_posting(posting, _criteria)
        attempts += 1
    assert not scoring.degraded, (
        f"LLM call kept failing/degrading after {attempts} attempts for "
        f"{row['id']!r} — this eval needs a working LLM endpoint, not the "
        f"local-embedding fallback, to say anything about the rubric."
    )

    pct = round(scoring.score * 100)
    label = row["label"]
    detail = (
        f"\n  title: {row['title']!r}\n  label: {label}  score: {pct}\n"
        f"  rationale: {scoring.rationale!r}\n  note: {row.get('note', '')}"
    )
    if label == "RELEVANT":
        assert pct >= _HIGH_FLOOR, f"expected >= {_HIGH_FLOOR}, got {pct}{detail}"
    else:
        assert pct < _LOW_CEILING, f"expected < {_LOW_CEILING}, got {pct}{detail}"
