"""ChatService proactively gathers the apply-readiness essentials (FR-CHAT-1 / FR-ONBOARD).

The conversational half of onboarding: with the apply-readiness gate wired, the
assistant knows the still-missing essentials (from ``onboarding.apply_readiness``) and:

* proactively NAMES the missing items and asks for the next one or two (offline-safe
  deterministic reply, so no model is needed);
* CAPTURES a stated essential through the existing gated criteria path — a free-text
  role statement + work mode apply directly, an integral salary floor is confirmation
  -gated (FR-FB-3) — and confirms truthfully + reports the remaining gaps;
* once the last essential is present, says it can begin; never claims it started while
  the gate is still closed.

Hermetic: real CriteriaService over InMemoryStorage + a tiny apply-readiness double
driven off the live criteria + a résumé flag, so "what's missing" is never fabricated.
"""

from __future__ import annotations

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.campaign_service import CampaignService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.criteria_service import CriteriaService
from applicant.core.ids import CampaignId
from applicant.core.rules.apply_readiness import evaluate_apply_readiness


class _Onboarding:
    """A minimal apply-readiness reporter driven off the live criteria + a résumé flag.

    Mirrors ``OnboardingService.apply_readiness`` semantics: a free-text criteria
    statement (``human_readable``) stands in for target-roles AND key-skills, so a
    chat-only setup can satisfy the gate. ``has_resume`` is a test toggle.
    """

    def __init__(self, criteria, campaign_id, *, has_resume=False):
        self._criteria = criteria
        self._cid = campaign_id
        self.has_resume = has_resume

    def apply_readiness(self, campaign_id):
        crit = self._criteria.get_criteria(CampaignId(str(campaign_id)))
        statement = bool((crit.human_readable or "").strip())
        return evaluate_apply_readiness(
            has_titles=bool(crit.titles) or statement,
            has_work_modes=bool(crit.work_modes),
            has_locations=bool(crit.locations),
            has_salary_floor=crit.salary_floor is not None,
            has_keywords=bool(crit.keywords) or statement,
            has_resume=self.has_resume,
        )


def _svc(*, has_resume=False):
    storage = InMemoryStorage()
    attrs = AttributeCloudService(storage)
    criteria = CriteriaService(storage)
    campaign = CampaignService(storage).create_campaign("Engineer")
    cid = campaign.id
    onboarding = _Onboarding(criteria, cid, has_resume=has_resume)
    svc = ChatService(
        attribute_service=attrs,
        criteria_service=criteria,
        onboarding=onboarding,
    )
    return svc, criteria, onboarding, cid


# === proactive essentials gathering (offline / deterministic reply) =========
def test_proactively_names_missing_essentials_and_asks():
    svc, _, _, cid = _svc()
    result = svc.converse(cid, "hi")
    msg = result.message.lower()
    # It can't start yet AND names the gate's real missing items (never fabricated).
    assert "start applying" in msg
    assert "target roles" in msg
    assert "work mode" in msg
    # It asks for the NEXT one or two, not a wall — but does ask.
    assert "could you tell me your" in msg


# === capture a free-text role statement (non-integral, applies directly) ====
def test_role_statement_applies_via_gated_path_and_reports_remaining():
    svc, criteria, _, cid = _svc()
    result = svc.converse(cid, "I want senior backend engineer roles")
    # The criteria edit went through the gated path and applied (human_readable).
    crit = criteria.get_criteria(cid)
    assert "backend" in (crit.human_readable or "").lower()
    applied = [c for c in result.control_actions if c.kind == "criteria" and c.applied]
    assert applied, "the role statement should apply directly (non-integral)"
    # The agent confirms truthfully AND reports the still-missing essentials.
    msg = result.message.lower()
    assert "captured" in msg or "got it" in msg
    assert "still need" in msg
    assert "work mode" in msg  # a remaining gap, truthfully reported


# === capture a work mode (non-integral, applies directly) ===================
def test_work_mode_applies_directly():
    svc, criteria, _, cid = _svc()
    result = svc.converse(cid, "focus on remote roles")
    crit = criteria.get_criteria(cid)
    assert "remote" in crit.work_modes
    assert any(c.kind == "criteria" and c.applied for c in result.control_actions)


# === salary floor stays confirmation-gated (integral, FR-FB-3) ==============
def test_salary_floor_is_confirmation_gated_not_applied():
    svc, criteria, _, cid = _svc()
    result = svc.converse(cid, "set my salary floor to $150k")
    # NOT applied — surfaced as a confirmation-gated action (the integral gate holds).
    crit = criteria.get_criteria(cid)
    assert crit.salary_floor is None
    gated = [
        c for c in result.control_actions
        if c.kind == "criteria" and c.requires_confirmation and not c.applied
    ]
    assert gated, "an integral salary floor must wait for explicit confirmation"
    assert gated[0].detail.get("salary_floor") == 150000


# === once the last essential is present, the agent can begin ================
def test_says_it_can_begin_when_all_essentials_present():
    # Seed everything but work mode through the gated criteria path first.
    svc, criteria, onboarding, cid = _svc(has_resume=True)
    criteria.edit_criteria(
        cid,
        changes={
            "human_readable": "senior backend roles, python and go",
            "locations": ["Remote"],
            "salary_floor": 150000,
        },
        confirm=True,
    )
    # The only remaining essential is work mode — the user supplies it in chat.
    result = svc.converse(cid, "remote only please")
    msg = result.message.lower()
    assert "can start applying" in msg or "i can start applying" in msg
    # Truthful: it never claims it ALREADY started, only that it CAN begin.
    assert "i've started applying" not in msg
    assert "already submitted" not in msg


# === never claims it started while still blocked ============================
def test_never_claims_started_while_blocked():
    svc, _, _, cid = _svc()
    result = svc.converse(cid, "have you started applying yet?")
    msg = result.message.lower()
    assert "i've started" not in msg
    assert "i have started" not in msg
    # It is explicit it cannot start yet.
    assert "start applying" in msg


# === additive: chat with NO onboarding wired behaves exactly as before ======
def test_no_onboarding_is_a_clean_noop():
    storage = InMemoryStorage()
    attrs = AttributeCloudService(storage)
    criteria = CriteriaService(storage)
    cid = CampaignService(storage).create_campaign("Engineer").id
    svc = ChatService(attribute_service=attrs, criteria_service=criteria)
    result = svc.converse(cid, "hi")
    # No essentials prompting — the prior gap-based deterministic reply path runs.
    assert "before i can start applying" not in result.message.lower()
