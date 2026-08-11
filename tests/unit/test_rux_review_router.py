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

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.deps import (
    get_digest_service,
    get_feedback_service,
    get_material_service,
    get_pending_actions_service,
    get_storage,
    require_llm_configured,
)
from applicant.app.routers.review import router as review_router
from applicant.application.services.digest_service import DigestService
from applicant.application.services.material_service import MaterialService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    ResumeVariantId,
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


def _build(storage, material, pending, feedback, digest) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_material_service] = lambda: material
    app.dependency_overrides[get_pending_actions_service] = lambda: pending
    app.dependency_overrides[get_feedback_service] = lambda: feedback
    app.dependency_overrides[get_digest_service] = lambda: digest
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
def digest(storage) -> DigestService:
    # notification=None: draft-from-posting only exercises approve()/_application_for()
    # / _close_loop(), all of which are None-safe for the optional notification/
    # pending/learning ports (best-effort side effects — see their docstrings).
    return DigestService(storage, notification=None)


@pytest.fixture
def client(storage, material, pending, feedback, digest) -> TestClient:
    return _build(storage, material, pending, feedback, digest)


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


def _seed_posting_only(storage) -> tuple[CampaignId, JobPosting]:
    """A bare POSTING with no application drafted yet (the digest-row shape)."""
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="Search", active=True))
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Platform Engineer",
        company="Globex",
        source_url="https://boards.globex.example/jobs/7",
        location="Remote",
        work_mode="remote",
        salary="$200k",
        description="Own the platform.",
    )
    storage.postings.add(posting)
    storage.commit()
    return cid, posting


# === RUX-1 fix D: draft-from-posting (digest/top-match "Review" 404 fix) ===
@pytest.mark.unit
def test_draft_from_posting_creates_a_real_application(client, storage):
    cid, posting = _seed_posting_only(storage)
    assert storage.applications.get_by_posting(cid, posting.id) is None  # nothing drafted yet

    r = client.post(f"/api/review/posting/{posting.id}/draft", json={"campaign_id": str(cid)})
    assert r.status_code == 201
    body = r.json()
    assert body["drafted"] is True
    assert body["posting_id"] == str(posting.id)
    app_id = body["application_id"]
    # A REAL, distinct application id -- never the posting id passed off as one
    # (the exact defect: digest.html used to fall back to row.posting_id).
    assert app_id and app_id != str(posting.id)

    created = storage.applications.get(ApplicationId(app_id))
    assert created is not None
    assert str(created.posting_id) == str(posting.id)

    # The freshly drafted application now opens through the review surface -- the
    # very 404 ("no such application") this fix closes.
    r2 = client.get(f"/api/review/{app_id}/source")
    assert r2.status_code == 200


@pytest.mark.unit
def test_draft_from_posting_is_idempotent(client, storage):
    cid, posting = _seed_posting_only(storage)
    first = client.post(
        f"/api/review/posting/{posting.id}/draft", json={"campaign_id": str(cid)}
    ).json()
    second = client.post(
        f"/api/review/posting/{posting.id}/draft", json={"campaign_id": str(cid)}
    ).json()
    # A second "Review" click on the same un-drafted row must not create a duplicate
    # application -- both resolve to the same real application id.
    assert first["application_id"] == second["application_id"]


@pytest.mark.unit
def test_draft_from_posting_404_for_unknown_posting(client):
    r = client.post(
        f"/api/review/posting/{new_id()}/draft", json={"campaign_id": str(new_id())}
    )
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


# === RUX-3 (fix A): the sections endpoint — this is what unblocks the panel ===
@pytest.mark.unit
def test_rux3_sections_endpoint_returns_generated_documents(client, storage, material):
    cid, app, _ = _seed(storage)
    doc = material.generate_cover_letter(
        cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None
    r = client.get(f"/api/review/{app.id}/sections")
    assert r.status_code == 200
    sections = r.json()["sections"]
    assert len(sections) == 1
    s = sections[0]
    # The shape the panel's x-for + textarea bind against.
    assert s["section_id"] == str(doc.id)
    assert s["label"]  # human-friendly label, not the raw enum value
    assert s["content"] == doc.content
    assert s["status"] == "pending"  # unapproved draft
    assert s["kind"] == "cover_letter"


@pytest.mark.unit
def test_rux3_sections_endpoint_empty_for_app_with_no_drafts(client, storage):
    _, app, _ = _seed(storage)
    r = client.get(f"/api/review/{app.id}/sections")
    assert r.status_code == 200
    assert r.json()["sections"] == []


def _seed_with_variant(storage, *, approved=False, coverage=0.5):
    """An application with a LINKED, GENERATED résumé variant (P1 résumé-in-review:
    the résumé never appeared in /sections even though Continue silently approves it).
    """
    cid, app, posting = _seed(storage)
    variant = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path="variants/test.tex",
        targeted_jd_signature="Python,Kubernetes",
        approved=approved,
        fit_scores={"coverage": coverage},
    )
    storage.resume_variants.add(variant)
    app = dataclasses.replace(app, resume_variant_id=variant.id)
    storage.applications.add(app)
    storage.commit()
    return cid, app, posting, variant


