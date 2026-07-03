"""Reflexion failure lessons wired into the real pre-fill step (dark-engine audit #44).

``LearningService.reflect_on_failure``/``recall_lessons`` distilled + replayed a
per-ATS verbal lesson (Reflexion) but had ZERO callers anywhere in the loop, and
their storage was a plain dict on the ``LearningService`` instance — which the
scheduler rebuilds fresh every tick AND every request (CONC-REQ-1), so even a
caller writing to it would have the lesson vanish before the very next recall.

These tests prove:
* ``AgentLoop``'s pre-fill step now calls ``recall_lessons`` BEFORE a fill attempt
  and ``reflect_on_failure`` AFTER a real field-level failure;
* a recalled lesson actually changes behavior (forces a cautious re-drive);
* the lesson store is now process-lived (``EpisodicLessonLedger``) so it survives
  the per-tick ``AgentLoop``/``LearningService`` rebuild, mirroring the existing
  ``ResumeLedger``/``DigestLedger`` pattern.
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.learning_service import (
    EpisodicLessonLedger,
    LearningService,
)
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState

ATS_URL = "https://jobs.greenhouse.io/acme/123"
ATS_DOMAIN = "jobs.greenhouse.io"


class _PrefillResult:
    def __init__(self, state, fields_failed=None):
        self.state = state
        self.fields_failed = fields_failed or []


class _RecordingPrefill:
    """Fake PrefillService that records every call + the ``cautious`` it received."""

    def __init__(self, result):
        self._result = result
        self.calls: list[tuple[str, bool]] = []

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls.append(("prefill_application", cautious))
        return self._result

    def resume_after_detection(self, application, attributes=None, *, cautious=True):
        self.calls.append(("resume_after_detection", cautious))
        return self._result


def _campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    return cid


def _application(
    storage, cid, *, status=ApplicationState.APPROVED, url=ATS_URL
) -> Application:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title="Engineer", company="Acme", source_url=url)
    )
    app = Application(
        id=ApplicationId(new_id()), campaign_id=cid, posting_id=pid, status=status, root_url=url
    )
    storage.applications.add(app)
    storage.commit()
    return app


def _loop(storage, prefill, learning) -> AgentLoop:
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        prefill_service=prefill,
        learning_service=learning,
    )


@pytest.mark.unit
def test_reflect_on_failure_called_on_real_field_failure():
    """FAIL-BEFORE: reflect_on_failure had no caller, so a real fill failure left no
    lesson at all. A prefill pass reporting ``fields_failed`` now writes one."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid)
    result = _PrefillResult(
        ApplicationState.EMERGENCY_DATA_HANDOFF,
        fields_failed=[
            {
                "selector": "#resume",
                "label": "Resume",
                "url": ATS_URL,
                "error": "locator not found",
            }
        ],
    )
    prefill = _RecordingPrefill(result)
    learning = LearningService(storage, LocalEmbedding())
    loop = _loop(storage, prefill, learning)

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    lessons = learning.recall_lessons(ATS_DOMAIN)
    assert len(lessons) == 1
    assert lessons[0].step == "#resume"
    assert "locator not found" in lessons[0].lesson


@pytest.mark.unit
def test_reflect_on_failure_not_called_on_clean_pass():
    """No field-level failure -> no fabricated lesson."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid)
    result = _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)
    prefill = _RecordingPrefill(result)
    learning = LearningService(storage, LocalEmbedding())
    loop = _loop(storage, prefill, learning)

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    assert learning.recall_lessons(ATS_DOMAIN) == []


@pytest.mark.unit
def test_recalled_lesson_forces_cautious_detection_resume():
    """FAIL-BEFORE: recall_lessons had no caller, so a recalled lesson could never
    change behavior. A domain with a recorded lesson now resumes CAUTIOUS even on
    the BLOCKED_DETECTION path that otherwise hard-codes non-cautious."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid, status=ApplicationState.BLOCKED_DETECTION)
    result = _PrefillResult(ApplicationState.PREFILLING)
    prefill = _RecordingPrefill(result)
    ledger = EpisodicLessonLedger()
    learning = LearningService(storage, LocalEmbedding(), lesson_ledger=ledger)
    # Seed a lesson for this exact ATS, as a prior failure's reflect_on_failure would.
    learning.reflect_on_failure({"ats": ATS_DOMAIN, "step": "captcha", "error": "timeout"})

    loop = _loop(storage, prefill, learning)
    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    assert ("resume_after_detection", True) in prefill.calls


