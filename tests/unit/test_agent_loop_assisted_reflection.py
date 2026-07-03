"""LOOP_TOOLS-gated assisted reasoning at pre-fill-failure reflection (dark-engine
audit #47).

``AgentLoop.run_assisted_reasoning`` / ``tools_for`` had exactly zero callers: the
opt-in autonomous tool-calling capability (memory ``remember``/``forget``,
``save_playbook``/``update_playbook``, ``recall``, the bounded ``desktop`` action) was
wired end-to-end but never invoked, so ``LOOP_TOOLS`` could never fire regardless of
the setting.

``_reflect_on_prefill_failure`` (dark-engine audit #44) is the natural call site: it
already writes a raw, templated Reflexion lesson from a real field-level pre-fill
failure ("last failed selector/error, verbatim") on a purely best-effort, exception-
swallowed path that never affects tick control flow or any state-machine transition.
Whether that raw signal is *actually* worth generalizing into a reusable per-ATS note
is a genuinely ambiguous judgment call the templated write can't make — exactly the
kind of decision ``run_assisted_reasoning`` exists for.

These tests prove:
* OFF (default, no ``loop_toolset_factory``/no tool-capable model): the tick's
  raw Reflexion-lesson write is byte-identical to before this change, and no
  memory/playbook write is staged — proving zero behavior change by default;
* ON (``LOOP_TOOLS`` opted in + a tool-capable model that calls ``save_playbook``):
  assisted reasoning actually fires from the real pre-fill-failure path (not just a
  direct ``run_assisted_reasoning`` call), staging a playbook entry through the
  SAME curation guard the chat tools use;
* the raw lesson write happens either way (additive, never replaced);
* a raising/misbehaving assisted-reasoning turn never breaks the tick (defensive).
"""

from __future__ import annotations

import json

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.memory.in_memory import (
    InMemoryMemoryStore,
    InMemoryRecallIndex,
    InMemorySkillStore,
)
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.curation_service import CurationLedger, CurationService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.loop_tools import build_loop_toolset
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.llm import LLMResult, ToolCall, ToolCallResult

ATS_URL = "https://jobs.greenhouse.io/acme/123"
ATS_DOMAIN = "jobs.greenhouse.io"


# --- fakes (mirrors tests/unit/test_loop_tools.py) -------------------------
class _ScriptedToolLLM:
    """A tool-capable model: emits scripted tool-call rounds, then final text."""

    def __init__(self, script, final_text="noted"):
        self._script = list(script)
        self._final = final_text
        self.round = 0
        self.calls_made = 0

    def is_configured(self):
        return True

    def supports_tools(self):
        return True

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        return LLMResult(text=self._final, tier=1, model="fake")

    def complete_with_tools(self, messages, tools, *, start_tier=1, max_tokens=None):
        self.calls_made += 1
        if self.round < len(self._script):
            calls = tuple(self._script[self.round])
            self.round += 1
            return ToolCallResult(text="", tool_calls=calls)
        return ToolCallResult(text=self._final, tool_calls=())


class _NoToolLLM:
    """Default-shaped LLM stand-in with no tool-calling support (byte-identical path)."""

    def is_configured(self):
        return True

    def supports_tools(self):
        return False


class _ExplodingLLM:
    """Proves a raising assisted-reasoning turn never breaks the tick."""

    def is_configured(self):
        return True

    def supports_tools(self):
        return True

    def complete_with_tools(self, messages, tools, *, start_tier=1, max_tokens=None):
        raise RuntimeError("boom")


def _tc(tool, **args):
    return ToolCall(id="c1", name=tool, arguments=json.dumps(args))


def _memory_stack():
    mem, skills, recall = InMemoryMemoryStore(), InMemorySkillStore(), InMemoryRecallIndex()

    class _Memory:
        pass

    bundle = _Memory()
    bundle.memory, bundle.skills, bundle.recall = mem, skills, recall
    cur = CurationService(
        memory_store=mem, skill_store=skills, ledger=CurationLedger(), recall=recall
    )
    return bundle, cur, mem, skills


