"""Reachability + real fields for the Gallery router (#296).

Proves the wired endpoint — not just the service method in isolation:
  (a) ``/api/gallery/{campaign_id}`` is a REGISTERED route on the booted app and
      returns non-404 via ``TestClient``;
  (b) a seeded campaign returns REAL fields — screenshot collections carry
      ``page_ref`` / ``page_url`` and material collections carry ``type`` /
      ``storage_path`` / ``approved`` / ``content`` (sourced from
      ``AdminQueryService``), not just the empty case.

Hermetic: in-memory storage, real container services, LLM gate opened like the
peer router tests (test_compare_router.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.application import Application
from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    ScreenshotId,
)
from applicant.core.state_machine import ApplicationState


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        # Open the LLM gate (the router carries require_llm_configured).
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _registered_paths(app) -> set[str]:
    """All endpoint paths registered on the app (flattening the mount wrapper)."""
    paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    return paths


def _seed(container, cid, aid):
    container.storage.campaigns.add(Campaign(id=CampaignId(cid), name="Gallery"))
    container.storage.applications.add(
        Application(
            id=ApplicationId(aid),
            campaign_id=CampaignId(cid),
            posting_id=JobPostingId(f"posting-{aid}"),
            status=ApplicationState.PREFILLING,
            role_name="Engineer",
        )
    )
    container.storage.screenshots.add(
        ApplicationScreenshot(
            id=ScreenshotId("shot-1"),
            application_id=ApplicationId(aid),
            page_ref="page-1.png",
            page_url="https://jobs.example.com/apply",
        )
    )
    container.storage.documents.add(
        GeneratedDocument(
            id=GeneratedDocumentId("doc-1"),
            campaign_id=CampaignId(cid),
            application_id=ApplicationId(aid),
            type=DocumentType.COVER_LETTER,
            content="Dear hiring team,",
            storage_path="artifacts/doc-1.pdf",
            approved=True,
        )
    )
    container.storage.commit()


# --- (a) reachability: the route is registered and non-404 ---------------------
def test_gallery_route_is_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/gallery/{campaign_id}" in paths


def test_gallery_endpoint_is_reachable_not_404(client):
    r = client.get("/api/gallery/c-empty")
    assert r.status_code != 404
    assert r.status_code == 200


# --- (b) seeded campaign returns REAL fields -----------------------------------
def test_gallery_returns_real_screenshot_and_material_fields(client):
    container = client.app.state.container
    _seed(container, "c-1", "a-1")

    r = client.get("/api/gallery/c-1")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == "c-1"

    shots = body["screenshots"]
    assert shots["count"] == 1
    shot = shots["items"][0]
    # REAL screenshot fields from AdminQueryService.
    assert shot["page_ref"] == "page-1.png"
    assert shot["page_url"] == "https://jobs.example.com/apply"
    assert shot["application_id"] == "a-1"

    mats = body["materials"]
    assert mats["count"] == 1
    mat = mats["items"][0]
    # REAL material fields from AdminQueryService.
    assert mat["type"] == "cover_letter"
    assert mat["storage_path"] == "artifacts/doc-1.pdf"
    assert mat["approved"] is True
    assert mat["content"] == "Dear hiring team,"


def test_gallery_empty_campaign_is_well_formed(client):
    r = client.get("/api/gallery/c-none")
    assert r.status_code == 200
    body = r.json()
    assert body["screenshots"] == {"count": 0, "items": []}
    assert body["materials"] == {"count": 0, "items": []}
