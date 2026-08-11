"""Round-3/round-4 regression eval: RANKING QUALITY within the allowlisted set.

Kevin's own words on a role the (round-2) allowlist correctly kept viable
but ranked 95: "too low pay, heavily SAFe, posted ~a month ago, not
high-impact, no idea why it scored so high." The allowlist fixed RELEVANCE
(in-domain vs not); it never touched WHICH allowlisted role is actually good
for Kevin. This file is the end-to-end regression pin for the fix: SIX
deterministic RANKING multipliers (recency, SAFe penalty, pay, seniority,
fit-to-profile, degree-requirement — ``applicant.core.rules.ranking_factors``)
plus a US-remote HARD gate, wired into ``ScoringService._score``.

ROUND 4 (after reading Kevin's actual résumé): his real title history is
EXCLUSIVELY Scrum Master/Agile Coach, with Scrum/Agile certs and no
bachelor's degree. ``round4-fit-pair-*`` and ``round4-degree-pair-*`` rows
below pin the two new factors on TOP of the round-3 gates/factors: a
Scrum Master must outrank an equally-fresh big-tech TPM (both stay viable,
fit ranks them), and a hard degree requirement ranks a posting lower.

Proved several ways against ``tests/eval/fixtures/ranking_factors_labels.json``:

1. HIGH vs LOW relative separation, with a FIXED-score fake LLM (always
   answers 95, Kevin's own reported number) so the effect measured is
   PURELY the deterministic ranking/gate layer, not LLM variance.
   MODERATE-labeled rows (round-3-widened TPM/PM/PMO/Operations families —
   still viable, just ranked below the round-4 STRONG-fit set) are excluded
   from this strict binary comparison; see the dedicated round-4 pairwise
   tests instead.
2. The four HARD-GATED rows (onsite, two non-US-remote, one off-domain)
   never reach the LLM at all — an LLM double that raises if called proves
   the short-circuit is real.
3. Round-4 pairwise comparisons: two rows identical in every dimension
   except the ONE factor under test (fit-tier, degree requirement).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.ports.driven.llm import LLMResult

_FIXTURE_PATH = Path(__file__).parent.parent / "eval" / "fixtures" / "ranking_factors_labels.json"
_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

#: Rows whose LOW ranking must ALSO cross the viability threshold (a hard
#: gate, or Kevin's own compounded real-world case). The other LOW rows
#: isolate a SINGLE ranking factor deliberately — each factor is a modest
#: ranking nudge by design (never a standalone override for an otherwise
#: strong candidate), so they are only asserted to rank clearly BELOW the
#: HIGH group, not necessarily below the threshold. See module docstring.
_MUST_BE_NON_VIABLE_IDS = frozenset(
    {
        "low-safe-rte-kevin-reported-case",
        "low-onsite-not-remote",
        "low-non-us-remote-bangalore",
        "low-non-us-remote-uk",
        "low-wrong-field-software-engineer",
    }
)
#: Rows that short-circuit BEFORE the LLM (a hard gate fired) — must never
#: reach a "must not be called" LLM double.
_HARD_GATED_IDS = frozenset(
    {
        "low-onsite-not-remote",
        "low-non-us-remote-bangalore",
        "low-non-us-remote-uk",
        "low-wrong-field-software-engineer",
    }
)


def _load_fixture() -> list[dict]:
    if not _FIXTURE_PATH.exists():  # pragma: no cover - defensive
        pytest.skip(f"fixture not found at {_FIXTURE_PATH}")
    return json.loads(_FIXTURE_PATH.read_text())


def _row_id(row: dict) -> str:
    return f"{row['label']}-{row['id']}"


class _FixedScoreLLM:
    """Always answers 95 — Kevin's own reported number for the live false
    positive. Isolates the deterministic ranking/gate layer's effect from
    any LLM variance: whatever separation shows up is purely the fix."""

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        return LLMResult(text='{"score": 95, "rationale": "strong fit"}', tier=1, model="fake")


class _MustNotBeCalledLLM:
    def is_configured(self) -> bool:
        return True

    def complete(self, *a, **k):  # pragma: no cover - the assertion IS the point
        raise AssertionError(
            "the LLM must never be called for a hard-gated (non-US-remote/"
            "onsite/off-domain) posting -- the deterministic gate must "
            "short-circuit first"
        )


def _posting_from_row(row: dict) -> JobPosting:
    date_posted = None
    if row.get("days_ago") is not None:
        date_posted = _NOW - timedelta(days=row["days_ago"])
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=CampaignId(new_id()),
        title=row["title"],
        company=row.get("company") or "",
        source_url=row["source_url"],
        description=row.get("description") or "",
        salary=row.get("salary"),
        work_mode=row.get("work_mode"),
        location=row.get("location"),
        date_posted=date_posted,
    )


def _kevin_criteria(cid: CampaignId) -> SearchCriteria:
    return SearchCriteria(
        campaign_id=cid,
        titles=("Scrum Master", "Release Train Engineer", "Agile Coach", "Program Manager"),
        keywords=("Agile", "Scrum", "Delivery"),
    )


@pytest.mark.unit
class TestHighVsLowRanking:
    @pytest.fixture(scope="class")
    @classmethod
    def fixture_rows(cls) -> list[dict]:
        return _load_fixture()

    def test_every_high_row_scores_at_least_as_well_as_every_low_row(
        self, fixture_rows: list[dict]
    ) -> None:
        cid = CampaignId(new_id())
        svc = ScoringService(InMemoryStorage(), _FixedScoreLLM(), embedding=None)
        criteria = _kevin_criteria(cid)

        high_scores: dict[str, float] = {}
        low_scores: dict[str, float] = {}
        for row in fixture_rows:
            # MODERATE rows (round-3-widened TPM/PM/PMO/Operations families)
            # are excluded from this strict HIGH-vs-LOW binary -- they are
            # deliberately RANKED BELOW strong-fit HIGH rows (round 4) but
            # are NOT meant to be lumped in with the gated/penalized LOW
            # rows either. See the dedicated round-4 pairwise tests below.
            if row["label"] == "MODERATE":
                continue
            scoring = svc.score_posting(_posting_from_row(row), criteria)
            if row["label"] == "HIGH":
                high_scores[row["id"]] = scoring.score
            else:
                low_scores[row["id"]] = scoring.score

        assert high_scores, "fixture must contain HIGH rows"
        assert low_scores, "fixture must contain LOW rows"
        min_high = min(high_scores.values())
        max_low = max(low_scores.values())
        assert max_low < min_high, (
            f"every LOW row must rank below every HIGH row -- "
            f"worst LOW={max_low:.3f} ({max(low_scores, key=low_scores.get)}), "
            f"weakest HIGH={min_high:.3f} ({min(high_scores, key=high_scores.get)})\n"
            f"high={high_scores}\nlow={low_scores}"
        )

    def test_high_rows_stay_strongly_viable(self, fixture_rows: list[dict]) -> None:
        cid = CampaignId(new_id())
        svc = ScoringService(InMemoryStorage(), _FixedScoreLLM(), embedding=None)
        criteria = _kevin_criteria(cid)
        failures = []
        for row in fixture_rows:
            if row["label"] != "HIGH":
                continue
            scoring = svc.score_posting(_posting_from_row(row), criteria)
            if scoring.score < 0.85:
                failures.append((row["id"], round(scoring.score * 100)))
        assert not failures, f"HIGH rows scored too low: {failures}"

    def test_designated_low_rows_fail_viability(self, fixture_rows: list[dict]) -> None:
        """Kevin's exact compounded real-world case + the hard gates must
        cross below the viability threshold, not just rank lower."""
        cid = CampaignId(new_id())
        svc = ScoringService(InMemoryStorage(), _FixedScoreLLM(), embedding=None)
        criteria = _kevin_criteria(cid)
        failures = []
        for row in fixture_rows:
            if row["id"] not in _MUST_BE_NON_VIABLE_IDS:
                continue
            scoring = svc.score_posting(_posting_from_row(row), criteria)
            if svc.is_viable(scoring):
                failures.append((row["id"], round(scoring.score * 100)))
        assert not failures, f"rows expected to fail viability still passed: {failures}"

    def test_kevins_reported_case_specifically(self, fixture_rows: list[dict]) -> None:
        """The exact symptom report: a role scored 95 despite being 'too low
        pay, heavily SAFe, posted ~a month ago, not high-impact'."""
        row = next(r for r in fixture_rows if r["id"] == "low-safe-rte-kevin-reported-case")
        cid = CampaignId(new_id())
        svc = ScoringService(InMemoryStorage(), _FixedScoreLLM(), embedding=None)
        scoring = svc.score_posting(_posting_from_row(row), _kevin_criteria(cid))
        pct = round(scoring.score * 100)
        assert pct < 60, f"Kevin's reported case must no longer score ~95, got {pct}: {scoring.rationale}"
        assert not svc.is_viable(scoring)