# === P1: résumé-variant-in-review (never appeared in /sections) ============
@pytest.mark.unit
def test_p1_resume_variant_appears_in_sections(client, storage):
    _, app, _, variant = _seed_with_variant(storage, coverage=0.75)
    r = client.get(f"/api/review/{app.id}/sections")
    assert r.status_code == 200
    sections = r.json()["sections"]
    resume = next((s for s in sections if s["kind"] == "resume"), None)
    assert resume is not None, "the linked résumé variant must appear in /sections"
    assert resume["section_id"] == str(variant.id)
    assert resume["variant_id"] == str(variant.id)
    assert resume["label"] == "Résumé"
    assert resume["status"] == "pending"
    assert resume["approved"] is False
    assert "75%" in resume["content"]


@pytest.mark.unit
def test_p1_resume_variant_status_reflects_approval(client, storage):
    _, app, _, variant = _seed_with_variant(storage, approved=True)
    resume = next(
        s for s in client.get(f"/api/review/{app.id}/sections").json()["sections"]
        if s["kind"] == "resume"
    )
    assert resume["status"] == "approved"
    assert resume["approved"] is True


@pytest.mark.unit
def test_p1_resume_variant_alongside_cover_letter(client, storage, material):
    cid, app, _, variant = _seed_with_variant(storage)
    doc = material.generate_cover_letter(cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True)
    assert doc is not None
    sections = client.get(f"/api/review/{app.id}/sections").json()["sections"]
    kinds = {s["kind"] for s in sections}
    assert kinds == {"cover_letter", "resume"}


@pytest.mark.unit
def test_p1_resume_variant_omitted_when_app_has_none_linked(client, storage):
    _, app, _ = _seed(storage)  # no resume_variant_id
    sections = client.get(f"/api/review/{app.id}/sections").json()["sections"]
    assert all(s["kind"] != "resume" for s in sections)


@pytest.mark.unit
def test_p1_continue_still_approves_the_resume_variant_shown_in_sections(client, storage):
    # Regression guard: Continue already approves the linked variant (RUX-2) -- this
    # fix only makes it VISIBLE beforehand; it must not change Continue's behavior.
    _, app, _, variant = _seed_with_variant(storage)
    r = client.post(f"/api/review/{app.id}/continue")
    assert r.status_code == 200
    assert r.json()["approved_variant"] == str(variant.id)
    resume = next(
        s for s in client.get(f"/api/review/{app.id}/sections").json()["sections"]
        if s["kind"] == "resume"
    )
    assert resume["status"] == "approved"


