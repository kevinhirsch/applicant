"""Multi-campaign readiness verification (NFR-EXT-1, FR-CRIT-4, FR-LEARN-1).

Runs TWO campaigns concurrently and asserts the architecture keeps them isolated
where it must and shares knowledge where it should:

* **Isolated per campaign:** criteria, attribute-cloud *values*, learning state
  (converting-role signature + source weights), discovery-source toggles, and
  conversions — one campaign's signals never leak into the other.
* **Shared cross-campaign:** field-mapping *knowledge* (which ATS selector a label
  binds to) is learnable once and reused everywhere via a global mapping
  (``campaign_id is None``), while the attribute *values* the mapping resolves stay
  per-campaign (FR-ATTR-2).
* **Independent learning:** a conversion in campaign A shifts A's next-run bias but
  not B's.

Hermetic: in-memory storage + local embedding, no external services. Concurrency is
exercised with a thread pool to surface any shared-state leakage.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.campaign_service import CampaignService
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import LearningService
from applicant.core.entities.application import Application
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.ids import ApplicationId, JobPostingId, OutcomeEventId, new_id
from applicant.core.state_machine import ApplicationState

pytestmark = pytest.mark.integration


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def services(storage):
    base = LearningService(storage, LocalEmbedding())
    return {
        "campaigns": CampaignService(storage),
        "base": base,
        "advanced": AdvancedLearningService(base=base, storage=storage),
        "attrs": AttributeCloudService(storage),
    }


def _converted_app(storage, campaign_id, job_title, work_mode):
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=campaign_id,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        job_title=job_title,
        work_mode=work_mode,
    )
    storage.applications.add(app)
    storage.outcomes.add(
        OutcomeEvent(id=OutcomeEventId(new_id()), application_id=app.id, type="submitted")
    )
    storage.commit()
    return app


def test_two_campaigns_isolated_values_shared_mappings(storage, services):
    a = services["campaigns"].create_campaign("Campaign A")
    b = services["campaigns"].create_campaign("Campaign B")
    attrs = services["attrs"]

    # --- per-campaign attribute VALUES are isolated -----------------------
    attrs.upsert(a.id, "preferred_location", "Remote")
    attrs.upsert(b.id, "preferred_location", "Austin, TX")
    assert attrs.get_by_name(a.id, "preferred_location").value == "Remote"
    assert attrs.get_by_name(b.id, "preferred_location").value == "Austin, TX"
    # listing one campaign never returns the other's attributes
    a_names = {x.name for x in storage.attributes.list_for_campaign(a.id)}
    b_only = [x for x in storage.attributes.list_for_campaign(b.id) if x.campaign_id == a.id]
    assert "preferred_location" in a_names and not b_only

    # --- field-mapping KNOWLEDGE is shared cross-campaign (FR-ATTR-2) ------
    a_attr = attrs.get_by_name(a.id, "preferred_location")
    shared = attrs.bind_field(
        "workday", "#location", attribute_id=a_attr.id, shared=True
    )
    assert shared.is_shared is True  # campaign_id is None -> global knowledge
    # Both campaigns resolve the SAME shared mapping to THEIR OWN value.
    resolved_a = attrs.resolve_attribute_for_field(a.id, "workday", "#location")
    resolved_b = attrs.resolve_attribute_for_field(b.id, "workday", "#location")
    assert resolved_a.value == "Remote"
    assert resolved_b.value == "Austin, TX"
    # The mapping itself is single + global (not duplicated per campaign).
    assert len(storage.field_mappings.list_for_site("workday")) == 1


def test_conversion_in_one_campaign_only_shifts_that_campaign(storage, services):
    a = services["campaigns"].create_campaign("Campaign A")
    b = services["campaigns"].create_campaign("Campaign B")
    advanced, base = services["advanced"], services["base"]
    app_a = _converted_app(storage, a.id, "Senior Backend Engineer", "remote")
    advanced.record_and_persist_conversion(a.id, app_a)

    model_a = base.load_model(a.id)
    model_b = base.load_model(b.id)
    # A learned a converting-role signature; B did not (independent learning).
    assert "role:senior backend engineer" in model_a.converting_role_signature
    assert model_b.converting_role_signature == {}
    assert model_a.converting_samples == 1 and model_b.converting_samples == 0


def test_concurrent_runs_keep_learning_isolated(storage, services):
    """Two campaigns converting concurrently must not cross-contaminate (NFR-EXT-1)."""
    advanced, base, campaigns = services["advanced"], services["base"], services["campaigns"]
    a = campaigns.create_campaign("Concurrent A")
    b = campaigns.create_campaign("Concurrent B")

    app_a = _converted_app(storage, a.id, "Staff Data Engineer", "remote")
    app_b = _converted_app(storage, b.id, "Frontend Designer", "onsite")

    def run(cid, app):
        return advanced.record_and_persist_conversion(cid, app)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, a.id, app_a), pool.submit(run, b.id, app_b)]
        for f in futures:
            f.result()

    model_a = base.load_model(a.id)
    model_b = base.load_model(b.id)
    assert "role:staff data engineer" in model_a.converting_role_signature
    assert "role:frontend designer" not in model_a.converting_role_signature
    assert "role:frontend designer" in model_b.converting_role_signature
    assert "role:staff data engineer" not in model_b.converting_role_signature


def test_discovery_toggles_isolated_per_campaign(storage, services):
    from applicant.adapters.discovery.factory import build_default_discovery
    from applicant.application.services.discovery_service import DiscoveryService

    a = services["campaigns"].create_campaign("Toggle A")
    b = services["campaigns"].create_campaign("Toggle B")
    svc = DiscoveryService(storage, build_default_discovery(live=False), LocalEmbedding())
    svc.sync_registry(a.id)
    svc.sync_registry(b.id)
    svc.set_source_enabled(a.id, "jobspy:indeed", False)
    # A's toggle is off; B's persisted record stays enabled (isolated, FR-CRIT-4).
    assert storage.discovery_sources.get(a.id, "jobspy:indeed").enabled is False
    assert storage.discovery_sources.get(b.id, "jobspy:indeed").enabled is True
