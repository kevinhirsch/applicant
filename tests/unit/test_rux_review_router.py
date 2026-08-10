"""RUX-1/2/3: the /api/review router (EPIC REVIEW-UX).

Mounts JUST the review router (hermetic: ``InMemoryStorage``, no DB, no LLM -> the
material engine's deterministic truthful fallback) and drives the source link +
cached snapshot (RUX-1), the three-way Continue / Save-for-later / Discard decision
(RUX-2), and per-section / cross-section / whole-app regenerate (RUX-3) end-to-end.

The router is deliberately THIN over existing engines, so these tests assert it
COMPOSES the real services (MaterialService review gate, PendingActionsService saved
bucket, FeedbackService negative learning) rather than re-implementing anything.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


class SpyFeedback:
    """Records posting-feedback calls so we can assert the discard reason feeds
    NEGATIVE learning (RUX-2)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_posting_feedback(self, campaign_id, posting_id, *, sentiment, text):
        self.calls.append(
            {
                "campaign_id": str(campaign_id),
                "posting_id": str(posting_id),
                "sentiment": sentiment,
                "text": text,
            }
        )
        return {"folded": True, "sentiment": sentiment}


def _build(storage, material, pending, feedback) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_material_service] = lambda: material
    app.dependency_overrides[get_pending_actions_service] = lambda: pending
    app.dependency_overrides[get_feedback_service] = lambda: feedback
    app.dependency_overrides[require_llm_configured] = lambda: None
    app.include_router(review_router)
    return TestClient(app)


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def material(storage) -> MaterialService:
    # No LLM -> deterministic truthful fallback (never fabricates, never blocks).
    return MaterialService(storage, llm=None, resume_tailoring=LatexTailor(render_mode="off"))


@pytest.fixture
def pending(storage) -> PendingActionsService:
    return PendingActionsService(storage)


@pytest.fixture
def feedback() -> SpyFeedback:
    return SpyFeedback()


@pytest.fixture
def client(storage, material, pending, feedback) -> TestClient:
    return _build(storage, material, pending, feedback)


def _seed(storage, *, with_posting=True) -> tuple[CampaignId, Application, JobPosting | None]:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="Search", active=True))
    posting = None
    pid = JobPostingId(new_id())
    if with_posting:
        posting = JobPosting(
            id=pid,
            campaign_id=cid,
            title="Staff Engineer",
            company="Acme",
            source_url="https://boards.acme.example/jobs/42",
            location="Remote",
            work_mode="remote",
            salary="$220k",
            description="Build resilient distributed systems in Python.",
        )
        storage.postings.add(posting)
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=pid,
        status=ApplicationState.DIGESTED,
        role_name="Staff Engineer",
        job_title="Staff Engineer",
        work_mode="remote",
    )
    storage.applications.add(app)
    storage.commit()
    return cid, app, posting


TRUE_SOURCE = "I built Python data pipelines and led backend platform work."


# === RUX-1: source posting link + cached snapshot ==========================
@pytest.mark.unit
def test_rux1_source_returns_live_url_and_cached_snapshot(client, storage):
    _, app, posting = _seed(storage)
    r = client.get(f"/api/review/{app.id}/source")
    assert r.status_code == 200
    body = r.json()
    assert body["source_url"] == posting.source_url  # live link
    snap = body["snapshot"]
    # The cached snapshot is a readable copy captured from the ingested fields, so a
    # PULLED listing is still readable independent of the URL.
    assert snap["title"] == "Staff Engineer"
    assert snap["company"] == "Acme"
    assert snap["text"] == posting.description
    assert snap["captured_at"]


@pytest.mark.unit
def test_rux1_snapshot_is_captured_once_and_stable(client, storage):
    _, app, _ = _seed(storage)
    first = client.get(f"/api/review/{app.id}/source").json()["snapshot"]
    second = client.get(f"/api/review/{app.id}/source").json()["snapshot"]
    # Idempotent capture: same captured_at across reads (persisted, not re-captured).
    assert first["captured_at"] == second["captured_at"]


@pytest.mark.unit
def test_rux1_source_404_for_unknown_application(client):
    r = client.get(f"/api/review/{new_id()}/source")
    assert r.status_code == 404


