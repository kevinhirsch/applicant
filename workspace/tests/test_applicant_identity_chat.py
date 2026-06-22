"""Tests for the unified Applicant identity + onboarding-gap chat awareness.

Covers:
* The ONE canonical identity (src/applicant_identity.py) is what plain chat,
  the agent loop, and scheduled-task fallbacks present — no persona drift, no
  white-label doubling bug.
* build_context_preface injects a SHORT onboarding-gap note (listing the user's
  specific missing sections, told to mention them only when relevant) in plain
  chat — and injects NOTHING when onboarding is complete / there is no campaign /
  the engine is unreachable, and never when a preset or agent mode owns identity.

Hermetic: the engine is replaced with a fake async ApplicantEngineClient; zero
network. Workspace tests run under the ROOT uv env:
    uv run pytest -q workspace/tests/test_applicant_identity_chat.py
"""

import types

import pytest

import tests.conftest  # noqa: F401  -- sets sys.path + stubs heavy deps

import src.applicant_identity as identity_mod
import src.chat_processor as cp
from src.applicant_identity import APPLICANT_IDENTITY


# ── 1. Canonical identity ──────────────────────────────────────────────────


def test_identity_is_unified_agent_not_disclaiming_assistant():
    text = APPLICANT_IDENTITY.lower()
    # Identifies as the autonomous job-application agent...
    assert "applicant" in text
    assert "agent" in text
    assert "autonomous" in text
    # ...and as a SINGLE entity that both works and chats.
    assert "chat" in text
    # ...with the review-before-submit boundary as part of identity.
    assert "review" in text and "submit" in text


def test_identity_is_white_label_clean():
    text = APPLICANT_IDENTITY
    # No upstream codenames / no doubled-name bug.
    assert "Applicant, Applicant" not in text
    assert "workspace assistant" not in text.lower()
    # No FR-/NFR- requirement jargon leaks into user-facing copy.
    assert "FR-" not in text
    assert "NFR-" not in text


def test_chat_processor_reuses_canonical_identity():
    # Imported, not copied.
    assert cp.APPLICANT_IDENTITY is identity_mod.APPLICANT_IDENTITY


def test_agent_loop_leads_with_canonical_identity():
    import src.agent_loop as al

    assert al._AGENT_PREAMBLE.startswith(APPLICANT_IDENTITY)
    # Existing tool-access wording is preserved.
    assert "tool access" in al._AGENT_PREAMBLE.lower()


def test_scheduled_task_persona_reuses_canonical_identity():
    import src.task_scheduler as ts

    assert ts._SCHEDULED_TASK_PERSONA.startswith(APPLICANT_IDENTITY)
    assert "scheduled task" in ts._SCHEDULED_TASK_PERSONA.lower()


# ── helpers for the gap-note tests ─────────────────────────────────────────


class _FakeEngine:
    """Minimal async stand-in for ApplicantEngineClient.

    ``calls`` counts how many times it was entered, so we can assert the per-owner
    TTL cache actually shields the engine from per-turn hits.
    """

    instances: list = []

    def __init__(self, *, status=None, campaigns=None, state=None, raises=False):
        self._status = status
        self._campaigns = campaigns
        self._state = state
        self._raises = raises
        self.enter_count = 0
        _FakeEngine.instances.append(self)

    async def __aenter__(self):
        self.enter_count += 1
        if self._raises:
            raise RuntimeError("engine unreachable")
        return self

    async def __aexit__(self, *exc):
        return False

    async def setup_status(self):
        return self._status if self._status is not None else {}

    async def list_campaigns(self):
        return self._campaigns

    async def onboarding_state(self, campaign_id):
        assert campaign_id == "camp-1"
        return self._state


def _patch_engine(monkeypatch, **kwargs):
    """Patch the engine factory and reset the per-owner TTL cache."""
    cp._gap_note_cache.clear()
    _FakeEngine.instances.clear()

    def _factory(*a, **k):
        return _FakeEngine(**kwargs)

    fake_mod = types.SimpleNamespace(ApplicantEngineClient=_factory)
    monkeypatch.setitem(__import__("sys").modules, "src.applicant_engine", fake_mod)
    return fake_mod


class _NullMemory:
    def load(self, owner=None):
        return []


def _processor():
    return cp.ChatProcessor(
        memory_manager=_NullMemory(),
        personal_docs_manager=types.SimpleNamespace(rag_manager=None),
    )


def _preface(proc, **overrides):
    kwargs = dict(
        message="hello there",
        session=types.SimpleNamespace(id="s1"),
        use_web=False,
        use_rag=False,
        use_memory=False,
        owner="kevin",
    )
    kwargs.update(overrides)
    preface, _rag, _web = proc.build_context_preface(**kwargs)
    return preface


def _system_texts(preface):
    return [m["content"] for m in preface if m.get("role") == "system"]


