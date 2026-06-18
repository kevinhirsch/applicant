"""ChatService LLM-reply + learning-fold coverage (FR-CHAT-1, FR-FB-2/3, FR-LEARN-3).

The offline/deterministic path is already covered elsewhere; this targets the
previously-uncovered branches: the LLM-backed reply (configured model), its
graceful degrade on an LLM exception / empty completion, and the chat-taste
learning fold (both the atomic API and the load/record/persist fallback).
Hermetic: in-memory storage + fake LLM / learning doubles.
"""

from __future__ import annotations

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.criteria_service import CriteriaService
from applicant.core.ids import CampaignId, new_id
from applicant.ports.driven.llm import LLMResult


class _FakeLLM:
    """Configurable LLM double: capture prompts, or raise, or return empty text."""

    def __init__(self, *, configured=True, text="LLM-crafted reply", raises=False) -> None:
        self._configured = configured
        self._text = text
        self._raises = raises
        self.calls: list = []

    def is_configured(self) -> bool:
        return self._configured

    def list_models(self):  # pragma: no cover - not exercised here
        return ["fake"]

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        if self._raises:
            raise RuntimeError("LLM exploded")
        return LLMResult(text=self._text, tier=1, model="fake")


class _AtomicLearning:
    def __init__(self) -> None:
        self.folds: list = []

    def fold_decision_atomic(self, campaign_id, *, approved, features):
        self.folds.append({"cid": campaign_id, "approved": approved, "features": features})


class _LegacyLearning:
    """No atomic API -> exercises the load/record/persist fallback path."""

    def __init__(self) -> None:
        self.persisted: list = []
        self.recorded: list = []

    def load_model(self, campaign_id):
        return {"campaign_id": campaign_id, "v": 0}

    def record_decision(self, model, *, approved, features):
        self.recorded.append({"model": model, "approved": approved, "features": features})
        return {**model, "v": model["v"] + 1}

    def persist_model(self, model):
        self.persisted.append(model)


class _BoomLearning:
    def fold_decision_atomic(self, *a, **k):
        raise RuntimeError("learning store down")


def _svc(*, llm=None, learning=None):
    storage = InMemoryStorage()
    attrs = AttributeCloudService(storage)
    criteria = CriteriaService(storage)
    return (
        ChatService(
            attribute_service=attrs,
            criteria_service=criteria,
            llm=llm,
            learning=learning,
        ),
        storage,
    )


# === LLM-backed reply (FR-CHAT-1) ==========================================
def test_configured_llm_reply_is_used():
    llm = _FakeLLM(text="Here is a tailored answer.")
    svc, _ = _svc(llm=llm)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "what should I do next?")
    assert result.message == "Here is a tailored answer."
    # The system + user messages were sent, with the gaps appended to the prompt.
    sent = llm.calls[0]["messages"]
    assert sent[0].role == "system"
    assert sent[1].role == "user"
    assert "Known missing details" in sent[1].content  # gaps folded into the prompt
    assert llm.calls[0]["max_tokens"] == 256


def test_llm_exception_degrades_to_deterministic_reply():
    llm = _FakeLLM(raises=True)
    svc, _ = _svc(llm=llm)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "hello")
    # Any LLM failure falls back to the offline deterministic reply.
    assert "confirmation" in result.message.lower()


def test_empty_llm_completion_degrades_to_deterministic_reply():
    llm = _FakeLLM(text="   ")  # whitespace-only completion
    svc, _ = _svc(llm=llm)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "hello")
    assert "confirmation" in result.message.lower()


def test_unconfigured_llm_skips_completion_entirely():
    llm = _FakeLLM(configured=False)
    svc, _ = _svc(llm=llm)
    cid = CampaignId(new_id())
    svc.converse(cid, "hello")
    assert llm.calls == []  # never called when not configured


