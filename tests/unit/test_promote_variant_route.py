"""Regression coverage for wiring ``MaterialService.promote_to_base_resume``
through to a reachable engine endpoint (dark-engine audit item 33).

Before this change ``promote_to_base_resume`` (``src/applicant/application/
services/material_service.py``, #293) had zero callers and no router exposed
it: a user with a clearly winning tailored résumé (per the variant scoreboard)
had no way to make it the new baseline future tailoring forks from. This file
covers the new engine route:

  * ``POST /api/documents/variants/{variant_id}/promote``
    (``src/applicant/app/routers/documents.py``) -- looks the variant up in
    storage, calls ``MaterialService.promote_to_base_resume``, and returns the
    promoted variant's id/type/approved/campaign_id/parent_id. 404 for an
    unknown variant id.

Hermetic: in-memory storage, no TeX/LLM. Mirrors the fixture + style of
``tests/unit/test_cov_documents.py``'s ``approve_variant`` coverage.

Every assertion here was hand-verified to go RED when the router change is
reverted, then GREEN again after restoring.
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


def _seed_variant(client, *, parent_id=None, approved=False):
    from applicant.core.entities.resume_variant import ResumeVariant
    from applicant.core.ids import CampaignId, ResumeVariantId, new_id

    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    vid = ResumeVariantId(new_id())
    storage.resume_variants.add(
        ResumeVariant(
            id=vid,
            campaign_id=cid,
            storage_path="cv.tex",
            approved=approved,
            parent_id=parent_id,
        )
    )
    storage.commit()
    return cid, vid


def test_promote_variant_404_for_unknown_variant(client):
    res = client.post("/api/documents/variants/no-such-variant/promote")
    assert res.status_code == 404
    assert "no such variant" in res.json()["detail"]


def test_promote_variant_clears_parent_and_approves(client):
    """The core behavior: a child variant becomes the new lineage root (its
    ``parent_id`` is cleared) and is marked approved, mirroring
    ``MaterialService.promote_to_base_resume``."""
    from applicant.core.ids import ResumeVariantId, new_id

    parent_id = ResumeVariantId(new_id())
    cid, vid = _seed_variant(client, parent_id=parent_id, approved=False)

    res = client.post(f"/api/documents/variants/{vid}/promote")
    assert res.status_code == 201
    body = res.json()
    assert body["id"] == str(vid)
    assert body["type"] == "resume_variant"
    assert body["approved"] is True
    assert body["campaign_id"] == str(cid)
    assert body["parent_id"] is None

    # Persisted: a follow-up lineage walk from the same variant id sees the
    # cleared parent (the storage record was actually updated, not just the
    # response payload).
    container = client.app.state.container
    stored = container.storage.resume_variants.get(vid)
    assert stored.parent_id is None
    assert stored.approved is True


def test_promote_variant_is_idempotent(client):
    """Promoting an already-promoted (root, approved) variant is a no-op that
    still succeeds and returns the same state."""
    cid, vid = _seed_variant(client, parent_id=None, approved=True)

    res = client.post(f"/api/documents/variants/{vid}/promote")
    assert res.status_code == 201
    body = res.json()
    assert body["approved"] is True
    assert body["parent_id"] is None

    res2 = client.post(f"/api/documents/variants/{vid}/promote")
    assert res2.status_code == 201
    assert res2.json() == body