# === RUX-2: Continue ========================================================
@pytest.mark.unit
def test_rux2_continue_approves_generated_materials_through_review_gate(
    client, storage, material
):
    cid, app, _ = _seed(storage)
    doc = material.generate_cover_letter(
        cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None and doc.approved is False  # starts review-gated

    r = client.post(f"/api/review/{app.id}/continue")
    assert r.status_code == 200
    body = r.json()
    assert body["proceeded"] is True
    assert str(doc.id) in body["approved_documents"]
    # The document is now approved through the review gate.
    assert storage.documents.get(doc.id).approved is True


# === RUX-2: Save-for-later ==================================================
@pytest.mark.unit
def test_rux2_save_for_later_moves_app_to_saved_bucket(client, storage, pending):
    cid, app, _ = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/save-for-later", json={"campaign_id": str(cid)}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["bucket"] == "saved"
    assert body["reminder_at"]  # the nudge reuses the snooze wake-time

    # Distinct bucket, out of the active queue.
    saved = client.get(f"/api/review/{cid}/saved").json()["items"]
    assert len(saved) == 1
    assert saved[0]["application_id"] == str(app.id)
    assert pending.list_pending(cid) == []  # not in the active portal


# === RUX-2: Discard-with-reason ============================================
@pytest.mark.unit
def test_rux2_discard_declines_reversibly_and_feeds_negative_learning(
    client, storage, material, feedback
):
    cid, app, posting = _seed(storage)
    doc = material.generate_cover_letter(
        cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None

    r = client.post(
        f"/api/review/{app.id}/discard",
        json={"campaign_id": str(cid), "reason": "salary too low, wrong stack"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["reversible"] is True
    assert str(doc.id) in body["declined_documents"]
    # Never deletes user data irrecoverably — the document still exists (unapproved).
    assert storage.documents.get(doc.id) is not None
    assert storage.documents.get(doc.id).approved is False
    # The reason fed a NEGATIVE learning signal via FeedbackService.
    assert feedback.calls == [
        {
            "campaign_id": str(cid),
            "posting_id": str(posting.id),
            "sentiment": "negative",
            "text": "salary too low, wrong stack",
        }
    ]


@pytest.mark.unit
def test_rux2_discard_requires_a_reason(client, storage):
    cid, app, _ = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/discard", json={"campaign_id": str(cid), "reason": "  "}
    )
    assert r.status_code == 422


# === RUX-3: per-section regenerate =========================================
@pytest.mark.unit
def test_rux3_regenerate_cover_letter_section_stays_review_gated(client, storage):
    cid, app, _ = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/regenerate/section",
        json={
            "campaign_id": str(cid),
            "kind": "cover_letter",
            "true_source": TRUE_SOURCE,
            "jd_terms": ["Python"],
            "role_requires": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["regenerated"] is True
    assert body["approved"] is False  # unapproved until human OK
    assert storage.documents.get(body["document_id"]).approved is False


@pytest.mark.unit
def test_rux3_regenerate_screening_answer_requires_a_question(client, storage):
    cid, app, _ = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/regenerate/section",
        json={"campaign_id": str(cid), "kind": "screening_answer", "true_source": TRUE_SOURCE},
    )
    assert r.status_code == 422


@pytest.mark.unit
def test_rux3_regenerate_resume_section_forks_unapproved_variant(client, storage):
    cid, app, posting = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/regenerate/section",
        json={
            "campaign_id": str(cid),
            "kind": "resume",
            "posting_id": str(posting.id),
            "true_source": "\\section{Skills}\nPython developer who built pipelines.\n",
            "jd_terms": ["Python", "Kubernetes"],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["approved"] is False  # a forked variant is review-gated


# === RUX-3: cross-section instruction + inline edit ========================
@pytest.mark.unit
def test_rux3_apply_instruction_fans_across_all_sections_review_gated(
    client, storage, material
):
    cid, app, _ = _seed(storage)
    doc = material.generate_cover_letter(
        cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None
    r = client.post(
        f"/api/review/{app.id}/apply-instruction",
        json={"campaign_id": str(cid), "instruction": "make it more concise"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["review_gated"] is True
    ids = [s["document_id"] for s in body["sections"]]
    assert str(doc.id) in ids
    assert all(s["turns"] >= 1 for s in body["sections"])
    # The edit did NOT approve the document.
    assert storage.documents.get(doc.id).approved is False


@pytest.mark.unit
def test_rux3_apply_instruction_rejects_unknown_turn_kind(client, storage):
    cid, app, _ = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/apply-instruction",
        json={"campaign_id": str(cid), "instruction": "x", "kind": "bogus"},
    )
    assert r.status_code == 422


# === RUX-3: whole-app regenerate ===========================================
@pytest.mark.unit
def test_rux3_regenerate_whole_app_regenerates_every_section_review_gated(
    client, storage
):
    cid, app, posting = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/regenerate/whole",
        json={
            "campaign_id": str(cid),
            "true_source": TRUE_SOURCE,
            "jd_terms": ["Python"],
            "posting_id": str(posting.id),
            "questions": ["Why do you want this role?"],
            "include_cover_letter": True,
            "role_requires": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["review_gated"] is True
    sections = {s["section"] for s in body["regenerated"]}
    assert {"resume", "cover_letter", "screening_answer"} <= sections
    # Nothing is approved by a regenerate.
    assert all(s.get("approved") is False for s in body["regenerated"])
