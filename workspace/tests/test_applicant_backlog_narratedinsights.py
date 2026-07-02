"""Regression coverage for the learning-story backlog item (docs/design/audits/
PRODUCT_EXHAUSTIVE_AUDIT.md): "narrated insights (not stat dumps)" +
"decline-reasons rolled up", on the non-admin Results surface
(``static/js/applicantResults.js`` + ``routes/applicant_results_routes.py``).

Two things landed this round, both additive/surfacing-only:

  1. Each Results section now leads with a narrated, plain-language takeaway
     sentence (a real ``_headline()`` helper, e.g. "You're converting best on
     LinkedIn -- 3 of 5 matched roles there were submitted.") ABOVE its bars/
     chips, instead of leaving the reader to interpret a bare number/percentage
     grid. The funnel, per-source, and "what converts for you" sections all
     grew one.
  2. A new fourth section, "Why you decline" (``_renderDeclines``), rolls up the
     words most common in the user's OWN decline feedback. Decline feedback is
     MANDATORY (``DigestService.decline`` rejects a blank ``feedback_text`` --
     FR-FB-1), and the engine already tokenizes it into ``feature_stats`` to
     bias future scoring (``LearningService.ingest_decline_feedback``) -- that
     signal was write-only. The new read-only ``LearningService.decline_reasons``
     surfaces the SAME persisted signal as a plain word-frequency rollup (no new
     capture point, no invented taxonomy), threaded through
     ``build_summary`` -> the ``GET /api/admin/learning/{id}`` engine read-model
     -> this proxy's ``decline_reasons`` field -> the new JS section.

Testing strategy, per the task's own instructions for this file: regex/text
assertions over the actual shipped source (``applicantResults.js``), since the
DOM-execution harness other Results-touching suites in this repo use is heavier
than this narrow a change needs; PLUS real (non-regex) FastAPI ``TestClient``
execution of the proxy route extension, mirroring
``test_applicant_results_routes.py``'s own ``FakeEngine`` pattern exactly.

Every ``test_*`` here was verified failing first (temporarily reverting the
source it protects), then restored -- clean ``git diff`` on the fixture files
afterward.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_results_routes as mod
from routes.applicant_results_routes import setup_applicant_results_routes

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_RESULTS_JS = _REPO / "static" / "js" / "applicantResults.js"


def _js_source() -> str:
    return _RESULTS_JS.read_text(encoding="utf-8")


# --- source-level: narrated headlines, not a stat dump ----------------------


@pytest.mark.parametrize(
    "needle",
    [
        # A dedicated headline helper exists and is used by every section, not
        # just tucked into one corner.
        "function _headline(text)",
        # The funnel narrates counts + overall rate as a sentence.
        "You've had ${matched} role",
        "been submitted",
        # Per-source conversion narrates the best-converting source by name +
        # real counts (the audit's own example: "You're converting best on
        # LinkedIn -- 3 of 5...").
        "You're converting best on",
        "function _sourcesHeadline(sources)",
        # "What converts for you" leads with a sentence, not just bare chips.
        "you tend to move forward on roles like these",
    ],
)
def test_results_js_has_narrated_headline_text(needle):
    src = _js_source()
    assert needle in src, f"expected narrated copy {needle!r} in applicantResults.js"


def test_headline_is_actually_called_from_every_stat_section():
    """Guards against the helper existing but being dead code in one section."""
    src = _js_source()
    # One call inside _renderFunnel, one inside _renderSources (via
    # _sourcesHeadline), one inside _renderSignature, one inside _renderDeclines.
    assert src.count("${_headline(") >= 4 or src.count("_headline(") >= 5


# --- source-level: the new "Why you decline" section -------------------------


@pytest.mark.parametrize(
    "needle",
    [
        "function _renderDeclines(reasons)",
        "Why you decline",
        "comes up most when you decline a role",
        "_renderDeclines(declineReasons)",
        "data.decline_reasons",
    ],
)
def test_results_js_has_decline_reasons_section(needle):
    src = _js_source()
    assert needle in src, f"expected {needle!r} in applicantResults.js"


def test_decline_reasons_section_degrades_to_nothing_when_empty():
    """No reasons yet -> the section renders nothing (never a fabricated '0
    declines' card) -- mirrors every other section's `if (!x.length) return '';`
    empty-degrade convention already established in this file."""
    src = _js_source()
    assert "if (!reasons.length) return '';" in src


# --- proxy route: decline_reasons passes straight through --------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    learning: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        return FakeEngine.campaigns

    async def admin_learning(self, cid):
        FakeEngine.calls.append(("admin_learning", cid))
        return FakeEngine.learning.get(cid, {})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.learning = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_results_routes())
    return TestClient(app)


def test_proxy_forwards_decline_reasons_from_engine(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.learning = {
        "c1": {
            "campaign_id": "c1",
            "summary": {"total_matched": 10, "total_approved": 4, "total_submitted": 2},
            "sources": [],
            "converting_roles": [],
            "decline_reasons": [
                {"reason": "onsite", "count": 4},
                {"reason": "salary", "count": 2},
            ],
        }
    }
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["decline_reasons"] == [
        {"reason": "onsite", "count": 4},
        {"reason": "salary", "count": 2},
    ]


def test_proxy_defaults_decline_reasons_to_empty_list_when_engine_omits_it(client):
    """Older/degraded engine payloads without the new field never crash the
    proxy -- it degrades to []."""
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.learning = {
        "c1": {
            "campaign_id": "c1",
            "summary": {"total_matched": 5, "total_approved": 1, "total_submitted": 1},
            "sources": [],
            "converting_roles": [],
            # no decline_reasons key at all
        }
    }
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    assert r.json()["decline_reasons"] == []


def test_proxy_drops_malformed_decline_reason_entries(client):
    """A malformed entry (not a dict, or missing 'reason') is dropped rather
    than surfaced as broken UI -- same defensive filtering as converting_roles."""
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.learning = {
        "c1": {
            "campaign_id": "c1",
            "summary": {"total_matched": 5, "total_approved": 1, "total_submitted": 1},
            "sources": [],
            "converting_roles": [],
            "decline_reasons": [
                {"reason": "onsite", "count": 3},
                "not-a-dict",
                {"count": 1},  # missing 'reason'
                None,
            ],
        }
    }
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    assert r.json()["decline_reasons"] == [{"reason": "onsite", "count": 3}]


def test_no_campaign_empty_scaffold_includes_decline_reasons(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/results")
    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is False
    assert body["decline_reasons"] == []
