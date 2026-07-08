"""Hermetic tests for the owner data export proxy (P1-7, issue #659).

Mounts only ``routes/applicant_export_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives
in ``app.py`` and is out of scope here). The engine is faked with a scripted
``FakeEngine`` patched in for ``ApplicantEngineClient`` — covers the campaign /
application fan-out (shared with the Tracker board via
``applicant_tracker_routes._owner_tracker_rows``), the zip contents, and the
soft-degrade paths. Zero network.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_export_routes as mod
from routes.applicant_export_routes import setup_applicant_export_routes
from src.applicant_engine import EngineError


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_export_routes())
    return app


class FakeResponse:
    """Stands in for the httpx.Response download_variant_pdf returns."""

    def __init__(self, content: bytes):
        self.content = content


class FakeEngine:
    calls: list = []
    campaigns: list = []
    boards: dict = {}          # campaign_id -> {"applications": [...]}
    attributes: dict = {}      # campaign_id -> {"items": [...]}
    runs: dict = {}            # campaign_id -> {"items": [...]} or list
    variants: dict = {}        # campaign_id -> {"variants": [...]}
    pdfs: dict = {}            # variant_id -> bytes
    docs_for_application: dict = {}  # application_id -> {...}
    raises: dict = {}          # key -> EngineError

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        if "list_campaigns" in FakeEngine.raises:
            raise FakeEngine.raises["list_campaigns"]
        return FakeEngine.campaigns

    async def tracker_board(self, campaign_id):
        FakeEngine.calls.append(("tracker_board", campaign_id))
        if ("tracker_board", campaign_id) in FakeEngine.raises:
            raise FakeEngine.raises[("tracker_board", campaign_id)]
        return FakeEngine.boards.get(campaign_id, {"applications": []})

    async def list_attributes(self, campaign_id):
        FakeEngine.calls.append(("list_attributes", campaign_id))
        if ("list_attributes", campaign_id) in FakeEngine.raises:
            raise FakeEngine.raises[("list_attributes", campaign_id)]
        return FakeEngine.attributes.get(campaign_id, {"items": []})

    async def agent_runs_list(self, campaign_id):
        FakeEngine.calls.append(("agent_runs_list", campaign_id))
        if ("agent_runs_list", campaign_id) in FakeEngine.raises:
            raise FakeEngine.raises[("agent_runs_list", campaign_id)]
        return FakeEngine.runs.get(campaign_id, {"items": []})

    async def list_variants(self, campaign_id):
        FakeEngine.calls.append(("list_variants", campaign_id))
        if ("list_variants", campaign_id) in FakeEngine.raises:
            raise FakeEngine.raises[("list_variants", campaign_id)]
        return FakeEngine.variants.get(campaign_id, {"variants": []})

    async def download_variant_pdf(self, variant_id):
        FakeEngine.calls.append(("download_variant_pdf", variant_id))
        if ("download_variant_pdf", variant_id) in FakeEngine.raises:
            raise FakeEngine.raises[("download_variant_pdf", variant_id)]
        return FakeResponse(FakeEngine.pdfs.get(variant_id, b""))

    async def documents_for_application(self, application_id):
        FakeEngine.calls.append(("documents_for_application", application_id))
        if ("documents_for_application", application_id) in FakeEngine.raises:
            raise FakeEngine.raises[("documents_for_application", application_id)]
        return FakeEngine.docs_for_application.get(application_id, {"items": []})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.boards = {}
    FakeEngine.attributes = {}
    FakeEngine.runs = {}
    FakeEngine.variants = {}
    FakeEngine.pdfs = {}
    FakeEngine.docs_for_application = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


def _open_zip(resp) -> zipfile.ZipFile:
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(resp.content))


# --- auth ---------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/export/data.zip")
    assert r.status_code == 401


# --- happy path -----------------------------------------------------------


def test_export_bundles_applications_documents_profile_activity(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend Search"}]
    FakeEngine.boards = {
        "c1": {
            "applications": [
                {
                    "application_id": "a1",
                    "status": "applied",
                    "role_name": "Acme Corp",
                    "job_title": "Backend Engineer",
                    "signals": ["interview_invited"],
                    "submitted_at": "2026-07-01T00:00:00",
                    "created_at": "2026-06-30T00:00:00",
                }
            ]
        }
    }
    FakeEngine.attributes = {"c1": {"campaign_id": "c1", "items": [{"id": "attr1", "name": "email", "value": "a@b.com"}]}}
    FakeEngine.runs = {"c1": {"items": [{"id": "r1", "intent": "Scanning sources"}]}}
    FakeEngine.variants = {
        "c1": {"variants": [{"variant_id": "v1", "fit_score": 0.9, "approved": True}]}
    }
    FakeEngine.pdfs = {"v1": b"%PDF-1.4 fake pdf bytes"}
    FakeEngine.docs_for_application = {
        "a1": {"application_id": "a1", "items": [{"id": "d1", "type": "resume", "approved": True}]}
    }

    r = client.get("/api/applicant/export/data.zip")
    zf = _open_zip(r)
    names = set(zf.namelist())
    assert {
        "manifest.json",
        "applications.json",
        "applications.csv",
        "profile.json",
        "activity.json",
        "documents/documents.json",
        "documents/resume-v1.pdf",
    } <= names

    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["engine_available"] is True
    assert manifest["counts"]["applications"] == 1
    assert manifest["counts"]["documents_pdfs"] == 1

    applications = json.loads(zf.read("applications.json"))
    assert applications[0]["application_id"] == "a1"
    assert applications[0]["role_name"] == "Acme Corp"

    csv_text = zf.read("applications.csv").decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert rows[0]["application_id"] == "a1"
    assert rows[0]["job_title"] == "Backend Engineer"
    assert rows[0]["signals"] == "interview_invited"

    profile = json.loads(zf.read("profile.json"))
    assert profile["c1"]["items"][0]["name"] == "email"

    activity = json.loads(zf.read("activity.json"))
    assert activity["c1"]["items"][0]["intent"] == "Scanning sources"

    documents = json.loads(zf.read("documents/documents.json"))
    assert documents["applications"][0]["application_id"] == "a1"
    assert documents["variants"][0]["variants"][0]["variant_id"] == "v1"

    assert zf.read("documents/resume-v1.pdf") == b"%PDF-1.4 fake pdf bytes"


def test_export_with_no_campaigns_is_still_a_well_formed_empty_zip(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/export/data.zip")
    zf = _open_zip(r)
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["engine_available"] is True
    assert manifest["counts"]["applications"] == 0
    applications = json.loads(zf.read("applications.json"))
    assert applications == []
    csv_text = zf.read("applications.csv").decode("utf-8-sig")
    # header only
    assert csv_text.strip().splitlines()[0].startswith("application_id")


# --- soft degrade -----------------------------------------------------------


def test_export_degrades_soft_when_engine_unreachable(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/export/data.zip")
    zf = _open_zip(r)
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["engine_available"] is False
    applications = json.loads(zf.read("applications.json"))
    assert applications == []


def test_export_marks_engine_unavailable_when_client_construction_fails(monkeypatch):
    # An empty zip must never CLAIM the engine was available (H-series honesty;
    # Greptile finding on #736) — a failed client construction skips every
    # engine-backed section, and the manifest has to say so.
    class Unconstructable:
        def __init__(self):
            raise RuntimeError("bad engine config")

    monkeypatch.setattr(mod, "ApplicantEngineClient", Unconstructable)
    c = TestClient(_make_app())
    r = c.get("/api/applicant/export/data.zip")
    zf = _open_zip(r)
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["engine_available"] is False
    assert any("engine client unavailable" in e for e in manifest["errors"])


def test_variant_pdf_download_failure_is_skipped_not_fatal(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Search"}]
    FakeEngine.variants = {"c1": {"variants": [{"variant_id": "v1"}]}}
    FakeEngine.raises[("download_variant_pdf", "v1")] = EngineError("no artifact", status=404)
    r = client.get("/api/applicant/export/data.zip")
    zf = _open_zip(r)
    names = set(zf.namelist())
    assert "documents/resume-v1.pdf" not in names
    documents = json.loads(zf.read("documents/documents.json"))
    assert documents["variants"][0]["variants"][0]["variant_id"] == "v1"


def test_per_application_documents_failure_is_recorded_not_fatal(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Search"}]
    FakeEngine.boards = {"c1": {"applications": [{"application_id": "a1", "status": "applied"}]}}
    FakeEngine.raises[("documents_for_application", "a1")] = EngineError("boom", status=500)
    r = client.get("/api/applicant/export/data.zip")
    zf = _open_zip(r)
    manifest = json.loads(zf.read("manifest.json"))
    assert any("documents[a1]" in e for e in manifest["errors"])
    documents = json.loads(zf.read("documents/documents.json"))
    # Still emits a row for the application, just without the failed items.
    assert documents["applications"][0]["application_id"] == "a1"
