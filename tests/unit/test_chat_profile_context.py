"""Regression: the assistant must answer from the candidate's SAVED profile.

The front-door chat prompt previously contained only the *missing* gaps (plus optional
interview context) — never the known attributes/criteria — so the assistant re-asked the
user for details already on file (e.g. target titles, salary floor). ChatService now
injects a compact profile-context block; these tests pin that it is present when data
exists and absent (degrades silently) when the profile is empty.
"""

from __future__ import annotations

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.criteria_service import CriteriaService
from applicant.core.entities.campaign import Campaign
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


def _user_prompt(llm) -> str:
    return llm.calls[0][1].content  # [system, user]


def test_saved_profile_is_injected_into_the_prompt():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(
            id=cid,
            name="C",
            criteria={
                "titles": ["Senior Backend Engineer", "Staff Software Engineer"],
                "salary_floor": 185000,
                "work_modes": ["remote"],
            },
        )
    )
    storage.commit()
    attrs = AttributeCloudService(storage)
    attrs.ai_add_attribute(cid, "full_name", "Jordan Mercer")
    llm = _FakeLLM()
    svc = ChatService(attribute_service=attrs, criteria_service=CriteriaService(storage), llm=llm)

    svc.converse(cid, "what roles am I targeting and what is my salary floor?")
    prompt = _user_prompt(llm)
    assert "saved profile" in prompt
    assert "Senior Backend Engineer" in prompt
    assert "185000" in prompt
    assert "Jordan Mercer" in prompt


def test_empty_profile_injects_no_block():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    llm = _FakeLLM()
    svc = ChatService(
        attribute_service=AttributeCloudService(storage),
        criteria_service=CriteriaService(storage),
        llm=llm,
    )
    svc.converse(cid, "hi")
    assert "saved profile" not in _user_prompt(llm)
