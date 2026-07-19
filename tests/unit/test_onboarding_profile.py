import pytest

from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.ids import CampaignId, OnboardingProfileId


@pytest.fixture(autouse=True)
def _no_state():
    """No-op fixture for xdist parallel safety."""
    pass


@pytest.mark.unit
class TestOnboardingProfileConstruction:
    """OnboardingProfile minimal and full construction."""

    def test_minimal_construction(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-1"),
            campaign_id=CampaignId("camp-1"),
        )
        assert profile.id == "op-1"
        assert profile.campaign_id == "camp-1"
        assert profile.completion_flag is False
        assert profile.wizard_state == {}
        assert profile.intake == {}

    def test_full_construction(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-2"),
            campaign_id=CampaignId("camp-2"),
            completion_flag=True,
            wizard_state={"step": "welcome", "progress": 0.3},
            intake={"first_name": "Jane"},
        )
        assert profile.id == "op-2"
        assert profile.campaign_id == "camp-2"
        assert profile.completion_flag is True
        assert profile.wizard_state == {"step": "welcome", "progress": 0.3}
        assert profile.intake == {"first_name": "Jane"}

    def test_dict_defaults_are_separate_instances(self):
        p1 = OnboardingProfile(
            id=OnboardingProfileId("op-3"), campaign_id=CampaignId("camp-1")
        )
        p2 = OnboardingProfile(
            id=OnboardingProfileId("op-4"), campaign_id=CampaignId("camp-1")
        )
        p1.wizard_state["key"] = "val1"
        assert "key" not in p2.wizard_state
        assert p2.wizard_state == {}

    def test_completion_flag_default_false(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-5"), campaign_id=CampaignId("camp-1")
        )
        assert profile.completion_flag is False

    def test_completion_flag_can_be_true(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-6"),
            campaign_id=CampaignId("camp-1"),
            completion_flag=True,
        )
        assert profile.completion_flag is True

    def test_completion_flag_can_be_false_explicit(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-7"),
            campaign_id=CampaignId("camp-1"),
            completion_flag=False,
        )
        assert profile.completion_flag is False


@pytest.mark.unit
class TestOnboardingProfileFrozen:
    """OnboardingProfile is a frozen dataclass."""

    def test_cannot_modify_id(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-10"), campaign_id=CampaignId("camp-1")
        )
        with pytest.raises(AttributeError):
            profile.id = OnboardingProfileId("op-11")

    def test_cannot_modify_campaign_id(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-12"), campaign_id=CampaignId("camp-1")
        )
        with pytest.raises(AttributeError):
            profile.campaign_id = CampaignId("camp-2")

    def test_cannot_modify_completion_flag(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-13"), campaign_id=CampaignId("camp-1")
        )
        with pytest.raises(AttributeError):
            profile.completion_flag = True

    def test_cannot_modify_wizard_state(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-14"), campaign_id=CampaignId("camp-1")
        )
        with pytest.raises(AttributeError):
            profile.wizard_state = {"new": "dict"}

    def test_cannot_modify_intake(self):
        profile = OnboardingProfile(
            id=OnboardingProfileId("op-15"), campaign_id=CampaignId("camp-1")
        )
        with pytest.raises(AttributeError):
            profile.intake = {"new": "dict"}