@pytest.mark.unit
def test_no_lesson_keeps_detection_resume_non_cautious():
    """Regression guard: with nothing learned yet, behavior is byte-identical to
    before this change (non-cautious re-drive after a human clears the block)."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid, status=ApplicationState.BLOCKED_DETECTION)
    result = _PrefillResult(ApplicationState.PREFILLING)
    prefill = _RecordingPrefill(result)
    learning = LearningService(storage, LocalEmbedding())
    loop = _loop(storage, prefill, learning)

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    assert ("resume_after_detection", False) in prefill.calls


@pytest.mark.unit
def test_lesson_survives_per_tick_agent_loop_rebuild_via_shared_ledger():
    """The scheduler rebuilds a fresh AgentLoop + LearningService every tick
    (container._build_tick_services), so a lesson reflected on in tick N must be
    recalled by tick N+1's BRAND NEW instances — proving the process-lived
    EpisodicLessonLedger injection actually survives the rebuild (not a per-
    instance dict that resets, per CLAUDE.md's per-tick-state warning)."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    ledger = EpisodicLessonLedger()

    # --- Tick N: a real field failure is reflected on.
    app_n = _application(storage, cid)
    learning_n = LearningService(storage, LocalEmbedding(), lesson_ledger=ledger)
    result_n = _PrefillResult(
        ApplicationState.EMERGENCY_DATA_HANDOFF,
        fields_failed=[
            {
                "selector": "#upload",
                "label": "Resume",
                "url": ATS_URL,
                "error": "element detached",
            }
        ],
    )
    loop_n = _loop(storage, _RecordingPrefill(result_n), learning_n)
    loop_n._build_context(storage.campaigns.get(cid), app_n).prefill()

    # --- Tick N+1: BRAND NEW AgentLoop + LearningService instances sharing the
    # SAME ledger attempt another application on the same ATS.
    app_n1 = _application(storage, cid)
    learning_n1 = LearningService(storage, LocalEmbedding(), lesson_ledger=ledger)
    loop_n1 = _loop(
        storage, _RecordingPrefill(_PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)),
        learning_n1,
    )
    loop_n1._build_context(storage.campaigns.get(cid), app_n1).prefill()

    assert learning_n1.recall_lessons(ATS_DOMAIN) != []


@pytest.mark.unit
def test_default_ledger_is_not_shared_across_instances():
    """Regression guard on the fix itself: two LearningService instances built
    WITHOUT an explicit shared ledger (the plain hermetic construction used all
    over the test suite) stay isolated from each other — only container.py's
    explicit sharing crosses instances."""
    storage = InMemoryStorage()
    ls_a = LearningService(storage, LocalEmbedding())
    ls_a.reflect_on_failure({"ats": ATS_DOMAIN, "step": "x", "error": "y"})
    ls_b = LearningService(storage, LocalEmbedding())
    assert ls_b.recall_lessons(ATS_DOMAIN) == []


@pytest.mark.unit
def test_list_all_lessons_groups_by_ats():
    """The admin/Mind-panel read-model groups every recorded lesson by ATS."""
    storage = InMemoryStorage()
    learning = LearningService(storage, LocalEmbedding())
    learning.reflect_on_failure({"ats": "a.example", "step": "s1", "error": "e1"})
    learning.reflect_on_failure({"ats": "b.example", "step": "s2", "error": "e2"})

    grouped = learning.list_all_lessons()
    assert set(grouped.keys()) == {"a.example", "b.example"}
    assert grouped["a.example"][0].step == "s1"
