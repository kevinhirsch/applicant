"""ChatService loop-control routing (FR-AGENT-1/2, FR-CRIT, FR-FB-3).

The chatbot is the control surface for the autonomous loop: the user steers the
agent by talking to it. These tests verify that:

* "pause" / "resume" route to the run-control service and confirm truthfully;
* a daily-throughput request is clamped to the hard cap and rejected out of range;
* a criteria refocus applies the non-integral facet directly and gates the integral
  one (salary floor) behind the confirmation gate (FR-FB-3);
* when a control dep is absent the chat declines gracefully (no crash, no fabrication);
* existing chat behavior is unchanged for non-control messages.

Hermetic: in-memory storage + fake run-control double, plus the real AgentRunService /
CriteriaService over InMemoryStorage for an end-to-end check.
"""

from __future__ import annotations

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.campaign_service import CampaignService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.criteria_service import CriteriaService
from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP
from applicant.core.ids import CampaignId, new_id


class _FakeRunControl:
    """Records pause/resume + throughput calls; mirrors AgentRunService's surface."""

    def __init__(self) -> None:
        self.active_calls: list = []
        self.configure_calls: list = []

    def set_active(self, campaign_id, active):
        self.active_calls.append({"cid": campaign_id, "active": active})

    def configure_run(self, campaign_id, *, throughput_target=None, **_):
        self.configure_calls.append({"cid": campaign_id, "throughput": throughput_target})


def _svc(*, run_control=None, criteria=None):
    storage = InMemoryStorage()
    attrs = AttributeCloudService(storage)
    criteria = criteria if criteria is not None else CriteriaService(storage)
    svc = ChatService(
        attribute_service=attrs,
        criteria_service=criteria,
        run_control=run_control,
    )
    return svc, storage


# === pause / resume (FR-AGENT-2) ===========================================
def test_pause_routes_to_run_control_and_confirms_truthfully():
    rc = _FakeRunControl()
    svc, _ = _svc(run_control=rc)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "pause for now")
    assert rc.active_calls == [{"cid": cid, "active": False}]
    assert len(result.control_actions) == 1
    act = result.control_actions[0]
    assert act.kind == "pause" and act.applied and act.ok
    assert "paused" in result.message.lower()
    # A control turn does not also try to parse the message as an attribute statement.
    assert result.proposed_changes == []


def test_resume_routes_to_run_control():
    rc = _FakeRunControl()
    svc, _ = _svc(run_control=rc)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "okay resume")
    assert rc.active_calls == [{"cid": cid, "active": True}]
    assert result.control_actions[0].kind == "resume"
    assert "resumed" in result.message.lower()


def test_pause_question_is_not_an_imperative():
    rc = _FakeRunControl()
    svc, _ = _svc(run_control=rc)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "can you pause?")
    assert rc.active_calls == []  # a question never pauses
    assert result.control_actions == []


def test_pause_declines_gracefully_when_control_absent():
    svc, _ = _svc(run_control=None)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "please pause")
    act = result.control_actions[0]
    assert act.kind == "pause" and not act.applied and not act.ok
    assert "can't" in result.message.lower()


# === daily throughput (FR-AGENT-1) =========================================
def test_throughput_within_range_applies():
    rc = _FakeRunControl()
    svc, _ = _svc(run_control=rc)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "apply to 20 roles a day")
    assert rc.configure_calls == [{"cid": cid, "throughput": 20}]
    act = result.control_actions[0]
    assert act.kind == "throughput" and act.applied and act.ok
    assert act.detail["throughput_target"] == 20
    assert "20 applications a day" in result.message


def test_throughput_above_hard_cap_is_rejected_not_clamped_silently():
    rc = _FakeRunControl()
    svc, _ = _svc(run_control=rc)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "apply to 50 a day")
    # Out of range -> never silently exceeds OR clamps; nothing is applied.
    assert rc.configure_calls == []
    act = result.control_actions[0]
    assert not act.applied and not act.ok
    assert str(THROUGHPUT_HARD_CAP) in result.message
    assert "outside" in result.message.lower()


def test_throughput_zero_is_rejected():
    rc = _FakeRunControl()
    svc, _ = _svc(run_control=rc)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "set the daily target to 0")
    assert rc.configure_calls == []
    assert not result.control_actions[0].applied


def test_throughput_declines_when_control_absent():
    svc, _ = _svc(run_control=None)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "set my daily target to 10")
    act = result.control_actions[0]
    assert act.kind == "throughput" and not act.applied and not act.ok
    assert "can't" in result.message.lower()


