"""Step bindings for the Review-UX acceptance scenarios (EPIC REVIEW-UX).

Maps RUX-1/2/3 to the real engines the review router composes — the MaterialService
review gate, the PendingActionsService saved bucket, and the FeedbackService
negative-learning seam — with NO TeX/LLM installed (deterministic truthful
fallback). Hermetic: the review router is mounted on a bare app with the driving-port
deps overridden to an in-memory bundle, mirroring the repo's service-level BDD style
(``tests/bdd/steps/test_p3_steps.py``) rather than depending on the shared wiring
(the review router's registration is owned by the Integrate step).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.deps import (
    get_feedback_service,
    get_material_service,
    get_pending_actions_service,
    get_storage,
    require_llm_configured,
)
from applicant.app.routers.review import router as review_router
from applicant.application.services.material_service import MaterialService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState

scenarios("../features/p3_review_ux.feature")

TRUE_SOURCE = "I built Python data pipelines and led backend platform work."


class _SpyFeedback:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_posting_feedback(self, campaign_id, posting_id, *, sentiment, text):
        self.calls.append({"sentiment": sentiment, "text": text})
        return {"folded": True, "sentiment": sentiment}


@pytest.fixture
def rux() -> dict:
    storage = InMemoryStorage()
    material = MaterialService(
        storage, llm=None, resume_tailoring=LatexTailor(render_mode="off")
    )
    pending = PendingActionsService(storage)
    feedback = _SpyFeedback()
    app = FastAPI()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_material_service] = lambda: material
    app.dependency_overrides[get_pending_actions_service] = lambda: pending
    app.dependency_overrides[get_feedback_service] = lambda: feedback
    app.dependency_overrides[require_llm_configured] = lambda: None
    app.include_router(review_router)
    return {
        "storage": storage,
        "material": material,
        "pending": pending,
        "feedback": feedback,
        "client": TestClient(app),
    }


def _seed_app(rux) -> None:
    storage = rux["storage"]
    cid = CampaignId(new_id())
    pid = JobPostingId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="Search", active=True))
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title="Staff Engineer",
            company="Acme",
            source_url="https://boards.acme.example/jobs/42",
            location="Remote",
            description="Build resilient distributed systems in Python.",
        )
    )
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=pid,
        status=ApplicationState.DIGESTED,
        role_name="Staff Engineer",
        job_title="Staff Engineer",
    )
    storage.applications.add(app)
    storage.commit()
    rux["campaign_id"] = cid
    rux["app_id"] = app.id
    rux["posting_id"] = pid


# --- Given -----------------------------------------------------------------
@given("an application under review with a source posting")
def app_with_posting(rux):
    _seed_app(rux)


@given("an application under review with a generated cover letter")
def app_with_cover_letter(rux):
    _seed_app(rux)
    doc = rux["material"].generate_cover_letter(
        rux["campaign_id"], rux["app_id"], TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None
    rux["doc_id"] = doc.id


# --- When ------------------------------------------------------------------
@when("the reviewer opens the source posting")
def open_source(rux):
    rux["resp"] = rux["client"].get(f"/api/review/{rux['app_id']}/source")


@when("the reviewer chooses Continue")
def choose_continue(rux):
    rux["resp"] = rux["client"].post(f"/api/review/{rux['app_id']}/continue")


@when("the reviewer chooses Save-for-later")
def choose_save(rux):
    rux["resp"] = rux["client"].post(
        f"/api/review/{rux['app_id']}/save-for-later",
        json={"campaign_id": str(rux["campaign_id"])},
    )


@when("the reviewer discards it with a reason")
def choose_discard(rux):
    rux["resp"] = rux["client"].post(
        f"/api/review/{rux['app_id']}/discard",
        json={"campaign_id": str(rux["campaign_id"]), "reason": "salary too low"},
    )


@when("the reviewer regenerates the cover letter section")
def regen_section(rux):
    rux["resp"] = rux["client"].post(
        f"/api/review/{rux['app_id']}/regenerate/section",
        json={
            "campaign_id": str(rux["campaign_id"]),
            "kind": "cover_letter",
            "true_source": TRUE_SOURCE,
            "jd_terms": ["Python"],
            "role_requires": True,
        },
    )


@when("the reviewer applies one instruction across all sections")
def apply_instruction(rux):
    rux["resp"] = rux["client"].post(
        f"/api/review/{rux['app_id']}/apply-instruction",
        json={"campaign_id": str(rux["campaign_id"]), "instruction": "be more concise"},
    )


# --- Then ------------------------------------------------------------------
@then("the live source URL is shown")
def then_live_url(rux):
    assert rux["resp"].status_code == 200
    assert rux["resp"].json()["source_url"] == "https://boards.acme.example/jobs/42"


@then("a cached snapshot of the listing is offered")
def then_snapshot(rux):
    snap = rux["resp"].json()["snapshot"]
    assert snap["title"] == "Staff Engineer"
    assert snap["text"] == "Build resilient distributed systems in Python."


@then("the generated cover letter is approved through the review gate")
def then_approved(rux):
    assert rux["resp"].status_code == 200
    assert str(rux["doc_id"]) in rux["resp"].json()["approved_documents"]
    assert rux["storage"].documents.get(rux["doc_id"]).approved is True


@then("the application appears in the Saved bucket")
def then_saved_bucket(rux):
    assert rux["resp"].status_code == 201
    items = rux["client"].get(f"/api/review/{rux['campaign_id']}/saved").json()["items"]
    assert [i["application_id"] for i in items] == [str(rux["app_id"])]


@then("it is out of the active pending queue")
def then_out_of_queue(rux):
    assert rux["pending"].list_pending(rux["campaign_id"]) == []


@then("the material is declined but not deleted")
def then_declined_not_deleted(rux):
    assert rux["resp"].status_code == 201
    body = rux["resp"].json()
    assert body["reversible"] is True
    assert str(rux["doc_id"]) in body["declined_documents"]
    doc = rux["storage"].documents.get(rux["doc_id"])
    assert doc is not None and doc.approved is False


@then("the discard reason feeds a negative learning signal")
def then_negative_learning(rux):
    assert rux["feedback"].calls == [{"sentiment": "negative", "text": "salary too low"}]


@then("a new cover letter is produced unapproved")
def then_new_unapproved(rux):
    assert rux["resp"].status_code == 201
    body = rux["resp"].json()
    assert body["regenerated"] is True
    assert body["approved"] is False
    assert rux["storage"].documents.get(body["document_id"]).approved is False


@then("every section records the revision turn")
def then_turns_recorded(rux):
    assert rux["resp"].status_code == 201
    sections = rux["resp"].json()["sections"]
    assert sections and all(s["turns"] >= 1 for s in sections)


@then("no section is approved by the edit")
def then_none_approved(rux):
    assert rux["storage"].documents.get(rux["doc_id"]).approved is False
