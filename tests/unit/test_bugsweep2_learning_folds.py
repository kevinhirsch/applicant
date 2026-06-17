"""Bugsweep-2 Fixes 2-4: every input folds into the per-campaign learning model.

* Fix 2 [FR-LEARN-2]: a digest APPROVE folds the approved posting's features as a
  POSITIVE taste decision (``...:approve`` buckets), not only the source-yield leg.
* Fix 3 [FR-LEARN-3]: redline add/subtract revision turns + chat taste statements
  fold a feedback signal into learning.
* Fix 4 [FR-LEARN-4 / FR-ATTR-5]: a resolved missing-attribute soft error folds a
  soft-error-resolution signal; parsed/observed inputs reconcile into the cloud
  (non-integral auto-applied, integral held for confirmation).
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.feedback_service import FeedbackService
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.material_service import MaterialService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import (
    AttributeId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    new_id,
)


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


def _approve_buckets(model) -> dict:
    return {
        feat: slot
        for feat, slot in model.feature_stats.items()
        if any(k.endswith(":approve") for k in slot)
    }


# === Fix 2: approval taste fold (FR-LEARN-2) =============================
@pytest.mark.unit
def test_digest_approve_folds_positive_taste(storage, learning, campaign):
    """FR-LEARN-2: approving a posting accrues ``...:approve`` feature buckets."""
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=campaign.id,
            title="Senior Python Engineer",
            company="Acme",
            work_mode="remote",
            source_key="rss",
            source_url="http://x",
        )
    )
    storage.commit()
    digest = DigestService(storage, notification=None, learning=learning)

    digest.approve(pid)

    model = learning.load_model(campaign.id)
    approve = _approve_buckets(model)
    # The flavor of role approved produced positive approve buckets attributable to it.
    assert "role:senior python engineer" in approve
    assert approve["role:senior python engineer"]["senior python engineer:approve"] == 1
    assert "work_mode:remote" in approve
    assert "source:rss" in approve


# === Fix 3: revision + chat feedback folds (FR-LEARN-3) =================
@pytest.mark.unit
def test_redline_turn_folds_revision_feedback(storage, learning, campaign):
    """FR-LEARN-3: an add/subtract redline turn folds a revision-feedback signal."""
    advanced = AdvancedLearningService(base=learning, storage=storage)
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=campaign.id,
        application_id=None,
        type=DocumentType.COVER_LETTER,
        content="initial body",
        approved=False,
    )
    storage.documents.add(doc)
    storage.commit()
    material = MaterialService(storage, learning=learning, advanced_learning=advanced)

    material.apply_turn(doc.id, "add", "kubernetes experience leadership")

    model = learning.load_model(campaign.id)
    approve = _approve_buckets(model)
    # The add edit folded positive ``revision:*`` taste features.
    assert any(feat.startswith("revision:") for feat in approve), approve


@pytest.mark.unit
def test_chat_taste_statement_folds_signal(storage, learning, campaign):
    """FR-LEARN-3: a chat taste statement folds a feedback signal into learning."""
    attrs = AttributeCloudService(storage)
    chat = ChatService(attribute_service=attrs, llm=None, learning=learning, storage=storage)

    chat.converse(campaign.id, "I really prefer remote backend roles")

    model = learning.load_model(campaign.id)
    assert model.feature_stats, "chat taste should fold at least one feature signal"


# === Fix 4: soft-error resolution + parsed-input reconcile (FR-LEARN-4) ==
@pytest.mark.unit
def test_resolving_missing_attr_folds_soft_error_signal(storage, learning, campaign):
    """FR-ATTR-5/FR-LEARN-4: resolving a missing attr folds a soft-error signal."""
    advanced = AdvancedLearningService(base=learning, storage=storage)
    pending = PendingActionsService(storage)
    attrs = AttributeCloudService(
        storage, pending_actions=pending, advanced_learning=advanced
    )
    # Surface then resolve a missing attribute for a known site.
    attrs.resolve_missing(
        campaign.id, "work authorization", site_key="greenhouse", field_selector="#wa"
    )
    attrs.acquire_missing(campaign.id, "work authorization", "Authorized")

    model = learning.load_model(campaign.id)
    assert "required_field:work authorization" in model.feature_stats


@pytest.mark.unit
def test_parsed_input_reconciles_into_cloud(storage, learning, campaign):
    """FR-LEARN-4: parsed input auto-applies non-integral, holds integral."""
    advanced = AdvancedLearningService(base=learning, storage=storage)
    # Seed an integral attribute so a new value for it is HELD for confirmation.
    storage.attributes.add(
        Attribute(
            id=AttributeId(new_id()),
            campaign_id=campaign.id,
            name="first name",
            value="Kev",
            is_integral=True,
        )
    )
    storage.commit()
    feedback = FeedbackService(storage, learning, advanced_learning=advanced)

    result = feedback.ingest_parsed_input(
        campaign.id,
        [
            {"name": "github", "value": "octocat", "is_integral": False, "source": "chat"},
            {"name": "first name", "value": "Kevin", "is_integral": True, "source": "chat"},
        ],
    )

    # Non-integral auto-applied; integral held (conflict, needs confirmation).
    applied = result["applied"]
    pending_or_conflict = result["pending"] + result.get("conflicts", [])
    assert "github" in applied
    assert any(p["name"] == "first name" for p in pending_or_conflict)
    # The auto-applied value is now in the cloud.
    names = {a.name for a in storage.attributes.list_for_campaign(campaign.id)}
    assert "github" in names