# === criteria refocus (FR-CRIT, gated by FR-FB-3) ==========================
def test_refocus_remote_applies_directly():
    storage = InMemoryStorage()
    campaign = CampaignService(storage).create_campaign("Engineer")
    cid = campaign.id
    criteria = CriteriaService(storage)
    attrs = AttributeCloudService(storage)
    svc = ChatService(attribute_service=attrs, criteria_service=criteria)
    result = svc.converse(cid, "focus on remote roles")
    act = result.control_actions[0]
    assert act.kind == "criteria" and act.applied
    # The non-integral work-mode change is persisted directly (no confirmation).
    assert "remote" in criteria.get_criteria(cid).work_modes
    assert "remote" in result.message.lower()


def test_refocus_salary_floor_is_confirmation_gated_not_applied():
    storage = InMemoryStorage()
    campaign = CampaignService(storage).create_campaign("Engineer")
    cid = campaign.id
    criteria = CriteriaService(storage)
    attrs = AttributeCloudService(storage)
    svc = ChatService(attribute_service=attrs, criteria_service=criteria)
    result = svc.converse(cid, "raise the salary floor to 150000")
    act = result.control_actions[0]
    assert act.kind == "criteria"
    assert act.requires_confirmation and not act.applied
    assert act.detail["salary_floor"] == 150000
    # NOT committed yet — the integral change waits for explicit confirmation (FR-FB-3).
    assert criteria.get_criteria(cid).salary_floor is None
    assert "confirm" in result.message.lower()


def test_confirm_criteria_refocus_commits_through_the_gate():
    storage = InMemoryStorage()
    campaign = CampaignService(storage).create_campaign("Engineer")
    cid = campaign.id
    criteria = CriteriaService(storage)
    attrs = AttributeCloudService(storage)
    svc = ChatService(attribute_service=attrs, criteria_service=criteria)
    svc.confirm_criteria_refocus(cid, changes={"salary_floor": 150000})
    assert criteria.get_criteria(cid).salary_floor == 150000


def test_salary_k_shorthand_is_understood():
    storage = InMemoryStorage()
    campaign = CampaignService(storage).create_campaign("Engineer")
    cid = campaign.id
    criteria = CriteriaService(storage)
    svc = ChatService(
        attribute_service=AttributeCloudService(storage), criteria_service=criteria
    )
    result = svc.converse(cid, "set the salary floor to 120k")
    assert result.control_actions[0].detail["salary_floor"] == 120000


# === end-to-end with the REAL run-control service ==========================
def test_pause_then_resume_via_real_agent_run_service():
    storage = InMemoryStorage()
    campaign = CampaignService(storage).create_campaign("Engineer")
    cid = campaign.id
    rc = AgentRunService(storage)
    svc = ChatService(
        attribute_service=AttributeCloudService(storage),
        criteria_service=CriteriaService(storage),
        run_control=rc,
    )
    svc.converse(cid, "pause")
    assert storage.campaigns.get(cid).active is False
    svc.converse(cid, "resume")
    assert storage.campaigns.get(cid).active is True


def test_throughput_via_real_agent_run_service_persists_clamped():
    storage = InMemoryStorage()
    campaign = CampaignService(storage).create_campaign("Engineer")
    cid = campaign.id
    rc = AgentRunService(storage)
    svc = ChatService(
        attribute_service=AttributeCloudService(storage),
        criteria_service=CriteriaService(storage),
        run_control=rc,
    )
    svc.converse(cid, "apply to 25 a day")
    assert storage.campaigns.get(cid).throughput_target == 25


# === existing behavior unchanged for non-control messages ==================
def test_non_control_message_has_no_control_actions():
    rc = _FakeRunControl()
    svc, _ = _svc(run_control=rc)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "just chatting about my background")
    assert result.control_actions == []
    assert rc.active_calls == [] and rc.configure_calls == []
    assert result.message


def test_attribute_statement_still_parses_when_not_a_control():
    rc = _FakeRunControl()
    svc, _ = _svc(run_control=rc)
    cid = CampaignId(new_id())
    result = svc.converse(cid, "my favorite language is python")
    # No control intent matched -> the attribute parser still runs as before.
    assert result.control_actions == []
    assert len(result.proposed_changes) == 1
    assert result.proposed_changes[0].name == "favorite language"