@pytest.mark.unit
def test_p1_resume_variant_is_regeneratable_via_section_id(client, storage):
    # "Regeneratable": the panel's generic per-section button sends section_id --
    # the engine must route a résumé section_id to select_or_generate (a variant is
    # selected/forked, not free-text revised in place).
    cid, app, posting, variant = _seed_with_variant(storage)
    r = client.post(
        f"/api/review/{app.id}/regenerate/section",
        json={
            "campaign_id": str(cid),
            "section_id": str(variant.id),
            "true_source": "\\section{Skills}\nPython developer who built pipelines.\n",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["regenerated"] is True
    assert body["review_gated"] is True
    assert body["section"]["kind"] == "resume"
    assert body["section"]["approved"] is False  # freshly (re)generated -> unapproved


@pytest.mark.unit
def test_p1_resume_variant_edit_section_is_a_clear_422_not_a_404(client, storage):
    # Inline text edit isn't a résumé concept (file-rendered, not free-text) -- this
    # must be an honest, actionable error, not a confusing bare 404.
    _, app, _, variant = _seed_with_variant(storage)
    r = client.post(
        f"/api/review/{app.id}/edit-section",
        json={"section_id": str(variant.id), "content": "new text"},
    )
    assert r.status_code == 422
    assert "Regenerate" in r.json()["detail"]


@pytest.mark.unit
def test_rux1_source_also_carries_sections_and_rendered_html(client, storage, material):
    cid, app, posting = _seed(storage)
    doc = material.generate_cover_letter(
        cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None
    body = client.get(f"/api/review/{app.id}/source").json()
    # RUX-1 fix C: top-level freshness + title/company + a rendered snapshot html.
    assert body["title"] == "Staff Engineer"
    assert body["company"] == "Acme"
    assert body["snapshot_available"] is True
    assert "posted_relative" in body and "posted_stale" in body
    assert isinstance(body["html"], str) and "Acme" in body["html"]
    # RUX-3 fix A: loadReview()'s single get() call now carries the sections too.
    ids = [s["section_id"] for s in body["sections"]]
    assert str(doc.id) in ids


# === RUX-1 (fix C): posting-keyed cached snapshot (the Digest snapshot button) ===
@pytest.mark.unit
def test_rux1_posting_snapshot_returns_rendered_html(client, storage):
    _, _, posting = _seed(storage)
    r = client.get(f"/api/review/posting/{posting.id}/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["html"], str)
    assert "Staff Engineer" in body["html"] and "Acme" in body["html"]
    assert body["snapshot"]["title"] == "Staff Engineer"


@pytest.mark.unit
def test_rux1_posting_snapshot_404_for_unknown_posting(client):
    r = client.get(f"/api/review/posting/{new_id()}/snapshot")
    assert r.status_code == 404


# === RUX-3 (fix B.1): regenerate one section by id, in place, review-gated ======
@pytest.mark.unit
def test_rux3_regenerate_section_by_id_stays_in_place_and_review_gated(
    client, storage, material
):
    cid, app, _ = _seed(storage)
    doc = material.generate_cover_letter(
        cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None
    r = client.post(
        f"/api/review/{app.id}/regenerate/section",
        json={"campaign_id": str(cid), "section_id": str(doc.id), "instruction": "tighten it"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["review_gated"] is True
    # Consistent singular {section_id, content, status} shape the panel merges.
    assert body["section"]["section_id"] == str(doc.id)  # same id — edited in place
    assert "content" in body["section"] and "status" in body["section"]
    # A regenerate never approves.
    assert storage.documents.get(doc.id).approved is False


@pytest.mark.unit
def test_rux3_regenerate_section_by_id_404_for_unknown_section(client, storage):
    cid, app, _ = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/regenerate/section",
        json={"campaign_id": str(cid), "section_id": new_id()},
    )
    assert r.status_code == 404


# === RUX-3 (fix B.3): apply-instruction items carry section_id + label =========
@pytest.mark.unit
def test_rux3_apply_instruction_items_carry_section_id_and_label(
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
    for s in body["sections"]:
        # x-for :key="section.section_id" needs section_id; the header needs label.
        assert s["section_id"]
        assert s["label"]
        assert "content" in s and "status" in s
        assert s["turns"] >= 1  # kept for the existing turn-recorded assertion


# === RUX-3 (fix B.2): whole-app regenerate with empty feedback (panel mode) ====
@pytest.mark.unit
def test_rux3_regenerate_whole_panel_mode_refreshes_in_place_no_feedback(
    client, storage, material
):
    cid, app, _ = _seed(storage)
    doc = material.generate_cover_letter(
        cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None
    # No posting_id / questions / true_source and empty instruction — the "Regenerate
    # whole app" button with no typed feedback used to 400; now it refreshes in place.
    r = client.post(
        f"/api/review/{app.id}/regenerate/whole",
        json={"campaign_id": str(cid), "instruction": ""},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["review_gated"] is True
    ids = [s["section_id"] for s in body["sections"]]
    assert str(doc.id) in ids  # the existing section is returned, same id
    assert storage.documents.get(doc.id).approved is False  # never approved


# === RUX-3 (fix B.4): inline edit persists a manual section edit, review-gated ==
@pytest.mark.unit
def test_rux3_edit_section_persists_manual_edit_unapproved(client, storage, material):
    cid, app, _ = _seed(storage)
    doc = material.generate_cover_letter(
        cid, app.id, TRUE_SOURCE, ["Python"], role_requires=True
    )
    assert doc is not None
    r = client.post(
        f"/api/review/{app.id}/edit-section",
        json={"section_id": str(doc.id), "content": "My own edited cover letter text."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["section"]["section_id"] == str(doc.id)
    stored = storage.documents.get(doc.id)
    assert stored.content == "My own edited cover letter text."
    assert stored.approved is False  # an edit is unreviewed — never auto-approved


@pytest.mark.unit
def test_rux3_edit_section_404_for_unknown_section(client, storage):
    _, app, _ = _seed(storage)
    r = client.post(
        f"/api/review/{app.id}/edit-section",
        json={"section_id": new_id(), "content": "x"},
    )
    assert r.status_code == 404
