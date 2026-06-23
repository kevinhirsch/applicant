"""Closing the FR-MIND learning loop: real run history feeds curation, curated runs
land in recall, and the LLM summarizer is used when wired (FR-MIND-2/3/7/13).

Hermetic — no LLM, no Postgres, no network. Proves:

* ``RunHistoryProvider`` maps real stored applications + outcomes -> RunSummaries
  (bounded), and a submitted application becomes a skill-worthy summary;
* a full scheduled tick with those real summaries proposes memory/skills AND indexes
  the run into recall, so ``recall.search`` returns the indexed run;
* re-ticking is idempotent — no duplicate proposals and no duplicate recall rows;
* ``build_llm_summarizer`` uses the model when one is wired and falls back cleanly
  to the heuristic when not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.memory.in_memory import (
    InMemoryMemoryStore,
    InMemoryRecallIndex,
    InMemorySkillStore,
)
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.curation_service import (
    CurationLedger,
    CurationService,
    RunSummary,
    _default_summarizer,
    build_llm_summarizer,
)
from applicant.application.services.run_history import RunHistoryProvider
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OutcomeEventId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


class _Loop:
    def tick(self, campaign_id, now=None, **_):
        return None


class _Gate:
    def is_automated_work_allowed(self) -> bool:
        return True


def _seed(storage, *, submitted: bool):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=True))
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.SUBMITTED_BY_USER
            if submitted
            else ApplicationState.MATERIAL_REVIEW,
            job_title="Senior Python Engineer",
            root_url="https://acme.wd1.myworkdayjobs.com/careers",
        )
    )
    if submitted:
        storage.outcomes.add(
            OutcomeEvent(
                id=OutcomeEventId(new_id()),
                application_id=aid,
                type="submitted",
                source=OutcomeSource.MANUAL,
            )
        )
    return cid, aid


# --- RunHistoryProvider: real storage -> RunSummaries ---------------------


def test_provider_maps_stored_applications_and_outcomes_to_summaries():
    storage = InMemoryStorage()
    _, aid = _seed(storage, submitted=True)
    summaries = RunHistoryProvider()(storage, datetime.now(UTC))

    assert len(summaries) == 1
    s = summaries[0]
    assert s.run_id == str(aid)
    assert "Senior Python Engineer" in s.text
    assert s.succeeded is True
    # A submitted application is non-trivial -> skill-worthy (tool_calls threshold).
    assert s.tool_calls >= 5
    # The ATS host is the reusable topic key.
    assert s.topic == "acme.wd1.myworkdayjobs.com"


def test_provider_skips_trivial_just_discovered_rows_and_bounds_output():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=True))
    # One DISCOVERED (skipped) + several reviewable rows.
    storage.applications.add(
        Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.DISCOVERED,
        )
    )
    for _ in range(5):
        storage.applications.add(
            Application(
                id=ApplicationId(new_id()),
                campaign_id=cid,
                posting_id=JobPostingId(new_id()),
                status=ApplicationState.MATERIAL_REVIEW,
                job_title="Role",
            )
        )
    summaries = RunHistoryProvider(max_summaries=3)(storage, datetime.now(UTC))
    # DISCOVERED is skipped; output capped at the bound.
    assert len(summaries) == 3
    assert all(s.run_id for s in summaries)


# --- full scheduled tick: propose + index recall --------------------------


def test_scheduled_tick_with_real_history_proposes_and_indexes_recall():
    storage = InMemoryStorage()
    _, aid = _seed(storage, submitted=True)

    ledger = CurationLedger()
    recall = InMemoryRecallIndex()
    curation = CurationService(
        memory_store=InMemoryMemoryStore(),
        skill_store=InMemorySkillStore(),
        ledger=ledger,
        recall=recall,
    )
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        setup_service=_Gate(),
        curation_service=curation,
        curation_schedule="daily",
        run_summaries_provider=RunHistoryProvider(),
    )

    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["curation"]["ran"] is True
    assert out["curation"]["reviewed"] == 1
    # A submitted run -> one memory + one skill proposal, both staged for review.
    assert out["curation"]["staged"] == 2

    # FR-MIND-3: the curated run is now recallable by content.
    hits = recall.search("Senior Python Engineer")
    assert hits, "expected the curated run to be indexed into recall"
    assert hits[0].run_id == str(aid)


def test_recall_indexing_is_idempotent_across_reticks():
    storage = InMemoryStorage()
    _seed(storage, submitted=True)
    ledger = CurationLedger()
    recall = InMemoryRecallIndex()
    provider = RunHistoryProvider()
    curation = CurationService(
        memory_store=InMemoryMemoryStore(),
        skill_store=InMemorySkillStore(),
        ledger=ledger,
        recall=recall,
    )

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    # Two ticks across two UTC days hit the curator with the same run again.
    curation.run_curation_tick(provider(storage, now))
    curation.run_curation_tick(provider(storage, now + timedelta(days=1)))

    # The run was reviewed once (ledger dedupe) -> exactly one recall row.
    assert len(recall._rows) == 1
    assert len(ledger.proposed_runs) == 1


# --- LLM summarizer: used when wired, falls back when not ------------------


class _FakeResult:
    def __init__(self, text):
        self.text = text


class _FakeLLM:
    def __init__(self, *, configured=True, text="A crisp learned lesson."):
        self._configured = configured
        self._text = text
        self.calls = 0

    def is_configured(self):
        return self._configured

    def complete(self, messages, **_):
        self.calls += 1
        return _FakeResult(self._text)


def test_llm_summarizer_used_when_model_wired():
    llm = _FakeLLM(text="Clear the react-select first, then type the city.")
    summarize = build_llm_summarizer(llm)
    s = RunSummary(run_id="r1", campaign_id=None, text="raw", topic="acme")
    out = summarize(s)
    assert out == "Clear the react-select first, then type the city."
    assert llm.calls == 1


def test_llm_summarizer_falls_back_to_heuristic_when_unconfigured():
    # Unconfigured LLM -> the factory returns the exact heuristic.
    assert build_llm_summarizer(_FakeLLM(configured=False)) is _default_summarizer
    # None LLM -> the exact heuristic too (hermetic default).
    assert build_llm_summarizer(None) is _default_summarizer


def test_llm_summarizer_degrades_on_completion_error():
    class _BoomLLM(_FakeLLM):
        def complete(self, messages, **_):
            raise RuntimeError("provider down")

    summarize = build_llm_summarizer(_BoomLLM())
    s = RunSummary(run_id="r1", campaign_id=None, text="raw detail", topic="acme")
    # Falls back to the heuristic line for this run rather than raising.
    assert summarize(s) == _default_summarizer(s)


def test_curation_uses_llm_summarizer_end_to_end():
    storage = InMemoryStorage()
    _seed(storage, submitted=True)
    llm = _FakeLLM(text="Sign in via company SSO before opening the application.")
    curation = CurationService(
        memory_store=InMemoryMemoryStore(),
        skill_store=InMemorySkillStore(),
        ledger=CurationLedger(),
        recall=InMemoryRecallIndex(),
        summarizer=build_llm_summarizer(llm),
    )
    result = curation.run_curation_tick(RunHistoryProvider()(storage, datetime.now(UTC)))
    assert result.reviewed == 1
    assert llm.calls == 1
    # The LLM lesson flows into the staged memory proposal text.
    assert any(
        "company SSO" in p.entry.text for p in result.memory_proposals
    )


@pytest.mark.unit
def test_provider_signature_is_scheduler_compatible():
    # The provider must be callable as provider(storage, now) — the scheduler slot.
    storage = InMemoryStorage()
    out = RunHistoryProvider()(storage, datetime.now(UTC))
    assert out == []
