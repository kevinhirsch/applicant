"""Activation backlog §7.5 — "Resume-health / ATS-parseability score at upload".

Reachability investigation: `ats_parseability.py` (issue #370's
`check_render_parseability`) already existed as a pure, generic core rule, but it
was wired ONLY into `submission_service._verify_ats_parse` — a self-check run on
the GENERATED résumé render right before final submit. It was never run against
the résumé the user actually uploads at onboarding, so the "instant value hit
before any application runs" the audit calls for did not exist: a formatting
problem in the user's own resume was invisible until (at best) submission time.

The fix reuses the SAME pure rule at the ingest call site — no new scoring/NLP is
built. `OnboardingService.ingest_base_resume` now runs
`check_render_parseability` against the parsed résumé's own extractable text and
returns the verdict on `ReconciliationResult` (`parseable` / `parseability_issues`);
the `/api/onboarding/{cid}/base-resume` router surfaces it as a `resume_health`
dict in the upload response, right alongside the existing "Read N details..."
confirmation the front-door already shows post-upload.
"""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.main import create_app
from applicant.application.services.onboarding_service import OnboardingService
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId

CID = "camp-health"

_CLEAN_RESUME = """\
Jane Q Candidate
jane@example.com | +1 (415) 555-0199

Experience:
Senior Engineer at Acme Corp    Jan 2020 - Present

Education:
B.S. Computer Science, State University    2013 - 2017

Skills:
Python, SQL, FastAPI
"""

# No email, no phone, no recognizable section-header words anywhere in the text
# (deliberately avoids "experience"/"education"/"skills"/"summary"/"projects"/
# "work history"/"employment" as substrings) — but well over the 40-char text-layer
# floor, so this trips exactly the "email" + "section headers" issues and nothing
# else.
_MESSY_RESUME = (
    "Jordan Smith\n\n"
    "Worked on many different things across several different teams and roles "
    "over the years, building lots of software for clients using many tools and "
    "platforms consistently well every day for a long time.\n"
)


@pytest.fixture
def svc_and_storage():
    storage = InMemoryStorage()
    storage.campaigns.add(Campaign(id=CampaignId(CID), name="c"))
    store = InMemoryAppConfigStore()
    svc = OnboardingService(storage=storage, config_store=store, resume_parser=ResumeParser())
    return svc, storage, store


# ---------------------------------------------------------------------------
# Service level — OnboardingService.ingest_base_resume
# ---------------------------------------------------------------------------


def test_ingest_base_resume_reports_healthy_resume_as_parseable(svc_and_storage, tmp_path):
    """A resume with a recoverable email + real section headers is flagged healthy."""
    svc, *_ = svc_and_storage
    p = tmp_path / "resume.txt"
    p.write_text(_CLEAN_RESUME, encoding="utf-8")

    result = svc.ingest_base_resume(CID, str(p))

    assert result.parseable is True
    assert result.parseability_issues == []


def test_ingest_base_resume_flags_missing_contact_and_section_headers(svc_and_storage, tmp_path):
    """A resume with no recoverable email/section headers surfaces both issues."""
    svc, *_ = svc_and_storage
    p = tmp_path / "resume.txt"
    p.write_text(_MESSY_RESUME, encoding="utf-8")

    result = svc.ingest_base_resume(CID, str(p))

    assert result.parseable is False
    assert any("email" in issue for issue in result.parseability_issues)
    assert any("section headers" in issue for issue in result.parseability_issues)


# ---------------------------------------------------------------------------
# Router level — POST /api/onboarding/{cid}/base-resume response shape
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _make_campaign(client) -> str:
    r = client.post("/api/campaigns", json={"name": "Job hunt"})
    assert r.status_code == 201
    return r.json()["id"]


def test_base_resume_upload_response_includes_resume_health_when_clean(client):
    cid = _make_campaign(client)
    r = client.post(
        f"/api/onboarding/{cid}/base-resume",
        files={"file": ("resume.txt", io.BytesIO(_CLEAN_RESUME.encode()), "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "resume_health" in body, "upload response must surface resume_health inline"
    assert body["resume_health"] == {"parseable": True, "issues": []}


def test_base_resume_upload_response_flags_issues_when_messy(client):
    cid = _make_campaign(client)
    r = client.post(
        f"/api/onboarding/{cid}/base-resume",
        files={"file": ("resume.txt", io.BytesIO(_MESSY_RESUME.encode()), "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    health = body["resume_health"]
    assert health["parseable"] is False
    assert len(health["issues"]) >= 1


# ---------------------------------------------------------------------------
# Router function directly — confirms the dict-construction wiring in isolation
# (getattr-based passthrough, same pattern already used for attribute_count).
# ---------------------------------------------------------------------------


class _StubReconciliation:
    def __init__(self, *, parseable: bool, issues: list[str]) -> None:
        self.auto_applied: list[str] = []
        self.conflicts: list = []
        self.attribute_count = 3
        self.parseable = parseable
        self.parseability_issues = issues


class _StubOnboardingService:
    def __init__(self, result: _StubReconciliation) -> None:
        self._result = result

    def ingest_base_resume(self, _campaign_id: str, _path: str) -> _StubReconciliation:
        return self._result


@pytest.mark.asyncio
async def test_router_dict_mirrors_service_parseability_verdict(tmp_path):
    from applicant.app.routers.onboarding import ingest_base_resume

    stub = _StubOnboardingService(
        _StubReconciliation(parseable=False, issues=["contact email is not recoverable"])
    )
    upload = UploadFile(file=io.BytesIO(b"some resume text" * 5), filename="resume.txt")

    out = await ingest_base_resume(
        "camp-router-stub", file=upload, svc=stub, container=object()
    )

    assert out["resume_health"] == {
        "parseable": False,
        "issues": ["contact email is not recoverable"],
    }