@pytest.mark.unit
class TestRound4FitAndDegreePairwiseComparisons:
    """Round 4: two rows identical in every dimension except the ONE factor
    under test (fit-tier, degree requirement) -- isolates each factor's
    effect precisely, independent of everything else in the pipeline."""

    @pytest.fixture(scope="class")
    @classmethod
    def fixture_rows(cls) -> list[dict]:
        return _load_fixture()

    @staticmethod
    def _row(fixture_rows: list[dict], row_id: str) -> dict:
        return next(r for r in fixture_rows if r["id"] == row_id)

    def test_scrum_master_outranks_an_equally_fresh_big_tech_tpm(
        self, fixture_rows: list[dict]
    ) -> None:
        cid = CampaignId(new_id())
        svc = ScoringService(InMemoryStorage(), _FixedScoreLLM(), embedding=None)
        criteria = _kevin_criteria(cid)

        sm_row = self._row(fixture_rows, "round4-fit-pair-strong-scrum-master")
        tpm_row = self._row(fixture_rows, "round4-fit-pair-moderate-tpm")
        sm_score = svc.score_posting(_posting_from_row(sm_row), criteria).score
        tpm_score = svc.score_posting(_posting_from_row(tpm_row), criteria).score

        assert sm_score > tpm_score, (
            f"Scrum Master ({sm_score:.3f}) must outrank an equally-fresh/paid "
            f"big-tech TPM ({tpm_score:.3f}) -- Kevin's real title history is "
            f"Scrum Master/Agile Coach, not TPM"
        )
        # Both stay genuinely viable -- fit is a ranking nudge, not a gate.
        tpm_scoring = svc.score_posting(_posting_from_row(tpm_row), criteria)
        assert svc.is_viable(tpm_scoring), "the MODERATE-fit TPM must still be viable, just ranked lower"

    def test_degree_required_posting_ranks_below_the_no_requirement_pair(
        self, fixture_rows: list[dict]
    ) -> None:
        cid = CampaignId(new_id())
        svc = ScoringService(InMemoryStorage(), _FixedScoreLLM(), embedding=None)
        criteria = _kevin_criteria(cid)

        no_req_row = self._row(fixture_rows, "round4-degree-pair-no-requirement")
        hard_req_row = self._row(fixture_rows, "round4-degree-pair-hard-requirement")
        no_req_scoring = svc.score_posting(_posting_from_row(no_req_row), criteria)
        hard_req_scoring = svc.score_posting(_posting_from_row(hard_req_row), criteria)

        assert hard_req_scoring.score < no_req_scoring.score, (
            f"a posting hard-requiring a degree ({hard_req_scoring.score:.3f}) must rank "
            f"below an otherwise-identical posting with no such requirement "
            f"({no_req_scoring.score:.3f}) -- Kevin has no bachelor's degree"
        )
        # Still viable on its own -- a ranking nudge, not a gate.
        assert svc.is_viable(hard_req_scoring), "a degree requirement alone must not gate an otherwise-strong role"


@pytest.mark.unit
class TestHardGatedRowsNeverReachTheLlm:
    @pytest.fixture(scope="class")
    @classmethod
    def fixture_rows(cls) -> list[dict]:
        return _load_fixture()

    def test_hard_gated_rows_short_circuit_before_the_llm(self, fixture_rows: list[dict]) -> None:
        cid = CampaignId(new_id())
        svc = ScoringService(InMemoryStorage(), _MustNotBeCalledLLM(), embedding=None)
        criteria = _kevin_criteria(cid)
        rows = [r for r in fixture_rows if r["id"] in _HARD_GATED_IDS]
        assert len(rows) == len(_HARD_GATED_IDS), "fixture is missing an expected hard-gated row"
        for row in rows:
            scoring = svc.score_posting(_posting_from_row(row), criteria)
            assert not svc.is_viable(scoring), row["id"]
            assert scoring.degraded is False, row["id"]
