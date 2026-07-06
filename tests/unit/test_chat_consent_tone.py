"""Consent-boundary TONE, not enforcement (owner feedback: no per-reply nagging).

The review-before-submit boundary is enforced server-side and stays untouched;
this covers the PROMPT: the system prompt must instruct the assistant to state
the approval boundary at most once (introduction / when asked about submitting)
instead of repeating "I never submit without your approval" in every reply, and
to never show its reasoning process. Hermetic: in-memory storage + a fake LLM
capturing the exact system prompt.
"""

from __future__ import annotations

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.criteria_service import CriteriaService
from applicant.core.ids import CampaignId, new_id
from applicant.ports.driven.llm import LLMResult


class _FakeLLM:
    def __init__(self) -> None:
        self.calls: list = []

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        self.calls.append(messages)
        return LLMResult(text="ok", tier=1, model="fake")


class _ReadyOnboarding:
    """Apply-readiness double that reports READY (the per-turn ready block path)."""

    class _R:
        ready = True
        missing: tuple = ()

    def apply_readiness(self, campaign_id):
        return self._R()


def _converse(**kw):
    storage = InMemoryStorage()
    llm = _FakeLLM()
    svc = ChatService(
        attribute_service=AttributeCloudService(storage),
        criteria_service=CriteriaService(storage),
        llm=llm,
        **kw,
    )
    svc.converse(CampaignId(new_id()), "hello there")
    system = llm.calls[0][0].content
    user = llm.calls[0][1].content
    return system, user


def test_system_prompt_limits_consent_boundary_to_once():
    system, _ = _converse()
    low = system.lower()
    # The once-only tone instruction is present…
    assert "at most once" in low
    assert "introduce" in low
    # …while the enforcement facts (the model must not claim submits) survive.
    assert "never claim to have submitted" in low


def test_system_prompt_forbids_showing_reasoning():
    system, _ = _converse()
    low = system.lower()
    assert "never show your reasoning" in low
    assert "final answer only" in low


def test_ready_block_does_not_reinject_approval_boilerplate_each_turn():
    _, user = _converse(onboarding=_ReadyOnboarding())
    # The per-turn ready block must not prompt a fresh approval reassurance…
    assert "waits for their approval" not in user
    assert "still waits" not in user
    # …but keeps the truthfulness guard and steers repetition down explicitly.
    assert "Do not claim you have already submitted anything" in user
    assert "not repeat the approval-boundary reassurance" in user
