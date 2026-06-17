"""FR-RESUME-7: the redline refinement loop is budget-capped.

After ``REFINEMENT_BUDGET`` turns the add/subtract/free-text loop must stop making
autonomous revisions and route back to review: further turns become no-ops that
neither change the document nor advance the revision, so the human still drives
approve/decline. This guards against the loop churning the document forever.

Kept in its own file so it does not collide with the broader material-service
suite. Mirrors that suite's in-memory + LatexTailor setup.
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.material_service import (
    REFINEMENT_BUDGET,
    MaterialService,
)
from applicant.core.entities.revision_session import RevisionStatus
from applicant.core.ids import CampaignId, new_id


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def svc(storage) -> MaterialService:
    return MaterialService(storage, llm=None, resume_tailoring=LatexTailor())


def _doc(svc):
    cid = CampaignId(new_id())
    return svc.generate_cover_letter(
        cid, new_id(), "I built Python data pipelines.", ["Python"], role_requires=True
    )


@pytest.mark.unit
def test_turns_past_budget_route_to_review_and_refuse_further_revision(svc):
    doc = _doc(svc)

    # Spend the whole refinement budget on real (truthful) turns.
    last = None
    for i in range(REFINEMENT_BUDGET):
        last = svc.apply_turn(doc.id, "free_text", f"tighten the wording, pass {i}")
    assert last is not None
    assert len(last.turns) == REFINEMENT_BUDGET
    content_at_budget = (last.redline_state or {}).get("content")

    # One more turn (REFINEMENT_BUDGET + 1): the loop must refuse further revision.
    # It stays OPEN (so the human can still approve/decline) but the turn is a
    # no-op that re-routes to review rather than mutating the document.
    over = svc.apply_turn(doc.id, "add", "Expert in Kubernetes orchestration")
    assert over.status is RevisionStatus.OPEN
    assert len(over.turns) == REFINEMENT_BUDGET + 1
    # The over-budget turn does not change the document content.
    assert (over.redline_state or {}).get("content") == content_at_budget
    # And it tells the user to approve or decline (routes to review).
    assert "approve or decline" in over.turns[-1].ai_response.lower()


@pytest.mark.unit
def test_over_budget_turn_skips_fabrication_revision_entirely(svc):
    """A would-be fabricating turn past budget is a no-op, not a revision.

    Because the over-budget turn never revises, it never even reaches the
    fabrication guardrail — the document is left untouched and review-bound.
    """
    doc = _doc(svc)
    for i in range(REFINEMENT_BUDGET):
        svc.apply_turn(doc.id, "free_text", f"pass {i}")

    # This add WOULD be a fabrication if applied; past budget it is simply ignored.
    over = svc.apply_turn(
        doc.id, "add", "Led a 50-person Kubernetes platform team",
        true_source="I built Python data pipelines.",
    )
    assert over.status is RevisionStatus.OPEN
    assert "approve or decline" in over.turns[-1].ai_response.lower()
    stored = svc._storage.documents.get(doc.id)
    assert "Kubernetes" not in (stored.content or "")
