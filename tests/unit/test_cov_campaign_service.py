"""CampaignService behavior coverage (FR-CRIT-4): seed, clone, list, get.

Targets the previously-uncovered branches of
``applicant.application.services.campaign_service``: criteria seeding on create
(best-effort, never breaks creation), clone-as-data-op (deep field copy), and the
not-found error path. Hermetic: in-memory storage + a fake criteria service.
"""

from __future__ import annotations

import pytest

from applicant.application.services.campaign_service import CampaignService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId, new_id


class _RecordingCriteria:
    """Fake CriteriaService capturing edit_criteria calls (#6 seeding seam)."""

    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[tuple] = []
        self._raises = raises

    def edit_criteria(self, campaign_id, *, changes, confirm):
        self.calls.append((campaign_id, changes, confirm))
        if self._raises:
            raise RuntimeError("criteria store is down")


def test_list_campaigns_excludes_reserved_system_sentinel(storage):
    # Regression: the reserved "__system__" campaign exists only so instance secrets
    # (the LLM key / sandbox tokens) satisfy the credential-store's non-null campaign
    # FK. It must never surface as a real campaign in listings (/api/campaigns).
    storage.campaigns.add(
        Campaign(id=CampaignId(SYSTEM_CAMPAIGN_ID), name="System (internal)", active=False)
    )
    svc = CampaignService(storage)
    real = svc.create_campaign("Backend roles")

    ids = [c.id for c in svc.list_campaigns()]
    assert real.id in ids
    assert SYSTEM_CAMPAIGN_ID not in ids


def test_create_campaign_persists_and_commits(storage):
    svc = CampaignService(storage)
    campaign = svc.create_campaign("Backend roles")

    assert campaign.name == "Backend roles"
    # Persisted to the campaigns repo and retrievable by id.
    assert storage.campaigns.get(campaign.id) == campaign
    assert svc.get_campaign(campaign.id) == campaign


def test_create_campaign_seeds_initial_criteria_from_name(storage):
    # #6: the campaign name seeds an initial SearchCriteria (titles + human_readable)
    # via the confirmation gate so discovery/scoring have a starting point.
    criteria = _RecordingCriteria()
    svc = CampaignService(storage, criteria_service=criteria)
    campaign = svc.create_campaign("  Staff Data Engineer  ")

    assert len(criteria.calls) == 1
    cid, changes, confirm = criteria.calls[0]
    assert cid == campaign.id
    # Name is stripped and used for BOTH the title list and the human-readable text.
    assert changes == {
        "titles": ["Staff Data Engineer"],
        "human_readable": "Staff Data Engineer",
    }
    assert confirm is True


def test_create_campaign_skips_seed_for_blank_name(storage):
    # A whitespace-only name short-circuits seeding (no empty criteria written).
    criteria = _RecordingCriteria()
    svc = CampaignService(storage, criteria_service=criteria)
    campaign = svc.create_campaign("   ")

    assert campaign.name == "   "
    assert criteria.calls == []  # name.strip() is falsy -> seeding skipped


def test_create_campaign_without_criteria_service_does_not_seed(storage):
    # No criteria service wired -> creation still works, nothing seeded.
    svc = CampaignService(storage)
    campaign = svc.create_campaign("Frontend")
    assert storage.campaigns.get(campaign.id) is not None


def test_seed_failure_never_breaks_creation(storage):
    # Best-effort seeding: a raising criteria service must not fail create_campaign.
    criteria = _RecordingCriteria(raises=True)
    svc = CampaignService(storage, criteria_service=criteria)

    campaign = svc.create_campaign("Resilient Campaign")  # must not raise
    assert storage.campaigns.get(campaign.id) is not None
    assert len(criteria.calls) == 1  # it was attempted


def test_set_criteria_service_enables_seeding_after_construction(storage):
    # The criteria service can be wired post-construction (container ordering).
    svc = CampaignService(storage)  # constructed without it
    criteria = _RecordingCriteria()
    svc.set_criteria_service(criteria)

    svc.create_campaign("Late Wiring")
    assert len(criteria.calls) == 1


def test_list_campaigns_returns_all_created(storage):
    svc = CampaignService(storage)
    a = svc.create_campaign("A")
    b = svc.create_campaign("B")
    listed = svc.list_campaigns()
    ids = {c.id for c in listed}
    assert {a.id, b.id} <= ids
    assert len(listed) >= 2


def test_get_campaign_returns_none_for_unknown_id(storage):
    svc = CampaignService(storage)
    assert svc.get_campaign(CampaignId(new_id())) is None


def test_clone_campaign_copies_fields_with_new_identity(storage):
    # clone is a data op: a fresh id + new name, every other field copied.
    svc = CampaignService(storage)
    source = svc.create_campaign("Original")
    # Mutate a couple of non-default fields so the copy is observable.
    import dataclasses

    source = dataclasses.replace(
        source, run_mode=RunMode.FIXED_DURATION, throughput_target=7, exploration_budget=0.25
    )
    storage.campaigns.add(source)
    storage.commit()

    clone = svc.clone_campaign(source.id, "Cloned")

    assert clone.id != source.id  # new identity
    assert clone.name == "Cloned"
    # All other data fields carried over verbatim.
    assert clone.run_mode == RunMode.FIXED_DURATION
    assert clone.throughput_target == 7
    assert clone.exploration_budget == 0.25
    # The clone is persisted and the source is untouched.
    assert storage.campaigns.get(clone.id) == clone
    assert storage.campaigns.get(source.id).name == "Original"


def test_clone_campaign_raises_keyerror_for_missing_source(storage):
    svc = CampaignService(storage)
    missing = CampaignId(new_id())
    with pytest.raises(KeyError, match=str(missing)):
        svc.clone_campaign(missing, "Nope")


def test_clone_does_not_invoke_criteria_seeding(storage):
    # clone copies criteria as data; it must NOT re-run the seeding edit gate.
    criteria = _RecordingCriteria()
    svc = CampaignService(storage, criteria_service=criteria)
    source = svc.create_campaign("Seeded")
    seed_calls = len(criteria.calls)

    svc.clone_campaign(source.id, "Clone Of Seeded")
    assert len(criteria.calls) == seed_calls  # no extra seeding on clone
