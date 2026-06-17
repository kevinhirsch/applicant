"""Stage 2.5 lane A — engine-side injection of upcoming-interview context into
the assistant's LLM prompt (ChatService._interview_context).

The ChatService takes an optional WorkspacePort. When the callback channel is
available and returns auto-detected interviews, a short "upcoming interviews"
block is appended to the LLM user prompt. When the channel is off / empty /
errors, NOTHING is appended and the chat turn is unaffected (degrade silently).
Hermetic: in-memory storage + fake LLM + mocked WorkspacePort.
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


class _FakeWorkspace:
    def __init__(self, *, available=True, payload=None, raises=False) -> None:
        self._available = available
        self._payload = payload
        self._raises = raises
        self.owner_seen = "unset"
        self.called = False

    def available(self) -> bool:
        return self._available

    def calendar_interviews(self, *, owner=None):
        self.called = True
        self.owner_seen = owner
        if self._raises:
            raise RuntimeError("workspace down")
        return self._payload


def _svc(workspace):
    storage = InMemoryStorage()
    llm = _FakeLLM()
    svc = ChatService(
        attribute_service=AttributeCloudService(storage),
        criteria_service=CriteriaService(storage),
        llm=llm,
        workspace=workspace,
    )
    return svc, llm


def _user_prompt(llm) -> str:
    return llm.calls[0][1].content  # [system, user]


def test_interview_context_injected_when_available():
    ws = _FakeWorkspace(
        payload={
            "interviews": [
                {"title": "Technical Interview", "detected_company": "Acme",
                 "start": "2026-07-01T10:00:00"},
                {"title": "Phone screen", "start": "2026-07-02T09:00:00"},
            ]
        }
    )
    svc, llm = _svc(ws)
    svc.converse(CampaignId(new_id()), "help me prep")
    prompt = _user_prompt(llm)
    assert "Upcoming interviews" in prompt
    assert "Technical Interview" in prompt
    assert "Acme" in prompt
    assert ws.called


def test_no_workspace_means_no_context():
    svc, llm = _svc(None)
    svc.converse(CampaignId(new_id()), "hi")
    assert "Upcoming interviews" not in _user_prompt(llm)


def test_unavailable_channel_skips_call():
    ws = _FakeWorkspace(available=False)
    svc, llm = _svc(ws)
    svc.converse(CampaignId(new_id()), "hi")
    assert ws.called is False
    assert "Upcoming interviews" not in _user_prompt(llm)


def test_empty_interviews_degrade_silently():
    ws = _FakeWorkspace(payload={"interviews": []})
    svc, llm = _svc(ws)
    svc.converse(CampaignId(new_id()), "hi")
    assert "Upcoming interviews" not in _user_prompt(llm)


def test_workspace_error_degrades_silently():
    ws = _FakeWorkspace(raises=True)
    svc, llm = _svc(ws)
    # Must not raise; prompt simply omits the block.
    svc.converse(CampaignId(new_id()), "hi")
    assert "Upcoming interviews" not in _user_prompt(llm)


def test_none_payload_degrades_silently():
    ws = _FakeWorkspace(payload=None)
    svc, llm = _svc(ws)
    svc.converse(CampaignId(new_id()), "hi")
    assert "Upcoming interviews" not in _user_prompt(llm)
