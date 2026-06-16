"""LearningService v1 unit tests (FR-DISC-5, FR-LEARN-3/4/5/6/7)."""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.learning_service import LearningService
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import AttributeId, CampaignId, new_id


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def learning(storage) -> LearningService:
    return LearningService(storage, LocalEmbedding())


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="c")
    storage.campaigns.add(c)
    storage.commit()
    return c


@pytest.mark.unit
def test_source_funnel_weights_conversions_above_matches(learning, campaign):
    """A source whose matches convert outranks a higher-volume non-converting source."""
    model = learning.model_for(campaign.id)
    model = learning.record_source_funnel(
        model,
        {
            "low_convert": {"matches": 20},
            "high_convert": {"matches": 3, "approvals": 2, "submissions": 1},
        },
    )
    ranking = learning.source_ranking(model)
    assert ranking.index("high_convert") < ranking.index("low_convert")
    assert model.source_yield_stats["high_convert"]["submissions"] == 1


@pytest.mark.unit
def test_decay_applies_across_runs(learning, campaign):
    model = learning.model_for(campaign.id)
    model = learning.record_source_yield(model, {"x": 10})
    first = model.source_weights["x"]
    model = learning.record_source_yield(model, {"x": 0})
    # Prior weight decays toward zero on a barren run.
    assert model.source_weights["x"] < first


@pytest.mark.unit
def test_converting_signature_biases_alignment(learning, campaign):
    model = learning.model_for(campaign.id)
    model = learning.record_converting_role(
        model, "senior python backend engineer fastapi postgres"
    )
    near = learning.converting_alignment(model, "python backend engineer fastapi services")
    far = learning.converting_alignment(model, "pastry chef bakery croissant")
    assert near > far
    assert model.converting_samples == 1


@pytest.mark.unit
def test_persist_and_reload_round_trips(learning, storage, campaign):
    model = learning.model_for(campaign.id)
    model = learning.record_source_funnel(model, {"jobspy:indeed": {"matches": 5, "approvals": 1}})
    model = learning.record_converting_role(model, "backend engineer")
    learning.persist_model(model)

    reloaded = learning.load_model(campaign.id)
    assert reloaded.source_weights["jobspy:indeed"] > 0
    assert reloaded.source_yield_stats["jobspy:indeed"]["approvals"] == 1
    assert reloaded.converting_samples == 1
    # And it persisted to discovery_sources for the registry/UI.
    persisted = storage.discovery_sources.list_for_campaign(campaign.id)
    assert any(s.source_key == "jobspy:indeed" for s in persisted)


@pytest.mark.unit
def test_cross_reference_auto_applies_non_integral(learning, storage, campaign):
    # FR-LEARN-4: non-integral parsed input auto-applies to the attribute cloud.
    result = learning.cross_reference_attributes(
        campaign.id, {"Preferred location": "Remote", "Years of experience": "8"}
    )
    assert len(result.applied) == 2
    assert not result.pending
    names = {a.name for a in storage.attributes.list_for_campaign(campaign.id)}
    assert "Preferred location" in names


@pytest.mark.unit
def test_cross_reference_holds_integral_for_confirmation(learning, storage, campaign):
    # FR-LEARN-4 + FR-FB-3: an integral attribute change is NOT auto-applied.
    storage.attributes.add(
        Attribute(
            id=AttributeId(new_id()),
            campaign_id=campaign.id,
            name="Full legal name",
            value="Kevin Hirsch",
            is_integral=True,
        )
    )
    storage.commit()
    result = learning.cross_reference_attributes(campaign.id, {"Full legal name": "Someone Else"})
    assert not result.applied
    assert result.pending and result.pending[0]["is_integral"] is True
    # The stored value is untouched until confirmed.
    stored = storage.attributes.list_for_campaign(campaign.id)[0]
    assert stored.value == "Kevin Hirsch"


@pytest.mark.unit
def test_cross_reference_skips_sensitive(learning, storage, campaign):
    storage.attributes.add(
        Attribute(
            id=AttributeId(new_id()),
            campaign_id=campaign.id,
            name="Gender",
            value="",
            is_sensitive=True,
        )
    )
    storage.commit()
    result = learning.cross_reference_attributes(campaign.id, {"Gender": "male"})
    assert not result.applied and not result.pending  # FR-ATTR-6: never auto-learned


@pytest.mark.unit
def test_exploration_reserves_unseen_source(learning, campaign):
    model = learning.model_for(campaign.id)
    model = learning.record_source_yield(model, {"jobspy:indeed": 5})
    exploit, explore = learning.exploration_split(
        model, ["jobspy:indeed", "jobspy:linkedin", "searxng"]
    )
    assert explore  # at least one under-used source reserved (FR-LEARN-6)
    assert "jobspy:indeed" in exploit


@pytest.mark.unit
def test_exploration_budget_zero_disables_exploration(learning, campaign):
    # FR-LEARN-6: exploration_budget == 0.0 must explore NOTHING (was forced >=1).
    from dataclasses import replace

    model = replace(learning.model_for(campaign.id), exploration_budget=0.0)
    exploit, explore = learning.exploration_split(model, ["A", "B", "C"])
    assert explore == []
    assert set(exploit) == {"A", "B", "C"}


@pytest.mark.unit
def test_exploration_split_keeps_all_cold_sources(learning, campaign):
    # FR-DISC-5: cold/unseen sources beyond the explore cap must not be dropped —
    # every source appears in exploit ∪ explore.
    from dataclasses import replace

    model = learning.model_for(campaign.id)
    model = learning.record_source_yield(model, {"indeed": 50})
    model = replace(model, exploration_budget=0.2)
    all_sources = ["indeed", "linkedin", "searxng", "rss"]
    exploit, explore = learning.exploration_split(model, all_sources)
    assert set(exploit) | set(explore) == set(all_sources)


@pytest.mark.unit
def test_source_ranking_favors_conversion_over_volume(learning, campaign):
    # FR-DISC-5: a high-volume zero-conversion source must NOT outrank a low-volume
    # converting one (ranking is by conversion, not raw match volume).
    model = learning.model_for(campaign.id)
    for _ in range(5):  # A: 50 matches/run x 5 runs, zero conversions
        model = learning.record_source_funnel(model, {"A": {"matches": 50}})
    model = learning.record_source_funnel(
        model, {"B": {"matches": 5, "approvals": 2, "submissions": 2}}
    )
    ranking = learning.source_ranking(model)
    assert ranking.index("B") < ranking.index("A")


@pytest.mark.unit
def test_concurrent_record_source_event_no_lost_update(learning, campaign):
    # FR-LEARN-1/FR-DUR-2: concurrent funnel updates for the same campaign must both
    # persist — the per-campaign lock prevents a lost read-modify-write update.
    import threading

    barrier = threading.Barrier(2)

    def record(leg: str) -> None:
        barrier.wait()  # maximize overlap of the load->fold->persist window
        learning.record_source_event(campaign.id, "indeed", leg, count=1)

    t1 = threading.Thread(target=record, args=("approvals",))
    t2 = threading.Thread(target=record, args=("submissions",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    reloaded = learning.load_model(campaign.id)
    stats = reloaded.source_yield_stats["indeed"]
    assert stats["approvals"] == 1
    assert stats["submissions"] == 1  # neither update was dropped
