"""CriteriaService unit tests (FR-CRIT-1/2/3, FR-FB-3, FR-LEARN-7)."""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.criteria_service import CriteriaService
from applicant.core.entities.campaign import Campaign
from applicant.core.errors import ConfirmationRequired
from applicant.core.ids import CampaignId, new_id


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="c")
    storage.campaigns.add(c)
    storage.commit()
    return c


@pytest.fixture
def svc(storage) -> CriteriaService:
    return CriteriaService(storage, llm=None)


@pytest.mark.unit
def test_get_default_is_empty(svc, campaign):
    crit = svc.get_criteria(campaign.id)
    assert crit.campaign_id == campaign.id
    assert crit.titles == ()


@pytest.mark.unit
def test_user_edit_non_integral_auto_applies(svc, campaign):
    # FR-CRIT-2: human-readable + keywords are editable freely (non-integral).
    crit = svc.edit_criteria(
        campaign.id, changes={"keywords": ["python"], "human_readable": "remote backend"}
    )
    assert crit.keywords == ("python",)
    assert crit.human_readable == "remote backend"
    # Persisted.
    assert svc.get_criteria(campaign.id).keywords == ("python",)


@pytest.mark.unit
def test_integral_edit_requires_confirmation(svc, campaign):
    # FR-FB-3: changing titles (integral) without confirm is rejected.
    with pytest.raises(ConfirmationRequired):
        svc.edit_criteria(campaign.id, changes={"titles": ["staff engineer"]})


@pytest.mark.unit
def test_integral_edit_with_confirmation_applies(svc, campaign):
    crit = svc.edit_criteria(campaign.id, changes={"titles": ["staff engineer"]}, confirm=True)
    assert crit.titles == ("staff engineer",)


@pytest.mark.unit
def test_learned_adjustment_is_transparent_and_overridable(svc, campaign):
    # FR-CRIT-3: LLM/learning mutation is surfaced; non-integral auto-applies.
    crit = svc.apply_learned_adjustment(
        campaign.id, adjustment={"keywords": ["fastapi"]}, rationale="approved roles use fastapi"
    )
    assert crit.keywords == ("fastapi",)
    assert crit.learned_adjustments["summary"]
    assert crit.learned_adjustments["last_delta"] == {"keywords": ["fastapi"]}
    # User can override / clear the learned layer (FR-CRIT-2).
    cleared = svc.edit_criteria(campaign.id, changes={}, clear_learned=True)
    assert cleared.learned_adjustments == {}


@pytest.mark.unit
def test_learned_integral_is_proposed_not_auto_applied(svc, campaign):
    # Integral learned delta is recorded as proposed, never silently applied (FR-FB-3).
    crit = svc.apply_learned_adjustment(campaign.id, adjustment={"titles": ["principal engineer"]})
    assert crit.titles == ()  # not applied
    assert crit.learned_adjustments["proposed_integral"] == {"titles": ["principal engineer"]}


@pytest.mark.unit
def test_edit_criteria_with_a_comma_separated_string_splits_into_titles(svc, campaign):
    """P0 (2026-08-10): ``_apply`` did ``tuple(value)`` unconditionally for the
    tuple fields (titles/locations/work_modes/keywords). When a caller passes a
    STRING (a plausible shape for a free-text edit box, e.g.
    "Scrum Master, RTE, Agile Coach"), ``tuple(str)`` shreds it into individual
    CHARACTERS ('S', 'c', 'r', ...) instead of titles -- silently corrupting the
    criteria that scoring/discovery match against (a title match becomes
    impossible, so scoring degenerates to whatever non-title signals remain,
    e.g. work-mode/salary alone -- see the live incident this fix closes:
    scores like 98 for an obviously-unrelated role once titles were shredded).
    A comma-separated string must split into trimmed titles instead."""
    crit = svc.edit_criteria(
        campaign.id,
        changes={"titles": "Scrum Master, RTE, Agile Coach"},
        confirm=True,
    )
    assert crit.titles == ("Scrum Master", "RTE", "Agile Coach")
    # Persisted correctly too, not just the returned in-memory value.
    assert svc.get_criteria(campaign.id).titles == ("Scrum Master", "RTE", "Agile Coach")


@pytest.mark.unit
def test_edit_criteria_with_a_list_of_titles_is_unaffected(svc, campaign):
    """A list/tuple input (the normal API shape) must keep working exactly as
    before -- the string guard must not change non-string behavior."""
    crit = svc.edit_criteria(
        campaign.id, changes={"titles": ["Staff Engineer", "Principal Engineer"]}, confirm=True,
    )
    assert crit.titles == ("Staff Engineer", "Principal Engineer")


@pytest.mark.unit
def test_edit_criteria_with_an_empty_string_yields_no_titles(svc, campaign):
    """An empty/whitespace-only string must degrade to no titles, not a tuple
    of whitespace characters."""
    crit = svc.edit_criteria(campaign.id, changes={"titles": "   "}, confirm=True)
    assert crit.titles == ()


@pytest.mark.unit
def test_learned_adjustment_with_a_string_keyword_also_splits_not_shreds(svc, campaign):
    """The same guard must apply on the learned-adjustment path (non-integral
    ``_apply`` call), not just the direct user-edit path -- both route through
    the same ``_apply`` helper."""
    crit = svc.apply_learned_adjustment(
        campaign.id, adjustment={"keywords": "python, fastapi"}, rationale="approved roles"
    )
    assert crit.keywords == ("python", "fastapi")