class _PrefillResult:
    def __init__(self, state, fields_failed=None):
        self.state = state
        self.fields_failed = fields_failed or []


class _RecordingPrefill:
    def __init__(self, result):
        self._result = result

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        return self._result

    def resume_after_detection(self, application, attributes=None, *, cautious=True):
        return self._result


def _campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    return cid


def _application(storage, cid, *, status=ApplicationState.APPROVED, url=ATS_URL) -> Application:
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


def _failed_result():
    return _PrefillResult(
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


# --- OFF by default: byte-identical to before this change ------------------
@pytest.mark.unit
def test_default_off_no_llm_no_factory_leaves_lesson_write_unchanged():
    """No ``llm``/``loop_toolset_factory`` at all (today's plain construction, still
    used all over the suite): the raw lesson is written exactly as before, and
    ``run_assisted_reasoning`` cleanly no-ops."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid)
    prefill = _RecordingPrefill(_failed_result())
    learning = LearningService(storage, LocalEmbedding())
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        prefill_service=prefill,
        learning_service=learning,
    )

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    lessons = learning.recall_lessons(ATS_DOMAIN)
    assert len(lessons) == 1
    assert lessons[0].step == "#resume"
    assert "locator not found" in lessons[0].lesson


@pytest.mark.unit
def test_loop_tools_off_setting_with_tool_capable_model_stages_nothing():
    """``LOOP_TOOLS=off`` (the default setting) even WITH a tool-capable model and a
    real factory wired: ``build_loop_toolset`` itself returns ``None`` for "off", so
    ``tools_for``/``run_assisted_reasoning`` no-op and nothing is staged — proving the
    new call site adds no behavior unless the setting is explicitly opted in."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid)
    prefill = _RecordingPrefill(_failed_result())
    learning = LearningService(storage, LocalEmbedding())
    bundle, cur, mem, skills = _memory_stack()
    llm = _ScriptedToolLLM([[_tc("save_playbook", name="acme", procedure=["step one"])]])

    def _factory(campaign_id, tick_llm):
        return build_loop_toolset(
            setting="off",  # the shipped default
            llm=tick_llm,
            campaign_id=campaign_id,
            agent_memory=bundle,
            curation_service=cur,
        )

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        prefill_service=prefill,
        learning_service=learning,
        llm=llm,
        loop_toolset_factory=_factory,
    )

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    # Raw lesson still written (unchanged)...
    assert len(learning.recall_lessons(ATS_DOMAIN)) == 1
    # ...but no assisted-reasoning tool call happened: nothing staged, model unused.
    assert cur.list_staged() == ()
    assert llm.calls_made == 0


@pytest.mark.unit
def test_non_tool_model_leaves_lesson_write_unchanged():
    """``LOOP_TOOLS=auto`` but the configured model doesn't advertise tool calling:
    still a clean no-op (mirrors ``build_loop_toolset``'s own gate)."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid)
    prefill = _RecordingPrefill(_failed_result())
    learning = LearningService(storage, LocalEmbedding())
    bundle, cur, mem, skills = _memory_stack()

    def _factory(campaign_id, tick_llm):
        return build_loop_toolset(
            setting="auto",
            llm=tick_llm,
            campaign_id=campaign_id,
            agent_memory=bundle,
            curation_service=cur,
        )

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        prefill_service=prefill,
        learning_service=learning,
        llm=_NoToolLLM(),
        loop_toolset_factory=_factory,
    )

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    assert len(learning.recall_lessons(ATS_DOMAIN)) == 1
    assert cur.list_staged() == ()


# --- ON: LOOP_TOOLS opted in + tool-capable model => assisted reasoning fires --
@pytest.mark.unit
def test_loop_tools_on_stages_a_playbook_entry_from_a_real_prefill_failure():
    """``LOOP_TOOLS=auto`` + a tool-capable model that chooses ``save_playbook``: the
    REAL pre-fill-failure path (``ctx.prefill()``, not a direct
    ``run_assisted_reasoning`` call) now drives the loop's tool-capable model, and its
    tool call stages through the SAME curation guard the chat tools use (FR-MIND-9:
    not auto-applied)."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid)
    prefill = _RecordingPrefill(_failed_result())
    learning = LearningService(storage, LocalEmbedding())
    bundle, cur, mem, skills = _memory_stack()
    llm = _ScriptedToolLLM(
        [[_tc("save_playbook", name="jobs.greenhouse.io",
              procedure=["Retry the resume upload after a short wait"])]]
    )

    def _factory(campaign_id, tick_llm):
        return build_loop_toolset(
            setting="auto",
            llm=tick_llm,
            campaign_id=campaign_id,
            agent_memory=bundle,
            curation_service=cur,
        )

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        prefill_service=prefill,
        learning_service=learning,
        llm=llm,
        loop_toolset_factory=_factory,
    )

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    # The raw templated lesson is STILL written (additive, not replaced).
    assert len(learning.recall_lessons(ATS_DOMAIN)) == 1
    # The assisted-reasoning turn actually ran and staged a playbook write.
    assert llm.calls_made >= 1
    assert skills.list_skills() == ()  # staged, not auto-applied (FR-MIND-9)
    staged = cur.list_staged()
    assert len(staged) == 1


