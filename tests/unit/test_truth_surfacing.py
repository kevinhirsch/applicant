"""P1-13 review surfacing: flagged facts reach the review surface (H4).

The truth gate's BALANCED policy surfaces unsupported claims instead of
blocking (the P1-13 core). These tests pin the SURFACING contract the review
UI consumes:

* flags are DERIVED, never stored — recomputed against the CLEAN truth cloud
  (attributes + base résumé, not the content itself) on every review open and
  every turn — so confirming a fact into the profile clears its flag on the
  next look, with no cache to invalidate;
* the flags ride ``RevisionSession.redline_state`` (already serialized by the
  documents router verbatim), so reachability is the existing review payload;
* a résumé variant records its generation-time flags in the free
  ``fit_scores`` dict (the degraded-draft precedent — no migration).
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.material_service import MaterialService
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    new_id,
)
from applicant.ports.driven.llm import LLMResult


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def svc(storage) -> MaterialService:
    return MaterialService(storage, llm=None, resume_tailoring=LatexTailor())


def _stored_doc(storage, content: str) -> GeneratedDocument:
    """Persist a cover letter directly (the surfacing tests exercise review,
    not generation, so the content is planted as-is), with a minimal REAL
    profile seeded — an empty cloud can verify nothing and derives no flags."""
    cid = CampaignId(new_id())
    storage.attributes.add(
        Attribute(
            id=AttributeId(new_id()),
            campaign_id=cid,
            name="Skills",
            value="I built Python data pipelines",
        )
    )
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=cid,
        application_id=ApplicationId(new_id()),
        type=DocumentType.COVER_LETTER,
        content=content,
        approved=False,
    )
    storage.documents.add(doc)
    storage.commit()
    return doc


@pytest.mark.unit
def test_open_revision_surfaces_flagged_facts_in_redline_state(storage, svc):
    """Opening review derives the unsupported claims and exposes them in the
    session's redline_state — the payload the review UI already receives."""
    doc = _stored_doc(storage, "Certified Snowflake administrator since 2019.")

    session = svc.open_revision(doc.id)

    flags = session.redline_state.get("flagged_facts")
    assert flags, "an unsupported entity claim must surface at review-open"
    joined = " ".join(flags).lower()
    assert "snowflake" in joined
    # Serializable as-is: the router returns redline_state verbatim.
    assert all(isinstance(f, str) for f in flags)


@pytest.mark.unit
def test_confirming_the_fact_into_the_profile_clears_the_flag_on_reopen(storage, svc):
    """The one-tap loop: the user says "that's true", the attribute lands in
    the cloud, and the NEXT review open no longer flags it — because the flags
    are derived fresh, not stored."""
    doc = _stored_doc(storage, "Certified Snowflake administrator since 2019.")
    first = svc.open_revision(doc.id)
    assert first.redline_state.get("flagged_facts")

    storage.attributes.add(
        Attribute(
            id=AttributeId(new_id()),
            campaign_id=doc.campaign_id,
            name="Snowflake",
            value="Certified Snowflake administrator since 2019",
        )
    )
    storage.commit()

    reopened = svc.open_revision(doc.id)
    assert not reopened.redline_state.get("flagged_facts"), (
        "a fact confirmed into the profile must stop being flagged"
    )


@pytest.mark.unit
def test_turns_recompute_the_flag_surface_on_the_new_content(storage, svc):
    """Every turn re-derives the flags against the post-turn content, so the
    surface never goes stale mid-review (and never breaks the turn)."""
    doc = _stored_doc(storage, "Certified Snowflake administrator since 2019.")
    svc.open_revision(doc.id)

    session = svc.apply_turn(doc.id, "free_text", "tighten the wording")

    state = session.redline_state
    assert "content" in state
    flags = state.get("flagged_facts") or []
    if state["content"].lower().find("snowflake") != -1:
        assert any("snowflake" in f.lower() for f in flags), (
            "the claim is still in the content, so it must still be flagged"
        )
    else:  # the revision dropped the claim — the flag must be gone with it
        assert not any("snowflake" in f.lower() for f in flags)


class _FabricatingLLM:
    """Injects a skill the candidate never had into the generated variant."""

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, **kwargs):
        return LLMResult(text="Seasoned expert in Kubernetes and Rust.", tier=1, model="fake")


@pytest.mark.unit
def test_variant_generation_stashes_flagged_facts_in_fit_scores(storage):
    """A generated résumé variant records its generation-time flags in the
    free ``fit_scores`` dict so the variant's review card can surface them."""
    svc = MaterialService(storage, llm=_FabricatingLLM(), resume_tailoring=LatexTailor())
    cid = CampaignId(new_id())

    sel = svc.select_or_generate(
        cid, JobPostingId(new_id()), ["Python"], "I built Python data pipelines."
    )

    assert sel.generated is True
    flags = (sel.variant.fit_scores or {}).get(MaterialService.FLAGGED_FACTS_KEY)
    assert flags, "generation-time flags must persist on the variant"
    joined = " ".join(flags).lower()
    assert "kubernetes" in joined or "rust" in joined
    # The degraded-draft key still has its slot when needed (shared dict).
    assert isinstance(sel.variant.fit_scores, dict)


@pytest.mark.unit
def test_truthful_material_surfaces_no_flags(storage, svc):
    """No unsupported claims ⇒ no flagged_facts key at all — the absence of a
    warning is itself honest (nothing renders when there is nothing to say)."""
    cid = CampaignId(new_id())
    storage.attributes.add(
        Attribute(
            id=AttributeId(new_id()),
            campaign_id=cid,
            name="Skills",
            value="I built Python data pipelines",
        )
    )
    storage.commit()
    doc = svc.generate_cover_letter(
        cid, new_id(), "I built Python data pipelines.", ["Python"], role_requires=True
    )
    session = svc.open_revision(doc.id)
    assert "flagged_facts" not in session.redline_state


@pytest.mark.unit
def test_an_empty_profile_derives_no_flags_at_all(storage, svc):
    """With NOTHING in the profile there is nothing to verify against: the
    surface stays silent instead of flagging every entity in the draft."""
    doc = GeneratedDocument(
        id=GeneratedDocumentId(new_id()),
        campaign_id=CampaignId(new_id()),
        application_id=ApplicationId(new_id()),
        type=DocumentType.COVER_LETTER,
        content="Certified Snowflake administrator since 2019.",
        approved=False,
    )
    storage.documents.add(doc)
    storage.commit()
    session = svc.open_revision(doc.id)
    assert "flagged_facts" not in session.redline_state