# ── 2. Onboarding-gap awareness ────────────────────────────────────────────


def test_gap_note_lists_specific_missing_sections(monkeypatch):
    _patch_engine(
        monkeypatch,
        status={"onboarding_complete": False},
        campaigns=[{"id": "camp-1"}],
        state={"complete": False, "missing_sections": ["work_authorization", "base_resume", "eeo"]},
    )
    texts = _system_texts(_preface(_processor()))
    note = next((t for t in texts if "Onboarding note" in t), None)
    assert note is not None, "expected a gap-awareness note in plain chat"
    # Friendly labels, not raw codes.
    assert "work authorization" in note
    assert "base résumé" in note
    assert "optional EEO disclosures" in note
    assert "work_authorization" not in note
    assert "base_resume" not in note
    # Mention-when-relevant, not a per-turn nag.
    assert "only when" in note.lower()
    assert "every turn" in note.lower()


def test_no_note_when_onboarding_complete(monkeypatch):
    _patch_engine(
        monkeypatch,
        status={"onboarding_complete": True},
        campaigns=[{"id": "camp-1"}],
        state={"complete": True, "missing_sections": []},
    )
    texts = _system_texts(_preface(_processor()))
    assert not any("Onboarding note" in t for t in texts)
    # The canonical identity is still present.
    assert any(t == APPLICANT_IDENTITY for t in texts)


def test_no_note_when_state_complete_even_if_status_silent(monkeypatch):
    # setup_status doesn't say complete, but onboarding_state does -> no note.
    _patch_engine(
        monkeypatch,
        status={},
        campaigns=[{"id": "camp-1"}],
        state={"complete": True, "missing_sections": []},
    )
    texts = _system_texts(_preface(_processor()))
    assert not any("Onboarding note" in t for t in texts)


def test_no_note_when_no_campaign(monkeypatch):
    _patch_engine(
        monkeypatch,
        status={"onboarding_complete": False},
        campaigns=[],
        state=None,
    )
    texts = _system_texts(_preface(_processor()))
    assert not any("Onboarding note" in t for t in texts)


def test_no_note_when_engine_unreachable(monkeypatch):
    _patch_engine(monkeypatch, raises=True)
    texts = _system_texts(_preface(_processor()))
    # Degrade silently: identity still there, no gap note, no crash.
    assert any(t == APPLICANT_IDENTITY for t in texts)
    assert not any("Onboarding note" in t for t in texts)


def test_no_note_with_preset_system_prompt(monkeypatch):
    # A preset/character owns identity -> the canonical identity AND the gap note
    # are both suppressed.
    _patch_engine(
        monkeypatch,
        status={"onboarding_complete": False},
        campaigns=[{"id": "camp-1"}],
        state={"complete": False, "missing_sections": ["location"]},
    )
    texts = _system_texts(_preface(_processor(), preset_system_prompt="You are Pirate Pete."))
    assert any("Pirate Pete" in t for t in texts)
    assert not any(t == APPLICANT_IDENTITY for t in texts)
    assert not any("Onboarding note" in t for t in texts)


def test_no_note_in_agent_mode(monkeypatch):
    # Agent mode gets identity from the agent preamble, so the preface skips both.
    _patch_engine(
        monkeypatch,
        status={"onboarding_complete": False},
        campaigns=[{"id": "camp-1"}],
        state={"complete": False, "missing_sections": ["location"]},
    )
    texts = _system_texts(_preface(_processor(), agent_mode=True))
    assert not any("Onboarding note" in t for t in texts)


def test_gap_note_is_cached_per_owner_no_per_turn_engine_hit(monkeypatch):
    _patch_engine(
        monkeypatch,
        status={"onboarding_complete": False},
        campaigns=[{"id": "camp-1"}],
        state={"complete": False, "missing_sections": ["location"]},
    )
    proc = _processor()
    # Three chat turns for the same owner.
    for _ in range(3):
        _preface(proc)
    # Only the first turn should have actually entered the engine client.
    entered = [e for e in _FakeEngine.instances if e.enter_count > 0]
    assert len(entered) == 1, f"engine hit {len(entered)} times — TTL cache not shielding per-turn calls"


def test_gap_note_expired_ttl_refetches(monkeypatch):
    _patch_engine(
        monkeypatch,
        status={"onboarding_complete": False},
        campaigns=[{"id": "camp-1"}],
        state={"complete": False, "missing_sections": ["location"]},
    )
    proc = _processor()
    _preface(proc)
    assert len([e for e in _FakeEngine.instances if e.enter_count > 0]) == 1
    # Force the cached entry to look stale.
    for k in list(cp._gap_note_cache):
        cp._gap_note_cache[k] = (0.0, cp._gap_note_cache[k][1])
    _preface(proc)
    assert len([e for e in _FakeEngine.instances if e.enter_count > 0]) == 2
