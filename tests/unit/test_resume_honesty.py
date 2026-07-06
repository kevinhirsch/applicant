"""Product-honesty regression suite for the résumé upload / preview claims.

A live audit caught the OOBE "Your profile" step fabricating success for a tiny
dummy résumé: "Resume health: looks good", "I read 21 details", and "I built a
polished version (2 pages). Looks like a faithful match." — with no name/contact
parsed, no LLM calls, and no render toolchain installed. Per the repo principle,
guards/claims must derive their own ground truth server-side:

* the resume-health verdict is now COMPUTED from what the parse actually found
  (name / email / phone / section headers / recoverable text) — never defaulted;
* "I read N details" counts THIS parse (``parsed_field_count``), not the whole
  attribute cloud;
* the conversion preview only carries artifact metadata (storage path, page
  count, passing fidelity) when a real PDF was produced by an available
  toolchain; with the toolchain absent it reports an honest unavailable verdict.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.resume_tailoring import latex_tailor as latex_mod
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.main import create_app
from applicant.application.services.onboarding_service import OnboardingService
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId
from applicant.core.rules.ats_parseability import (
    UPLOAD_HEALTH_GOOD,
    UPLOAD_HEALTH_ISSUES,
    UPLOAD_HEALTH_UNREADABLE,
    check_upload_health,
)

CID = "camp-honesty"

#: The audit's failure mode: a tiny dummy "résumé" with no name, no contact info,
#: no real sections — long enough to have a text layer, but nothing a recruiter
#: system could use. This must NEVER read as "looks good".
_DUMMY_RESUME = (
    "this is a dummy resume file used for testing the upload flow only, "
    "it contains no real candidate information at all whatsoever\n"
)

_COMPLETE_RESUME = """\
Jane Q Candidate
jane@example.com | +1 (415) 555-0199

Experience:
Senior Engineer at Acme Corp    Jan 2020 - Present

Education:
B.S. Computer Science, State University    2013 - 2017

Skills:
Python, SQL, FastAPI
"""


# ---------------------------------------------------------------------------
# Core rule — check_upload_health derives every verdict, no optimistic default
# ---------------------------------------------------------------------------


def test_empty_resume_is_unreadable_not_good():
    report = check_upload_health(raw_text="", full_name="", email="", phone="")
    assert report.verdict == UPLOAD_HEALTH_UNREADABLE
    assert report.parseable is False
    assert any("no recoverable text layer" in i for i in report.issues)


def test_dummy_resume_with_no_contact_yields_issue_verdict_naming_whats_missing():
    report = check_upload_health(raw_text=_DUMMY_RESUME, full_name="", email="", phone="")
    assert report.verdict == UPLOAD_HEALTH_ISSUES
    assert report.parseable is False
    joined = " | ".join(report.issues)
    assert "your name is not detectable" in joined
    assert "contact email is not recoverable" in joined
    assert "phone number is not detectable" in joined
    assert "no recognizable section headers" in joined
    # And it's suspiciously thin for a résumé.
    assert "very little text" in joined


def test_complete_resume_with_all_fields_found_is_good():
    report = check_upload_health(
        raw_text=_COMPLETE_RESUME,
        full_name="Jane Q Candidate",
        email="jane@example.com",
        phone="+1 (415) 555-0199",
    )
    assert report.verdict == UPLOAD_HEALTH_GOOD
    assert report.parseable is True
    assert report.issues == ()


def test_missing_single_field_downgrades_the_verdict():
    # Missing phone alone must already prevent a "looks good" claim.
    report = check_upload_health(
        raw_text=_COMPLETE_RESUME,
        full_name="Jane Q Candidate",
        email="jane@example.com",
        phone="",
    )
    assert report.verdict == UPLOAD_HEALTH_ISSUES
    assert any("phone number" in i for i in report.issues)


# ---------------------------------------------------------------------------
# Service — the verdict and the "I read N details" count come from THIS parse
# ---------------------------------------------------------------------------


@pytest.fixture
def onboarding_svc():
    storage = InMemoryStorage()
    storage.campaigns.add(Campaign(id=CampaignId(CID), name="c"))
    return OnboardingService(
        storage=storage, config_store=InMemoryAppConfigStore(), resume_parser=ResumeParser()
    )


def test_ingest_dummy_resume_reports_issue_verdict_and_tiny_field_count(onboarding_svc, tmp_path):
    p = tmp_path / "dummy.txt"
    p.write_text(_DUMMY_RESUME, encoding="utf-8")
    result = onboarding_svc.ingest_base_resume(CID, str(p))
    assert result.health_verdict == UPLOAD_HEALTH_ISSUES
    assert result.parseable is False
    # Nothing (or nearly nothing) was actually extracted — the honest count.
    assert result.parsed_field_count <= 2


def test_ingest_complete_resume_reports_good_verdict_and_real_field_count(onboarding_svc, tmp_path):
    p = tmp_path / "resume.txt"
    p.write_text(_COMPLETE_RESUME, encoding="utf-8")
    result = onboarding_svc.ingest_base_resume(CID, str(p))
    assert result.health_verdict == UPLOAD_HEALTH_GOOD
    assert result.parseable is True
    # name + email + phone + >=1 job + >=1 degree + >=3 skills
    assert result.parsed_field_count >= 6
    # The honest per-parse count is not the attribute-cloud total by construction:
    # it is derived from the ParsedResume fields alone (see onboarding_service).


# ---------------------------------------------------------------------------
# HTTP boundary — upload response + conversion preview with no toolchain
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "model": "llama3.1",
            },
        )
        assert r.status_code == 204
        yield c


def _make_campaign(client) -> str:
    r = client.post("/api/campaigns", json={"name": "Job hunt"})
    assert r.status_code == 201
    return r.json()["id"]


def test_dummy_upload_response_is_honest_end_to_end(client):
    import io

    cid = _make_campaign(client)
    r = client.post(
        f"/api/onboarding/{cid}/base-resume",
        files={"file": ("dummy.txt", io.BytesIO(_DUMMY_RESUME.encode()), "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    health = body["resume_health"]
    assert health["verdict"] == "issues"
    assert health["parseable"] is False
    assert any("name is not detectable" in i for i in health["issues"])
    assert body["parsed_field_count"] <= 2


def test_conversion_preview_with_no_toolchain_reports_honest_unavailable(client, monkeypatch):
    """Toolchain-absent convert -> honest unavailable response, no fabricated
    artifact metadata (no storage path, no page count, no passing fidelity)."""
    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: None)
    res = client.post(
        "/api/conversion/camp-honesty-conv/preview",
        json={"source": "Jane Doe\nSoftware Engineer\nBuilt data pipelines in Python."},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["artifact_available"] is False
    assert body["storage_path"] is None
    assert body["page_count"] is None
    assert body["fidelity_ok"] is False
    assert "aren't available" in body["notes"]
    assert "faithful match" not in body["notes"].lower()


def test_conversion_preview_download_404s_honestly_with_no_toolchain(client, monkeypatch):
    monkeypatch.setattr(latex_mod.shutil, "which", lambda _name: None)
    res = client.get("/api/conversion/camp-honesty-conv/preview/download")
    assert res.status_code == 404
    assert "document tools" in res.json()["detail"]
