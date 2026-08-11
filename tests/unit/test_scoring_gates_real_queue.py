"""Regression eval for the catastrophic viability-scoring miscalibration fix.

Live incident this guards against: against the real discovery queue, nearly
EVERY posting scored 85-100 regardless of relevance to Kevin's profile
(senior Agile delivery leader: Scrum Master / RTE / Agile Coach / Delivery
Manager / agile-flavored TPM), including a blog article ("The Most Important
Agile Delivery Roles: Explained Simply", 100/100) and roles with zero
plausible relationship to agile delivery ("Key Accounts Executive" 98,
"Senior Product Security Engineer II" 93, "Sr. Video Editor (short-form)"
93, "Applied AI Architect" 93, "Research Advisor" 93, ...). Prompt-only
calibration of the LLM rubric (``ScoringService._llm_base``'s
``system_text``) was attempted twice and failed both times to hold against
the real distribution.

The fix is two DETERMINISTIC, no-LLM gates wired into ``ScoringService._score``
(see its module docstring): :func:`~applicant.core.rules.posting_quality
.check_posting_quality` (non-posting floor) and
:func:`~applicant.core.rules.role_domain_fit.classify_role_domain`
(off-domain cap). This file is the ROCK-SOLID regression pin for BOTH gates
against ``tests/eval/fixtures/domain_fit_real_queue_labels.json`` — the 17
exact catastrophic titles from the live incident (1 non-posting + 16
off-domain) plus 5 real/reconstructed in-profile positives — proved two ways:

1. Directly against the pure rule functions (no ScoringService involved at
   all) — this is the part that must be bulletproof.
2. End-to-end through ``ScoringService._score``, with an LLM/embedding
   double that RAISES if ever called for a NON_POSTING/OUT_OF_DOMAIN row —
   proving the short-circuit is real, not just that the rubric happens to
   agree — and a fixed-score fake LLM for IN_DOMAIN rows, proving the gates
   never suppress a real in-profile role.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.core.rules.posting_quality import check_posting_quality
from applicant.core.rules.role_domain_fit import classify_role_domain
from applicant.ports.driven.llm import LLMResult

_FIXTURE_PATH = (
    Path(__file__).parent.parent / "eval" / "fixtures" / "domain_fit_real_queue_labels.json"
)

#: Matches ``ScoringService``'s own fixed gate scores (kept as separate
#: literals, not imported, so a regression that changes the constant without
#: updating this pin is caught rather than silently agreeing with itself).
_GATE_CEILING = 0.40  # "ideally < 0.40" per the fix's acceptance bar
_HARD_CEILING = 0.70  # the fix's hard requirement
_RELEVANT_FLOOR = 0.75


def _load_fixture() -> list[dict]:
    if not _FIXTURE_PATH.exists():  # pragma: no cover - defensive
        pytest.skip(f"fixture not found at {_FIXTURE_PATH}")
    return json.loads(_FIXTURE_PATH.read_text())


def _row_id(row: dict) -> str:
    return f"{row['label']}-{row['id']}"


class _MustNotBeCalledLLM:
    """A configured LLM double that FAILS the test if ``complete()`` runs.

    Proves the gate is a true short-circuit (never reaches the LLM at all),
    not merely a rubric that happens to agree with the gate's verdict.
    """

    def is_configured(self) -> bool:
        return True

    def complete(self, *a, **k):  # pragma: no cover - the assertion IS the point
        raise AssertionError(
            "the LLM must never be called for a NON_POSTING/OUT_OF_DOMAIN "
            "posting -- the deterministic gate must short-circuit first"
        )


class _MustNotBeCalledEmbedding:
    """Companion double for the local-embedding fallback path."""

    def similarity(self, *a, **k):  # pragma: no cover - the assertion IS the point
        raise AssertionError(
            "the embedding fallback must never be called for a "
            "NON_POSTING/OUT_OF_DOMAIN posting either"
        )


class _FixedScoreLLM:
    """Configured LLM double that always returns a strong 90/100 match.

    Used for IN_DOMAIN rows to prove the gates do NOT suppress them: if the
    final score comes back at 90, the deterministic gates let the posting
    through to the LLM untouched, exactly as designed.
    """

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        return LLMResult(
            text='{"score": 90, "rationale": "strong agile-delivery fit"}',
            tier=1,
            model="fake",
        )


def _posting_from_row(row: dict) -> JobPosting:
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=CampaignId(new_id()),
        title=row["title"],
        company=row.get("company") or "",
        source_url=row["source_url"],
        description=row.get("description") or "",
    )


def _kevin_criteria(cid: CampaignId) -> SearchCriteria:
    return SearchCriteria(
        campaign_id=cid,
        titles=(
            "Scrum Master",
            "Release Train Engineer",
            "Agile Coach",
            "Delivery Manager",
            "Technical Program Manager",
        ),
        work_modes=("remote",),
        locations=("United States",),
        keywords=("Agile", "Scrum", "Kanban", "SAFe", "PI Planning"),
    )


@pytest.mark.unit
class TestDeterministicRulesAloneAgainstTheRealQueueFixture:
    """No ScoringService, no LLM, no IO -- the rock-solid layer."""

    @pytest.fixture(scope="class")
    @classmethod
    def fixture_rows(cls) -> list[dict]:
        return _load_fixture()

    def test_every_non_posting_row_is_caught_by_posting_quality(
        self, fixture_rows: list[dict]
    ) -> None:
        misses = []
        for row in fixture_rows:
            if row["label"] != "NON_POSTING":
                continue
            verdict = check_posting_quality(
                row["title"], row["source_url"], row.get("description") or ""
            )
            if verdict.is_posting:
                misses.append(row["id"])
        assert not misses, f"NON_POSTING rows not caught by posting_quality: {misses}"

    def test_every_out_of_domain_row_is_caught_by_role_domain_fit(
        self, fixture_rows: list[dict]
    ) -> None:
        misses = []
        for row in fixture_rows:
            if row["label"] != "OUT_OF_DOMAIN":
                continue
            # Sanity: these are real postings (not caught by the quality
            # gate) so the assertion below actually exercises domain-fit,
            # not a coincidental quality-gate hit.
            assert check_posting_quality(
                row["title"], row["source_url"], row.get("description") or ""
            ).is_posting, f"{row['id']} unexpectedly flagged as a non-posting"
            verdict = classify_role_domain(row["title"], row.get("description") or "")
            if verdict.in_domain is not False:
                misses.append((row["id"], verdict.reason))
        assert not misses, f"OUT_OF_DOMAIN rows not caught by role_domain_fit: {misses}"

    def test_every_in_domain_row_passes_both_gates(self, fixture_rows: list[dict]) -> None:
        failures = []
        for row in fixture_rows:
            if row["label"] != "IN_DOMAIN":
                continue
            quality = check_posting_quality(
                row["title"], row["source_url"], row.get("description") or ""
            )
            if not quality.is_posting:
                failures.append((row["id"], "wrongly flagged NON_POSTING", quality.reason))
                continue
            domain = classify_role_domain(row["title"], row.get("description") or "")
            if domain.in_domain is False:
                failures.append((row["id"], "wrongly flagged OUT_OF_DOMAIN", domain.reason))
        assert not failures, f"IN_DOMAIN rows wrongly gated: {failures}"


@pytest.mark.unit
class TestEndToEndScoringServiceShortCircuit:
    """Through the real ``ScoringService._score`` call tree."""

    @pytest.fixture(scope="class")
    @classmethod
    def fixture_rows(cls) -> list[dict]:
        return _load_fixture()

    @staticmethod
    def _non_posting_and_off_domain_rows(rows: list[dict]) -> list[dict]:
        return [r for r in rows if r["label"] in ("NON_POSTING", "OUT_OF_DOMAIN")]

    @staticmethod
    def _in_domain_rows(rows: list[dict]) -> list[dict]:
        return [r for r in rows if r["label"] == "IN_DOMAIN"]

    def test_gated_rows_score_low_without_ever_calling_the_llm_or_embedding(
        self, fixture_rows: list[dict]
    ) -> None:
        cid = CampaignId(new_id())
        svc = ScoringService(
            InMemoryStorage(), _MustNotBeCalledLLM(), _MustNotBeCalledEmbedding()
        )
        criteria = _kevin_criteria(cid)
        failures = []
        for row in self._non_posting_and_off_domain_rows(fixture_rows):
            posting = _posting_from_row(row)
            scoring = svc.score_posting(posting, criteria)
            pct = round(scoring.score * 100)
            if scoring.score >= _GATE_CEILING or scoring.degraded:
                failures.append((row["id"], row["label"], pct, scoring.rationale))
        assert not failures, f"gated rows scored too high or degraded: {failures}"

    def test_gated_rows_stay_well_under_the_hard_ceiling(self, fixture_rows: list[dict]) -> None:
        # Separate, looser assertion pinned directly to the fix's stated hard
        # requirement ("< 0.70"), independent of the tighter _GATE_CEILING
        # regression pin above.
        cid = CampaignId(new_id())
        svc = ScoringService(
            InMemoryStorage(), _MustNotBeCalledLLM(), _MustNotBeCalledEmbedding()
        )
        criteria = _kevin_criteria(cid)
        for row in self._non_posting_and_off_domain_rows(fixture_rows):
            scoring = svc.score_posting(_posting_from_row(row), criteria)
            assert scoring.score < _HARD_CEILING, (
                f"{row['id']} ({row['label']}) scored {scoring.score * 100:.0f}, "
                f"expected < {_HARD_CEILING * 100:.0f}"
            )

    def test_in_domain_rows_are_not_suppressed_by_the_gates(
        self, fixture_rows: list[dict]
    ) -> None:
        cid = CampaignId(new_id())
        svc = ScoringService(InMemoryStorage(), _FixedScoreLLM(), embedding=None)
        criteria = _kevin_criteria(cid)
        failures = []
        for row in self._in_domain_rows(fixture_rows):
            posting = _posting_from_row(row)
            scoring = svc.score_posting(posting, criteria)
            pct = round(scoring.score * 100)
            if scoring.score < _RELEVANT_FLOOR or scoring.degraded:
                failures.append((row["id"], pct, scoring.rationale))
        assert not failures, f"IN_DOMAIN rows were gated/suppressed: {failures}"
        # The fake LLM always answers 90 -- proves the score reaching the
        # caller IS the LLM's judgment, not a coincidentally-similar gate cap.
        for row in self._in_domain_rows(fixture_rows):
            scoring = svc.score_posting(_posting_from_row(row), criteria)
            assert scoring.score == pytest.approx(0.90), row["id"]
