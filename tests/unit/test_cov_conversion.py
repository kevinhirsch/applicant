"""Coverage: conversion ROUTER (src/applicant/app/routers/conversion.py).

Drives the LaTeX-conversion accept/reject gate over HTTP (hermetic: the TeX compile
auto-stubs when no engine is present): GET engine (default docx), POST preview (explicit
source AND the ``_base_source`` fallback that reads the uploaded base resume off the
onboarding state), and accept/reject flipping the persisted per-campaign engine. Also
asserts the LLM gate the router declares (409 before setup).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.ports.driving.onboarding import IntakeSection


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        # Open the LLM gate (FR-UI-5) so the conversion router is reachable.
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_get_engine_defaults_to_docx(client):
    res = client.get("/api/conversion/camp-conv-1/engine")
    assert res.status_code == 200
    assert res.json() == {"campaign_id": "camp-conv-1", "engine": "docx"}


def test_preview_with_explicit_source(client):
    res = client.post(
        "/api/conversion/camp-conv-2/preview",
        json={"source": "Jane Doe\nSoftware Engineer\nBuilt data pipelines in Python."},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == "camp-conv-2"
    # A real moderncv conversion + (stubbed) compile yields a storage path + page count.
    assert body["storage_path"]
    assert body["page_count"] >= 1
    assert "fidelity_ok" in body


def test_accept_then_reject_flips_persisted_engine(client):
    cid = "camp-conv-3"
    # ACCEPT -> latex becomes the campaign's engine, and it persists.
    acc = client.post(f"/api/conversion/{cid}/accept")
    assert acc.status_code == 200
    assert acc.json() == {"campaign_id": cid, "engine": "latex"}
    assert client.get(f"/api/conversion/{cid}/engine").json()["engine"] == "latex"

    # REJECT -> falls back to docx, and that persists too.
    rej = client.post(f"/api/conversion/{cid}/reject")
    assert rej.status_code == 200
    assert rej.json() == {"campaign_id": cid, "engine": "docx"}
    assert client.get(f"/api/conversion/{cid}/engine").json()["engine"] == "docx"


def test_preview_falls_back_to_uploaded_base_resume(client, tmp_path):
    """With no explicit source, the router resolves the uploaded base-resume file
    (``_base_source``) off the onboarding state and converts that."""
    cid = "camp-conv-4"
    resume = tmp_path / "resume.txt"
    resume.write_text(
        "Kevin Hirsch\nStaff Engineer\nLed platform teams; shipped Python services.",
        encoding="utf-8",
    )
    # Seed the onboarding base-resume section with the file path the router reads.
    container = client.app.state.container
    container.onboarding_service.save_section(
        cid, IntakeSection.BASE_RESUME, {"document_path": str(resume)}
    )

    res = client.post(f"/api/conversion/{cid}/preview", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["campaign_id"] == cid
    assert body["storage_path"]  # it converted the file content, not an empty string.


def test_preview_unreadable_base_resume_is_swallowed(client, tmp_path, monkeypatch):
    """If the uploaded base-resume file exists but can't be read, ``_base_source``
    swallows the OSError and returns "" rather than 500ing the preview."""
    cid = "camp-conv-6"
    resume = tmp_path / "resume.txt"
    resume.write_text("secret resume", encoding="utf-8")

    container = client.app.state.container
    container.onboarding_service.save_section(
        cid, IntakeSection.BASE_RESUME, {"document_path": str(resume)}
    )

    # The file exists (is_file() True) but reading it raises -> exercise the
    # ``except OSError`` branch in _base_source deterministically (we run as root,
    # so a chmod-based denial would not actually block the read).
    import applicant.app.routers.conversion as conv_mod

    real_read_text = conv_mod.Path.read_text

    def _boom(self, *a, **k):
        if str(self) == str(resume):
            raise OSError("permission denied")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(conv_mod.Path, "read_text", _boom)
    res = client.post(f"/api/conversion/{cid}/preview", json={})
    assert res.status_code == 200
    assert res.json()["campaign_id"] == cid


def test_preview_with_missing_base_resume_uses_empty_source(client):
    """No explicit source AND no uploaded base resume -> ``_base_source`` returns "",
    and the preview is still built (empty conversion) rather than erroring."""
    res = client.post("/api/conversion/camp-conv-5/preview", json={})
    assert res.status_code == 200
    assert res.json()["campaign_id"] == "camp-conv-5"


def test_router_blocked_before_llm_gate(app):
    with TestClient(app) as c:
        assert c.get("/api/conversion/camp-z/engine").status_code == 409
