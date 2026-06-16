"""Onboarding / fonts / conversion endpoints + automated-work gate (Phase 0 exit).

Proves the zero-CLI OOBE+onboarding gate end to end over HTTP (NFR-ZEROCLI-1):
the gated surface is 409 until the LLM is configured; onboarding is resumable and
saved per step; the base-resume upload bootstraps the attribute cloud; the font
flow detects/installs; the LaTeX conversion accept/reject persists; and
"automated work may begin" requires LLM + channels + onboarding complete.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from applicant.app.config import Settings
from applicant.app.main import create_app
from applicant.ports.driving.onboarding import REQUIRED_SECTIONS


@pytest.fixture
def client(tmp_path):
    # Isolate the confined fonts dir so installs don't leak across test runs.
    settings = Settings(FONTS_DIR=str(tmp_path / "fonts"))
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _configure_llm(client) -> None:
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204


def _make_campaign(client) -> str:
    r = client.post("/api/campaigns", json={"name": "Job hunt"})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.integration
def test_onboarding_gated_until_llm(client):
    # FR-UI-5: onboarding surface is 409 until LLM configured.
    assert client.get("/api/onboarding/anything").status_code == 409


@pytest.mark.integration
def test_onboarding_resumable_and_complete_gate(client):
    _configure_llm(client)
    cid = _make_campaign(client)

    # Initially incomplete; required sections missing.
    state = client.get(f"/api/onboarding/{cid}").json()
    assert state["complete"] is False
    assert state["missing_sections"]

    # Completing before filling required sections is refused (FR-ONBOARD-2).
    assert client.post(f"/api/onboarding/{cid}/complete").status_code == 409

    # Save every required section (resumable, persisted per step).
    for section in REQUIRED_SECTIONS:
        r = client.post(
            f"/api/onboarding/{cid}/section",
            json={"section": section.value, "data": {"answer": "value"}},
        )
        assert r.status_code == 200

    done = client.post(f"/api/onboarding/{cid}/complete")
    assert done.status_code == 200
    assert done.json()["complete"] is True


@pytest.mark.integration
def test_base_resume_upload_bootstraps_and_reconciles(client):
    _configure_llm(client)
    cid = _make_campaign(client)
    # Interview answer conflicts with the resume on an integral field.
    client.post(
        f"/api/onboarding/{cid}/section",
        json={"section": "identity", "data": {"full_name": "Janet Different"}},
    )
    resume = (
        "Jane Q Candidate\njane@example.com\n\nExperience:\n"
        "Senior Engineer at Acme Corp    Jan 2020 - Present\n\nSkills:\nPython, SQL\n"
    )
    r = client.post(
        f"/api/onboarding/{cid}/base-resume",
        files={"file": ("resume.txt", io.BytesIO(resume.encode()), "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["attribute_count"] > 0
    assert body["requires_confirmation"] is True
    assert any(c["attribute"] == "full_name" for c in body["conflicts"])

    # Confirm the integral change (FR-FB-3).
    conf = client.post(
        f"/api/onboarding/{cid}/confirm-conflict",
        json={"attribute": "full_name", "value": "Jane Q Candidate"},
    )
    assert conf.status_code == 200
    assert conf.json()["intake"]["identity"]["full_name"] == "Jane Q Candidate"


@pytest.mark.integration
def test_font_flow_detect_and_install(client):
    _configure_llm(client)
    tex = "\\setmainfont{Lato}\n\\fontspec{Inconsolata}\n"
    det = client.post(
        "/api/fonts/detect",
        files={"file": ("resume.tex", io.BytesIO(tex.encode()), "text/plain")},
    )
    assert det.status_code == 200
    assert "Inconsolata" in det.json()["missing"]

    inst = client.post(
        "/api/fonts/install",
        data={"name": "Inconsolata"},
        files={"file": ("Inconsolata.ttf", io.BytesIO(b"\x00\x01font"), "font/ttf")},
    )
    assert inst.status_code == 200
    assert inst.json()["confirmed"] is True
    assert "Inconsolata" in client.get("/api/fonts").json()["installed"]


@pytest.mark.integration
def test_conversion_accept_reject_persists(client):
    _configure_llm(client)
    cid = _make_campaign(client)
    assert client.get(f"/api/conversion/{cid}/engine").json()["engine"] == "docx"

    prev = client.post(f"/api/conversion/{cid}/preview", json={"source": "\\section{S}\nbody"})
    assert prev.status_code == 200
    assert prev.json()["page_count"] >= 1

    assert client.post(f"/api/conversion/{cid}/accept").json()["engine"] == "latex"
    assert client.get(f"/api/conversion/{cid}/engine").json()["engine"] == "latex"
    assert client.post(f"/api/conversion/{cid}/reject").json()["engine"] == "docx"


@pytest.mark.integration
def test_automated_work_gate_requires_llm_channels_onboarding(client):
    # Fresh: nothing configured.
    s = client.get("/api/setup/status").json()
    assert s["automated_work_allowed"] is False

    _configure_llm(client)
    # LLM only: still blocked (channels + onboarding missing).
    assert client.get("/api/setup/status").json()["automated_work_allowed"] is False

    # Channels configured (modeled gate, FR-OOBE-3).
    client.post("/api/setup/advance/channels")
    assert client.get("/api/setup/status").json()["automated_work_allowed"] is False

    # Onboarding complete (FR-ONBOARD-2) finally opens the gate.
    cid = _make_campaign(client)
    for section in REQUIRED_SECTIONS:
        client.post(
            f"/api/onboarding/{cid}/section",
            json={"section": section.value, "data": {"answer": "v"}},
        )
    assert client.post(f"/api/onboarding/{cid}/complete").json()["complete"] is True

    assert client.get("/api/setup/status").json()["automated_work_allowed"] is True
