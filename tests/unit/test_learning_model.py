import pytest

from applicant.core.entities.learning_model import LearningModel
from applicant.core.ids import CampaignId


@pytest.fixture(autouse=True)
def _reset_module_state():
    """No module-level mutable state to reset; fixture exists for xdist parallel safety."""
    yield


@pytest.mark.unit
class TestLearningModelDefaults:
    """LearningModel uses sensible defaults for all optional fields."""

    def test_minimal_construction(self):
        model = LearningModel(campaign_id=CampaignId("camp-1"))
        assert model.campaign_id == "camp-1"
        assert model.source_weights == {}
        assert model.source_yield_stats == {}
        assert model.converting_role_signature == {}
        assert model.converting_samples == 0
        assert model.exploration_budget == 0.1
        assert model.feature_stats == {}

    def test_default_dicts_are_independent(self):
        model1 = LearningModel(campaign_id=CampaignId("camp-1"))
        model2 = LearningModel(campaign_id=CampaignId("camp-2"))
        assert model1.source_weights is not model2.source_weights
        assert model1.source_yield_stats is not model2.source_yield_stats
        assert model1.converting_role_signature is not model2.converting_role_signature
        assert model1.feature_stats is not model2.feature_stats


@pytest.mark.unit
class TestLearningModelCustomValues:
    """All fields accept custom values."""

    def test_full_construction(self):
        model = LearningModel(
            campaign_id=CampaignId("camp-5"),
            source_weights={"linkedin": 0.8, "indeed": 0.6},
            source_yield_stats={"linkedin": {"matches": 10, "approvals": 5, "submissions": 2}},
            converting_role_signature={"python": 1.0, "fastapi": 0.7},
            converting_samples=15,
            exploration_budget=0.25,
            feature_stats={"avg_skills": 5.2},
        )
        assert model.campaign_id == "camp-5"
        assert model.source_weights == {"linkedin": 0.8, "indeed": 0.6}
        assert model.source_yield_stats == {"linkedin": {"matches": 10, "approvals": 5, "submissions": 2}}
        assert model.converting_role_signature == {"python": 1.0, "fastapi": 0.7}
        assert model.converting_samples == 15
        assert model.exploration_budget == 0.25
        assert model.feature_stats == {"avg_skills": 5.2}

    def test_exploration_budget_accepts_float_range(self):
        model = LearningModel(campaign_id=CampaignId("camp-6"), exploration_budget=0.0)
        assert model.exploration_budget == 0.0
        model2 = LearningModel(campaign_id=CampaignId("camp-7"), exploration_budget=1.0)
        assert model2.exploration_budget == 1.0


@pytest.mark.unit
class TestLearningModelFrozen:
    """LearningModel is a frozen dataclass and cannot be mutated."""

    def test_cannot_modify_campaign_id(self):
        model = LearningModel(campaign_id=CampaignId("camp-10"))
        with pytest.raises(AttributeError):
            model.campaign_id = "camp-11"

    def test_cannot_modify_exploration_budget(self):
        model = LearningModel(campaign_id=CampaignId("camp-12"))
        with pytest.raises(AttributeError):
            model.exploration_budget = 0.5

    def test_cannot_modify_dict_field(self):
        model = LearningModel(campaign_id=CampaignId("camp-13"))
        with pytest.raises(AttributeError):
            model.source_weights = {"new": 1.0}

    def test_cannot_modify_int_field(self):
        model = LearningModel(campaign_id=CampaignId("camp-14"))
        with pytest.raises(AttributeError):
            model.converting_samples = 5


@pytest.mark.unit
class TestLearningModelFieldAccess:
    """Fields are accessible as regular attributes."""

    def test_all_fields_accessible(self):
        model = LearningModel(campaign_id=CampaignId("camp-20"))
        # Access and verify repr/str are available
        assert isinstance(model.campaign_id, str)
        assert isinstance(model.source_weights, dict)
        assert isinstance(model.source_yield_stats, dict)
        assert isinstance(model.converting_role_signature, dict)
        assert isinstance(model.converting_samples, int)
        assert isinstance(model.exploration_budget, float)
        assert isinstance(model.feature_stats, dict)

    def test_repr_includes_fields(self):
        model = LearningModel(campaign_id=CampaignId("camp-21"))
        repr_str = repr(model)
        assert "campaign_id" in repr_str
        assert "exploration_budget" in repr_str
        assert "camp-21" in repr_str

    def test_equality(self):
        model1 = LearningModel(campaign_id=CampaignId("camp-30"), exploration_budget=0.2)
        model2 = LearningModel(campaign_id=CampaignId("camp-30"), exploration_budget=0.2)
        assert model1 == model2

    def test_inequality(self):
        model1 = LearningModel(campaign_id=CampaignId("camp-31"), exploration_budget=0.2)
        model2 = LearningModel(campaign_id=CampaignId("camp-32"), exploration_budget=0.2)
        assert model1 != model2

