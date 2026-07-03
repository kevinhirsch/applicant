"""Regression tests: variant-library ancestry breadcrumb (dark-engine audit item 50).

``MaterialService.lineage(variant)`` already walks a résumé variant's ``parent_id``
chain to the root, but the routed variant library (``GET
/api/documents/variants/{campaign_id}``) used to read rows flat and never surfaced
that chain — a user could see a raw ``lineage_depth`` count and an immediate
``parent_id``, but never the readable ancestry ("this variant was tailored from
that one, which was tailored from the original base résumé").

These tests exercise the router directly (hermetic ``TestClient`` over
``create_app()``, in-memory storage, no TeX/LLM/DB) and confirm each variant's
response dict now carries a ``lineage`` list, root-first, built from the SAME
``MaterialService.lineage`` walk core to FR-RESUME-6.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.ids import CampaignId, ResumeVariantId, new_id


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


def test_lone_root_variant_has_a_single_entry_lineage(client):
    """A variant with no parent is its own (one-entry) lineage: itself, the root."""
    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    root = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="root.tex")
    storage.resume_variants.add(root)
    storage.commit()

    res = client.get(f"/api/documents/variants/{cid}")
    assert res.status_code == 200
    lib = {v["variant_id"]: v for v in res.json()["variants"]}

    lineage = lib[str(root.id)]["lineage"]
    assert len(lineage) == 1
    assert lineage[0]["variant_id"] == str(root.id)
    assert lineage[0]["is_root"] is True


def test_three_generation_chain_reports_full_ancestry_root_first(client):
    """Root -> child -> grandchild: the deepest variant's lineage lists all three,
    oldest (root) first, ending with itself — the shape the breadcrumb renders."""
    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    root = ResumeVariant(
        id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="root.tex", approved=True
    )
    child = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path="child.tex",
        parent_id=root.id,
        approved=True,
        targeted_jd_signature="acme-swe",
    )
    grandchild = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path="grandchild.tex",
        parent_id=child.id,
        targeted_jd_signature="beta-swe",
    )
    storage.resume_variants.add(root)
    storage.resume_variants.add(child)
    storage.resume_variants.add(grandchild)
    storage.commit()

    res = client.get(f"/api/documents/variants/{cid}")
    assert res.status_code == 200
    lib = {v["variant_id"]: v for v in res.json()["variants"]}

    lineage = lib[str(grandchild.id)]["lineage"]
    assert [n["variant_id"] for n in lineage] == [str(root.id), str(child.id), str(grandchild.id)]
    assert lineage[0]["is_root"] is True
    assert lineage[1]["targeted_jd_signature"] == "acme-swe"
    assert lineage[2]["variant_id"] == str(grandchild.id)
    assert lineage[2]["targeted_jd_signature"] == "beta-swe"

    # The child's own lineage is just root -> child (does not include its
    # descendant grandchild).
    child_lineage = lib[str(child.id)]["lineage"]
    assert [n["variant_id"] for n in child_lineage] == [str(root.id), str(child.id)]


def test_lineage_is_empty_list_never_absent_for_a_row(client):
    """Every row in the library carries a ``lineage`` key (never missing), so the
    front door can render without a defensive existence check."""
    container = client.app.state.container
    storage = container.storage
    cid = CampaignId(new_id())
    v = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="v.tex")
    storage.resume_variants.add(v)
    storage.commit()

    res = client.get(f"/api/documents/variants/{cid}")
    row = res.json()["variants"][0]
    assert "lineage" in row
    assert isinstance(row["lineage"], list)
