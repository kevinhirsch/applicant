"""P1-9 save-a-job-from-any-page: the front-door half.

Covers the three workspace pieces the story adds:

* ``routes/applicant_tracker_routes.py`` — the new owner-gated
  ``POST /api/applicant/tracker/save-job`` proxy over the engine's direct-URL
  intake (campaign resolved from THIS request's own ``list_campaigns()``
  fan-out, never a caller-supplied id; soft-degrades exactly like its
  siblings). Route-level tests with the scripted ``FakeEngine``, mirroring
  ``test_applicant_tracker_routes.py``.
* ``static/capture.html`` + the ``/capture`` app route — the bookmarklet
  target popup. Source-composition assertions (the page must post to the
  save-job proxy with the session cookie, carry the CSP nonce token, and the
  app route must serve it) — the same convention as the sibling ``*_ui`` tests
  for browser-only surfaces.
* ``static/js/applicantTracker.js`` — the Tracker's "Add a job you found
  yourself" panel (paste-a-URL input + the bookmarklet install link opening
  ``/capture?url=…``). Source-composition assertions.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_tracker_routes as mod
from routes.applicant_tracker_routes import setup_applicant_tracker_routes
from src.applicant_engine import EngineError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"

SAVE_URL = "https://boards.example.com/jobs/senior-backend-engineer-1234"


# --- test app with a stand-in auth middleware --------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_tracker_routes())
    return app


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    intake_results: dict = {}  # url -> engine response dict
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

    async def intake_url(self, campaign_id, url):
        FakeEngine.calls.append(("intake_url", campaign_id, url))
        if "intake_url" in FakeEngine.raises:
            raise FakeEngine.raises["intake_url"]
        return FakeEngine.intake_results.get(
            url,
            {
                "saved": True,
                "duplicate": False,
                "posting_id": "p-1",
                "campaign_id": campaign_id,
                "title": "Senior Backend Engineer",
                "company": "boards.example.com",
                "source": "added-by-you",
                "viability_score": 75,
                "fetched": False,
                "note": "",
            },
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.intake_results = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth ---------------------------------------------------------------------


def test_unauthenticated_save_job_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.post("/api/applicant/tracker/save-job", json={"url": SAVE_URL})
    assert r.status_code == 401
    # The engine must never even be consulted for an unauthenticated caller.
    assert FakeEngine.calls == []


# --- the save path --------------------------------------------------------------


def test_save_job_forwards_to_owners_first_campaign(client):
    FakeEngine.campaigns = [
        {"id": "c1", "name": "Backend"},
        {"id": "c2", "name": "Frontend"},
    ]

    r = client.post("/api/applicant/tracker/save-job", json={"url": SAVE_URL})

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["saved"] is True
    assert body["source"] == "added-by-you"
    assert body["viability_score"] == 75
    # The campaign is resolved from THIS request's own fan-out (first campaign),
    # never a caller-supplied id.
    assert ("intake_url", "c1", SAVE_URL) in FakeEngine.calls


def test_save_job_without_a_campaign_is_honest_not_500(client):
    FakeEngine.campaigns = []

    r = client.post("/api/applicant/tracker/save-job", json={"url": SAVE_URL})

    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is False
    assert body["has_data"] is False
    assert "Finish setup" in body["note"]
    # The intake write was never attempted.
    assert all(not (isinstance(c, tuple) and c[0] == "intake_url") for c in FakeEngine.calls)


def test_save_job_soft_degrades_when_engine_down(client):
    FakeEngine.raises = {"list_campaigns": EngineError("down", status=None)}

    r = client.post("/api/applicant/tracker/save-job", json={"url": SAVE_URL})

    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["saved"] is False


def test_save_job_gate_409_is_surfaced_as_gated(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises = {
        "intake_url": EngineError("blocked", status=409, detail="Finish setup first.")
    }

    r = client.post("/api/applicant/tracker/save-job", json={"url": SAVE_URL})

    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == "Finish setup first."


def test_save_job_bad_url_422_is_a_real_error_with_engine_message(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises = {
        "intake_url": EngineError(
            "unprocessable", status=422, detail="That doesn't look like a web address I can open."
        )
    }

    r = client.post("/api/applicant/tracker/save-job", json={"url": "notaurl"})

    assert r.status_code == 422
    assert "web address" in r.json()["detail"]


def test_save_job_duplicate_passthrough(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.intake_results = {
        SAVE_URL: {
            "saved": False,
            "duplicate": True,
            "posting_id": "p-1",
            "title": "Senior Backend Engineer",
            "note": "This role is already being tracked — no second copy was created.",
        }
    }

    r = client.post("/api/applicant/tracker/save-job", json={"url": SAVE_URL})

    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is False
    assert body["duplicate"] is True
    assert "already being tracked" in body["note"]


# --- the /capture bookmarklet page (source composition) ------------------------


def _read(rel: str) -> str:
    return (WORKSPACE_DIR / rel).read_text(encoding="utf-8")


def test_capture_page_posts_to_save_job_proxy_with_session_cookie():
    html = _read("static/capture.html")
    # CSP: the inline script must carry the nonce token app.py injects.
    assert 'nonce="{{CSP_NONCE}}"' in html
    # The page reads ?url= and posts it through the owner-gated proxy, reusing
    # the session cookie (the whole point of the bookmarklet popup).
    assert "params.get('url')" in html
    assert "/api/applicant/tracker/save-job" in html
    assert "credentials: 'same-origin'" in html
    # Honest states: signed-out, gated, offline, duplicate all say so.
    assert "You need to sign in first." in html
    assert "finish setup first" in html.lower()
    assert "offline" in html.lower()
    assert "Already tracked" in html


def test_capture_route_is_registered_in_app():
    app_py = _read("app.py")
    m = re.search(r"@app\.get\(\"/capture\"\)\s*\nasync def serve_capture", app_py)
    assert m, "/capture route missing from app.py"
    assert 'static/capture.html' in app_py


# --- the Tracker panel (source composition) ------------------------------------


def test_tracker_panel_has_paste_input_and_bookmarklet():
    js = _read("static/js/applicantTracker.js")
    # The always-visible save-a-job panel exists and is rendered at modal build.
    assert "applicant-tracker-savejob" in js
    assert "_renderSaveJobPanel(modal.querySelector('#applicant-tracker-savejob'))" in js
    # Paste-a-URL posts through the SAME proxy the capture page uses.
    assert "_post(`${API}/save-job`, { url })" in js
    # The bookmarklet opens /capture?url=… in a popup.
    assert "/capture?url='+encodeURIComponent(location.href)" in js
    # Honest result states surfaced inline (gated / offline / duplicate / saved).
    assert "already tracked, no second copy was created" in js
    assert "pending items to review" in js
