"""P1-12: the on-demand weekly-recap read (digest router).

``GET /api/digest/{campaign_id}/weekly-recap`` is PURE EXPOSURE of the recap the
scheduler already pushes weekly through the notification fan-out
(``DigestService.build_weekly_recap`` + ``render_weekly_recap_message`` — audit
Top-25 #18): no new aggregation logic, no new state. These prove, hermetically:

* the route returns the engine's own composed, first-person recap message —
  subject, body, and the real counts behind it;
* a zero-application week reads honestly ("didn't send any") with no fabricated
  best source;
* a real submission inside the trailing window is counted and narrated;
* the route carries the SAME automated-work gate as its daily-digest siblings
  (LLM-only setup gets the 409, not a fabricated recap).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from tests.conftest import open_automated_work_gate


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def llm_client(app):
    """LLM gate open only — NOT enough for the recap (automated work)."""
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


@pytest.fixture
def work_client(app):
    with TestClient(app) as c:
        open_automated_work_gate(c)
        yield c


def test_weekly_recap_zero_week_is_honest(work_client):
    res = work_client.get("/api/digest/camp-recap-1/weekly-recap")
    assert res.status_code == 200
    body = res.json()
    assert body["subject"] == "Your weekly recap"
    assert body["applications_sent"] == 0
    # A zero week says so in first person — never a fabricated count.
    assert "didn't send any" in body["body"]
    # No funnel data yet -> no "best source" is invented.
    assert body["best_source"] is None


def test_weekly_recap_counts_a_real_submission(work_client):
    from applicant.core.entities.application import Application
    from applicant.core.entities.submission_snapshot import SubmissionSnapshot
    from applicant.core.ids import (
        ApplicationId,
        CampaignId,
        JobPostingId,
        SubmissionSnapshotId,
        new_id,
    )

    storage = work_client.app.state.container.storage
    cid = "camp-recap-2"
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=CampaignId(cid), posting_id=JobPostingId(""))
    )
    storage.submission_snapshots.add(
        SubmissionSnapshot(
            id=SubmissionSnapshotId(new_id()),
            application_id=aid,
            captured_at=datetime.now(UTC),
        )
    )
    storage.commit()

    res = work_client.get(f"/api/digest/{cid}/weekly-recap")
    assert res.status_code == 200
    body = res.json()
    assert body["applications_sent"] == 1
    assert "I sent 1 application" in body["body"]


def test_weekly_recap_is_gated_like_its_digest_siblings(llm_client):
    # require_automated_work: LLM-only setup is not enough — same 409 as
    # GET /api/digest/{id} itself.
    assert llm_client.get("/api/digest/camp-x/weekly-recap").status_code == 409