@pytest.mark.unit
def test_clean_pass_never_enters_assisted_reasoning():
    """No field-level failure -> no raw lesson AND no assisted-reasoning call (the
    tool-capable model is never even asked)."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid)
    prefill = _RecordingPrefill(_PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL))
    learning = LearningService(storage, LocalEmbedding())
    bundle, cur, mem, skills = _memory_stack()
    llm = _ScriptedToolLLM([[_tc("save_playbook", name="x", procedure=["y"])]])

    def _factory(campaign_id, tick_llm):
        return build_loop_toolset(
            setting="auto",
            llm=tick_llm,
            campaign_id=campaign_id,
            agent_memory=bundle,
            curation_service=cur,
        )

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        prefill_service=prefill,
        learning_service=learning,
        llm=llm,
        loop_toolset_factory=_factory,
    )

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()

    assert learning.recall_lessons(ATS_DOMAIN) == []
    assert llm.calls_made == 0
    assert cur.list_staged() == ()


@pytest.mark.unit
def test_assisted_reasoning_failure_never_breaks_the_tick():
    """A raising tool-capable model during the assisted-reflection call must not break
    the tick: the raw lesson write still lands, and no exception propagates out of
    ``ctx.prefill()``."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    app = _application(storage, cid)
    prefill = _RecordingPrefill(_failed_result())
    learning = LearningService(storage, LocalEmbedding())
    bundle, cur, mem, skills = _memory_stack()

    def _factory(campaign_id, tick_llm):
        return build_loop_toolset(
            setting="auto",
            llm=tick_llm,
            campaign_id=campaign_id,
            agent_memory=bundle,
            curation_service=cur,
        )

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        prefill_service=prefill,
        learning_service=learning,
        llm=_ExplodingLLM(),
        loop_toolset_factory=_factory,
    )

    ctx = loop._build_context(storage.campaigns.get(cid), app)
    ctx.prefill()  # must not raise

    assert len(learning.recall_lessons(ATS_DOMAIN)) == 1
    assert cur.list_staged() == ()


# --- direct unit coverage of the new AgentLoop methods ----------------------
@pytest.mark.unit
def test_maybe_assisted_reflect_passes_campaign_id_through_to_run_assisted_reasoning():
    """``_maybe_assisted_reflect`` calls ``run_assisted_reasoning`` with the SAME
    campaign id the failure occurred under (not a stray/default one)."""
    storage = InMemoryStorage()
    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    seen = []
    loop.run_assisted_reasoning = lambda campaign_id, system, prompt: seen.append(
        (campaign_id, system, prompt)
    )
    cid = CampaignId(new_id())

    loop._maybe_assisted_reflect(cid, ATS_DOMAIN, {"selector": "#x", "error": "boom"})

    assert len(seen) == 1
    got_cid, system, prompt = seen[0]
    assert got_cid == cid
    assert ATS_DOMAIN in prompt
    assert "boom" in prompt
