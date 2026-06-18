"""Coverage: documents ROUTER (src/applicant/app/routers/documents.py).

Targets the router branches the existing integration suite leaves uncovered: the index,
``list_for_application`` (incl. the all-approved gate flag), the deterministic redline
(FR-RESUME-8), the deferred-essay handoff (#4), variant-approve incl. the 404, the
invalid-turn-kind 422, and document decline. Hermetic: in-memory storage, no TeX/LLM. The
final test also exercises the module-level ``_material_service`` fallback directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        # Open the LLM gate (FR-UI-5) so the documents router is reachable.
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_index(client):
    res = client.get("/api/documents")
    assert res.status_code == 200
    assert res.json() == {"surface": "documents", "phase": 3, "status": "live"}


def test_list_for_application_empty_is_all_approved(client):
    # No docs for an application -> all_approved defaults True (nothing blocks the gate).
    res = client.get("/api/documents/applications/app-none/")
    assert res.status_code == 200
    body = res.json()
    assert body["application_id"] == "app-none"
    assert body["items"] == []
    assert body["all_approved"] is True


def test_list_for_application_reflects_generated_unapproved_doc(client):
    cid, aid = "camp-docs-1", "app-docs-1"
    # Generate a screening answer (real document, stored unapproved).
    made = client.post(
        "/api/documents/screening-answer",
        json={
            "campaign_id": cid,
            "application_id": aid,
            "question": "Why this role?",
            "true_source": "I love building data platforms.",
        },
    )
    assert made.status_code == 201
    doc_id = made.json()["id"]

    listing = client.get(f"/api/documents/applications/{aid}/").json()
    assert len(listing["items"]) == 1
    assert listing["items"][0]["id"] == doc_id
    assert listing["items"][0]["approved"] is False
    # An unapproved doc means the gate is NOT all-approved.
    assert listing["all_approved"] is False


def _seed_profile(client, cid):
    """Seed attributes so the server-derived true_source is substantive."""
    from applicant.core.entities.attribute import Attribute
    from applicant.core.ids import AttributeId, CampaignId, new_id

    storage = client.app.state.container.storage
    for name, value in (
        ("Full Name", "Jordan Mercer"),
        ("Current Job Title", "Data Engineer"),
        ("Skills", "Python, SQL, building data pipelines and analytics dashboards"),
    ):
        storage.attributes.add(
            Attribute(id=AttributeId(new_id()), campaign_id=CampaignId(cid), name=name, value=value)
        )
    storage.commit()


def test_screening_answer_derives_true_source_when_omitted(client):
    """FR-ANSWER-1 on-demand: the front-door sends just the question; the truthful
    ground-truth is built server-side from the profile (no résumé blob from the UI)."""
    cid, aid = "camp-gen-1", "app-gen-1"
    _seed_profile(client, cid)
    made = client.post(
        "/api/documents/screening-answer",
        json={"campaign_id": cid, "application_id": aid, "question": "Why this role?"},
    )
    assert made.status_code == 201
    body = made.json()
    assert body["type"] == "screening_answer"
    assert body["approved"] is False
    # It lands in the review list (review-gated before any use).
    listing = client.get(f"/api/documents/applications/{aid}/").json()
    assert any(i["id"] == body["id"] for i in listing["items"])


def test_cover_letter_on_demand_derives_true_source(client):
    """FR-RESUME-10 on-demand: role_requires forces generation; true_source derived."""
    cid, aid = "camp-gen-2", "app-gen-2"
    _seed_profile(client, cid)
    res = client.post(
        "/api/documents/cover-letter",
        json={"campaign_id": cid, "application_id": aid, "role_requires": True},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["generated"] is True
    assert body["type"] == "cover_letter"
    assert body["approved"] is False


def test_redline_renders_additions_and_subtractions(client):
    res = client.post(
        "/api/documents/redline",
        json={
            "variant_id": "var-1",
            "base_source": "Line A\nLine B\nLine C",
            "new_source": "Line A\nLine B2\nLine C\nLine D",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["variant_id"] == "var-1"
    # "Line B" -> "Line B2" is a replace (sub + add); "Line D" is an addition.
    assert "Line D" in body["additions"]
    assert "Line B2" in body["additions"]
    assert "Line B" in body["subtractions"]
    assert "redline" in body["rendered_html"]


def test_deferred_essay_generates_and_reviews(client):
    cid, aid = "camp-docs-2", "app-docs-2"
    res = client.post(
        "/api/documents/deferred-essay",
        json={
            "campaign_id": cid,
            "application_id": aid,
            "true_source": "I shipped a payments platform end to end.",
            "label": "Describe a hard project",
            "selector": "#essay-1",
            "url": "https://acme.example/apply",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["id"]
    assert body["approved"] is False  # routed to review, not auto-approved.
    assert "content" in body


def test_invalid_turn_kind_is_422(client):
    cid, aid = "camp-docs-3", "app-docs-3"
    made = client.post(
        "/api/documents/screening-answer",
        json={"campaign_id": cid, "application_id": aid, "question": "Q?", "true_source": "S."},
    )
    doc_id = made.json()["id"]
    # An unknown turn kind -> InvalidInput -> 422 (mandatory FR-RESUME-8 validation).
    res = client.post(
        f"/api/documents/{doc_id}/turn",
        json={"kind": "bogus", "instruction": "do it"},
    )
    assert res.status_code == 422
    assert "kind" in res.json()["detail"]


def test_decline_keeps_document_unapproved(client):
    cid, aid = "camp-docs-4", "app-docs-4"
    made = client.post(
        "/api/documents/screening-answer",
        json={"campaign_id": cid, "application_id": aid, "question": "Q?", "true_source": "S."},
    )
    doc_id = made.json()["id"]
    res = client.post(f"/api/documents/{doc_id}/decline")
    assert res.status_code == 201
    assert res.json()["approved"] is False


def test_approve_variant_404_for_unknown_variant(client):
    res = client.post("/api/documents/variants/no-such-variant/approve")
    assert res.status_code == 404
    assert "no such variant" in res.json()["detail"]


def test_approve_variant_succeeds_for_existing_variant(client):
    """Seed a real ResumeVariant in storage, then approve it through the router."""
    from applicant.core.entities.resume_variant import ResumeVariant
    from applicant.core.ids import CampaignId, ResumeVariantId, new_id

    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    vid = ResumeVariantId(new_id())
    storage.resume_variants.add(
        ResumeVariant(id=vid, campaign_id=cid, storage_path="cv.tex", approved=False)
    )
    storage.commit()

    res = client.post(f"/api/documents/variants/{vid}/approve")
    assert res.status_code == 201
    body = res.json()
    assert body["id"] == str(vid)
    assert body["type"] == "resume_variant"
    assert body["approved"] is True
    assert body["campaign_id"] == str(cid)


def test_owner_variant_library_endpoint_reports_lineage(client):
    """FR-RESUME-6 / FR-UI-6: the owner-scoped variant-library endpoint (the
    user-facing equivalent of the admin Variants view) returns lineage + approval."""
    from applicant.core.entities.resume_variant import ResumeVariant
    from applicant.core.ids import CampaignId, ResumeVariantId, new_id

    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    root = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="root.tex")
    child = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path="child.tex",
        parent_id=root.id,
        approved=True,
        fit_scores={"posting-1": 0.8},
    )
    storage.resume_variants.add(root)
    storage.resume_variants.add(child)
    storage.commit()

    res = client.get(f"/api/documents/variants/{cid}")
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == str(cid)
    lib = {v["variant_id"]: v for v in body["variants"]}
    assert lib[str(root.id)]["is_root"] is True
    assert lib[str(child.id)]["lineage_depth"] == 1
    assert lib[str(child.id)]["approved"] is True


def test_material_service_fallback_builds_from_container_adapters(app):
    """The module-level ``_material_service`` helper builds a MaterialService from the
    frozen container's adapters when no per-request service exists (CONC-REQ-1)."""
    from applicant.app.routers.documents import _material_service
    from applicant.application.services.material_service import MaterialService

    container = app.state.container
    # When a per-request material service IS present, the helper returns it as-is.
    assert _material_service(container) is container.material_service

    container.material_service = None  # force the fallback construction branch.
    svc = _material_service(container)
    assert isinstance(svc, MaterialService)
