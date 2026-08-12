"""Fast, no-network structural guard for the agile-delivery scoring rubric.

``ScoringService._llm_base``'s ``system_text`` carries the ACTUAL rubric — a
non-posting gate, a domain-fit gate, and a remote/location gate (see its
docstring / the backlog item that motivated it). Verifying the rubric's real
effectiveness requires a live model (``tests/eval/test_scoring_calibration.py``,
skipped by default), but that means the default hermetic lane has NO coverage
at all against someone silently deleting or gutting the rubric text — a
one-line revert of ``system_text`` would pass every other test in this file's
neighborhood.

This module closes that gap cheaply: it captures the EXACT messages
``_llm_base`` builds (via a capturing fake LLM, no network) and asserts the
key gate language / structural inputs (the source URL, work-mode-unstated
handling) are present. It intentionally does NOT assert on any LLM's actual
JUDGMENT — that is the live eval's job — only that the prompt the judgment is
based on still says what it is supposed to say.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.ports.driven.llm import LLMResult


class _CapturingLLM:
    """Configured LLM double that records the exact messages it was sent."""

    def __init__(self) -> None:
        self.last_messages = None
        self.last_json_schema = None

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        self.last_messages = list(messages)
        self.last_json_schema = json_schema
        return LLMResult(text='{"score": 50, "rationale": "captured"}', tier=1, model="fake")


def _posting(**overrides) -> JobPosting:
    cid = CampaignId(new_id())
    defaults = dict(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Scrum Master",
        company="Acme",
        source_url="https://job-boards.greenhouse.io/acme/jobs/123",
        description="We are hiring a Scrum Master.",
    )
    defaults.update(overrides)
    return JobPosting(**defaults)


def _criteria(cid: CampaignId) -> SearchCriteria:
    return SearchCriteria(campaign_id=cid, titles=("Scrum Master",), keywords=("Agile", "Scrum"))


def _captured_system_text() -> str:
    """The exact ``system`` message ``_llm_base`` builds, via a real call."""
    llm = _CapturingLLM()
    svc = ScoringService(InMemoryStorage(), llm, embedding=None)
    posting = _posting()
    svc._llm_base(posting, _criteria(posting.campaign_id))
    assert llm.last_messages is not None, "the capturing LLM was never called"
    system_messages = [m for m in llm.last_messages if m.role == "system"]
    assert system_messages, "no system message was sent"
    return system_messages[0].content


@pytest.mark.unit
class TestScoringRubricStructure:
    """The system prompt still carries the three-gate rubric (no live LLM)."""

    def test_non_posting_gate_present(self) -> None:
        text = _captured_system_text()
        low = text.lower()
        assert "gate 1" in low
        assert "search-results" in low or "search results" in low
        assert "aggregator" in low or "index" in low
        assert "glossary" in low
        assert "boilerplate" in low

    def test_domain_fit_gate_present(self) -> None:
        text = _captured_system_text()
        low = text.lower()
        assert "gate 2" in low
        assert "off-domain" in low
        assert "software-engineering" in low or "software engineering" in low
        assert "solutions/enterprise architecture" in low or "enterprise architecture" in low
        assert "program manager" in low
        assert "agile-delivery facilitation" in low or "agile delivery facilitation" in low

    def test_remote_gate_present(self) -> None:
        text = _captured_system_text()
        low = text.lower()
        assert "gate 3" in low
        assert "remote" in low
        assert "clearance" in low
        assert "unstated" in low

    def test_unstated_work_mode_is_explicitly_not_penalized(self) -> None:
        """Regression sentinel for the cited 95->45 over-penalization bug:
        the rubric must explicitly instruct the model to deduct nothing for a
        genuinely unstated work mode, not just describe the confirmed-onsite
        case."""
        text = _captured_system_text()
        low = text.lower()
        assert "deduct nothing" in low
        assert "genuinely unstated" in low

    def test_gate_verdict_must_drive_the_score(self) -> None:
        """Regression sentinel for the 'rationale names a failed gate but the
        score stays high anyway' failure mode observed while calibrating this
        rubric against real model output."""
        text = _captured_system_text()
        low = text.lower()
        assert "score must" in low or "must be single digits" in low

    def test_known_non_job_domains_named(self) -> None:
        text = _captured_system_text()
        assert "Scaled Agile" in text

    def test_safe_less_taste_preference_present(self) -> None:
        """Regression sentinel for the SAFe-vs-LeSS taste preference (a ranking
        nudge, never a gate): LeSS/agnostic roles rank top-band, SAFe-specific
        roles (including plain RTE titles, which are inherently SAFe) rank a
        notch lower but must never be floored below 70 for that reason alone."""
        text = _captured_system_text()
        low = text.lower()
        assert "taste preference" in low
        assert "less" in low and "large-scale scrum" in low
        assert "wells fargo" in low
        assert "never" in low and "70" in low  # the SAFe sub-top floor
        assert "release train engineer" in low or " rte" in low

    def test_search_engine_company_is_not_penalized_alone(self) -> None:
        """Regression sentinel: an earlier draft over-fired GATE 1 whenever
        'Company' showed the discovery search engine (e.g. 'google cse')
        rather than the real employer, incorrectly failing several REAL
        postings found via search."""
        text = _captured_system_text()
        low = text.lower()
        assert "google cse" in low
        assert "never a reason to fail this gate" in low


@pytest.mark.unit
class TestRemoteGateTravelAndFederal:
    """Regression sentinels for the 2026-08-11 GATE-3 false-positives.

    A remote-BASE role that requires TRAVEL, and a federal/government role that
    explicitly offers remote, were both floored to single digits by the LLM
    over-applying GATE 3 (CompassX Agile Transformation Coach scored 16, CGS
    Agile Coach scored 22 — both genuine, verified US-remote-eligible roles Kevin
    is applying to). The rubric must say travel is not onsite and must not infer
    a clearance/onsite from 'federal' alone."""

    def test_travel_is_not_an_onsite_signal(self) -> None:
        low = _captured_system_text().lower()
        assert "travel" in low
        assert "still remote" in low
        assert "the role's own work location" in low

    def test_explicit_remote_wins_over_federal_or_clearance_inference(self) -> None:
        low = _captured_system_text().lower()
        assert "never infer" in low
        assert "federal" in low or "government" in low
        assert "public trust" in low
        assert "explicit remote statement always wins" in low


@pytest.mark.unit
class TestScoringPromptIncludesSourceUrl:
    """GATE 1/3 both reason about the source URL, so it must reach the prompt."""

    def test_source_url_included_in_user_message(self) -> None:
        llm = _CapturingLLM()
        svc = ScoringService(InMemoryStorage(), llm, embedding=None)
        posting = _posting(source_url="https://www.schwabjobs.com/job/austin/release-train-engineer-rte/1")
        svc._llm_base(posting, _criteria(posting.campaign_id))
        user_messages = [m for m in llm.last_messages if m.role == "user"]
        assert user_messages
        assert "schwabjobs.com/job/austin" in user_messages[0].content

    def test_missing_source_url_does_not_crash(self) -> None:
        llm = _CapturingLLM()
        svc = ScoringService(InMemoryStorage(), llm, embedding=None)
        posting = _posting(source_url="")
        # Must not raise even with no URL to report.
        svc._llm_base(posting, _criteria(posting.campaign_id))
        assert llm.last_messages is not None