def test_no_gaps_uses_short_deterministic_reply():
    # When all core attributes + criteria are present, no gaps are appended and
    # the short deterministic reply is returned (offline).
    from applicant.application.services.campaign_service import CampaignService

    svc, storage = _svc()
    # Criteria persistence is campaign-scoped, so the campaign must exist first.
    campaign = CampaignService(storage).create_campaign("Engineer")
    cid = campaign.id
    for name, value in [
        ("first name", "Ada"),
        ("last name", "Lovelace"),
        ("email address", "ada@x.com"),
        ("phone", "555-0100"),
        ("current job title", "Engineer"),
    ]:
        svc.confirm_change(cid, name, value)
    svc._criteria.edit_criteria(
        cid, changes={"titles": ["Engineer"], "human_readable": "Engineer roles"}, confirm=True
    )
    assert svc.identify_gaps(cid) == []
    result = svc.converse(cid, "anything else?")
    assert "integral will be confirmed" in result.message


def test_canonical_onboarding_keys_are_not_reported_missing():
    """Regression: onboarding stores full_name/email/title/phone (canonical keys),
    not the spaced display labels. The gap-finder must treat those as satisfying the
    core needs so a completed profile is never falsely shown as 'still missing'."""
    from applicant.application.services.campaign_service import CampaignService

    svc, storage = _svc()
    cid = CampaignService(storage).create_campaign("Engineer").id
    for name, value in [
        ("full_name", "Ada Lovelace"),
        ("email", "ada@x.com"),
        ("phone", "555-0100"),
        ("title", "Staff Engineer"),
    ]:
        svc.confirm_change(cid, name, value)
    svc._criteria.edit_criteria(
        cid, changes={"titles": ["Engineer"], "human_readable": "Engineer roles"}, confirm=True
    )
    assert svc.identify_gaps(cid) == []


# === learning fold (FR-LEARN-3) ============================================
def test_chat_taste_folds_via_atomic_api():
    learning = _AtomicLearning()
    svc, _ = _svc(learning=learning)
    cid = CampaignId(new_id())
    svc.converse(cid, "I really enjoy backend distributed systems")
    assert len(learning.folds) == 1
    fold = learning.folds[0]
    assert fold["approved"] is True
    # Only tokens longer than 3 chars become features, prefixed with "chat:".
    assert "chat:really" in fold["features"]
    assert "chat:backend" in fold["features"]
    assert "chat:i" not in fold["features"]  # short token dropped


def test_chat_taste_folds_via_legacy_load_record_persist():
    learning = _LegacyLearning()
    svc, _ = _svc(learning=learning)
    cid = CampaignId(new_id())
    svc.converse(cid, "prefer remote senior roles")
    # The fallback path loaded, recorded, and persisted the model.
    assert len(learning.recorded) == 1
    assert len(learning.persisted) == 1
    assert learning.persisted[0]["v"] == 1


def test_chat_taste_skips_when_no_long_tokens():
    learning = _AtomicLearning()
    svc, _ = _svc(learning=learning)
    cid = CampaignId(new_id())
    svc.converse(cid, "a an is to")  # all tokens <= 3 chars -> no features
    assert learning.folds == []


def test_chat_taste_failure_never_breaks_the_turn():
    svc, _ = _svc(learning=_BoomLearning())
    cid = CampaignId(new_id())
    result = svc.converse(cid, "this should still return a reply")  # must not raise
    assert result.message  # the turn completed despite the learning failure


def test_statement_with_empty_value_yields_no_proposal():
    # A statement that parses a name but an empty value (trailing dot only) is
    # rejected rather than proposing a blank attribute.
    svc, _ = _svc()
    cid = CampaignId(new_id())
    result = svc.converse(cid, "my title is .")
    assert result.proposed_changes == []


def test_non_statement_message_yields_no_proposal():
    svc, _ = _svc()
    cid = CampaignId(new_id())
    result = svc.converse(cid, "just chatting, no structured statement here")
    assert result.proposed_changes == []


def test_no_learning_service_is_a_noop():
    svc, _ = _svc(learning=None)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "no learning wired here")
    assert result.message  # nothing to fold; turn still works
