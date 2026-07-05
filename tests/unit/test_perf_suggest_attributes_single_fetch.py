"""Regression coverage for performance lens 03 (round 2): ``AdvancedLearningService.
suggest_attributes`` (``application/services/learning_advanced.py``, #273) called
``self._storage.attributes.list_for_campaign(campaign_id)`` TWICE back-to-back — once
to build the existing-names set, once more (identical query) to build the
existing-values set. This runs on the polled setup-status path (perf lens 03 #29
already flags the surrounding cost).

The fix fetches the attribute list once and derives both sets from it.

FAIL-BEFORE: on the pre-fix tree (verified by hand — file-copy the pre-fix
``learning_advanced.py`` back in, rerun, see the call-count assertion fail with 2
instead of 1, then restore) this pins the single-fetch AND that the suggestion
output (which skills get proposed vs excluded as already-known) is unchanged.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import LearningService
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.ids import AttributeId, CampaignId, OnboardingProfileId, new_id


class _CountingAttributeRepo:
    def __init__(self, inner):
        self._inner = inner
        self.list_for_campaign_calls = 0

    def list_for_campaign(self, campaign_id):
        self.list_for_campaign_calls += 1
        return self._inner.list_for_campaign(campaign_id)

    def add(self, attribute):
        return self._inner.add(attribute)

    def get(self, *a, **kw):
        return self._inner.get(*a, **kw)


class _FakeEmbedding:
    def similarity(self, a, b):
        return 0.5


@pytest.mark.unit
def test_suggest_attributes_fetches_attributes_exactly_once():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    # An existing attribute for "react" (by VALUE) — must be excluded from proposals.
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="skill", value="react")
    )
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            intake={
                "base_resume": {
                    "raw_text": (
                        "Experienced with Python, React, and Kubernetes in production."
                    )
                }
            },
        )
    )
    storage.commit()

    counting = _CountingAttributeRepo(storage.attributes)
    storage.attributes = counting

    base = LearningService(storage, _FakeEmbedding())
    svc = AdvancedLearningService(base=base, storage=storage)

    proposals = svc.suggest_attributes(cid)

    assert counting.list_for_campaign_calls == 1, (
        "must fetch the campaign's attributes exactly once, not twice"
    )
    proposed_values = {p.value for p in proposals}
    # Behavior parity: python + kubernetes are new (proposed); react is already an
    # attribute VALUE on file, so it must be excluded.
    assert "python" in proposed_values
    assert "kubernetes" in proposed_values
    assert "react" not in proposed_values
