"""Dev/demo seed route — hard gate + coherent dataset + idempotent re-seed.

Audit §6 / quick-wins #49: "there is no seed/demo data path — the crawl opens
every surface empty... This single item unblocks every render below." This
proves the fix end to end:

  (a) HARD GATE — ``POST /api/dev/seed`` and ``POST /api/dev/seed/reset`` 404
      when ``APPLICANT_ALLOW_SEED`` is unset (the production default) and only
      become reachable with ``APPLICANT_ALLOW_SEED=1``;
  (b) the seeded dataset is coherent and well-formed: a campaign, varied
      postings, a pending digest row, a redline/document-review session, a
      submission snapshot, post-submission tracker rows in different states
      (awaiting-response, interview_invited), and heterogeneous Portal
      pending-actions — all reachable through the REAL front-door read routes
      (pending-actions, post-submission tracker), not just storage internals;
  (c) re-seeding is idempotent — a second POST replaces rather than
      duplicates rows;
  (d) reset purges the demo campaign cleanly and re-seeding after reset works.

Hermetic: in-memory storage, real container services, no LLM gate needed (the
seed route is deliberately NOT behind ``require_llm_configured`` — a fresh,
unconfigured instance is exactly when a demo seed is wanted).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.application.services.dev_seed import DEMO_CAMPAIGN_ID


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        # The seed route itself is gate-free (deliberately reachable pre-setup); the
        # front-door READ routes used to verify the seeded rows render for real
        # (pending-actions, post-submission tracker) carry the ordinary LLM gate, so
        # open it the same way every peer router test does.
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _registered_paths(app) -> set[str]:
    """All endpoint paths registered on the app (flattening the mount wrapper)."""
    paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    return paths


# --- (a) hard gate -----------------------------------------------------------


def test_seed_routes_are_registered(client):
    """The routes exist on the booted app regardless of the gate (gate is a
    per-request 404, not route non-registration) — mirrors the peer router
    reachability tests."""
    paths = _registered_paths(client.app)
    assert "/api/dev/seed" in paths
    assert "/api/dev/seed/reset" in paths


def test_seed_is_404_when_allow_seed_unset(client, monkeypatch):
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    r = client.post("/api/dev/seed")
    assert r.status_code == 404


def test_seed_reset_is_404_when_allow_seed_unset(client, monkeypatch):
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    r = client.post("/api/dev/seed/reset")
    assert r.status_code == 404


def test_seed_is_404_when_allow_seed_is_not_exactly_one(client, monkeypatch):
    """Anything other than the literal string '1' must still refuse (no truthy
    coercion of 'true'/'yes'/etc — an exact, deliberate opt-in only)."""
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "true")
    r = client.post("/api/dev/seed")
    assert r.status_code == 404


def test_seed_is_reachable_when_allow_seed_is_one(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    r = client.post("/api/dev/seed")
    assert r.status_code == 200
    body = r.json()
    assert body["seeded"] is True
    assert body["campaign_id"] == DEMO_CAMPAIGN_ID


def test_seed_reset_is_reachable_when_allow_seed_is_one(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    r = client.post("/api/dev/seed/reset")
    assert r.status_code == 200
    assert r.json()["reset"] is True


def test_gate_reflects_env_flips_within_one_process(client, monkeypatch):
    """The gate is checked live per-request (no caching): flipping the env var
    mid-process changes reachability on the very next call."""
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    assert client.post("/api/dev/seed").status_code == 404

    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    assert client.post("/api/dev/seed").status_code == 200

    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    assert client.post("/api/dev/seed").status_code == 404


def test_demo_mode_env_enables_the_seed_route(client, monkeypatch):
    """``DEMO_MODE=1`` — the story's canonical gate — opens the seed route just
    like the ``APPLICANT_ALLOW_SEED`` alias, and unsetting it closes it again."""
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    assert client.post("/api/dev/seed").status_code == 404

    monkeypatch.setenv("DEMO_MODE", "1")
    assert client.post("/api/dev/seed").status_code == 200

    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert client.post("/api/dev/seed").status_code == 404


def test_status_endpoint_reports_active_state(client, monkeypatch):
    """``GET /api/dev/seed/status`` (banner state) is gated too, and reports
    ``demo_active`` off the seeded campaign row."""
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    # Gated like every other route on the seed router.
    assert client.get("/api/dev/seed/status").status_code == 404

    monkeypatch.setenv("DEMO_MODE", "1")
    # Before seeding: reachable but inactive.
    before = client.get("/api/dev/seed/status")
    assert before.status_code == 200
    assert before.json()["demo_active"] is False

    assert client.post("/api/dev/seed").status_code == 200
    after = client.get("/api/dev/seed/status")
    assert after.status_code == 200
    body = after.json()
    assert body["demo_active"] is True
    assert body["counts"]["applications"] >= 5


# --- (b) the seeded dataset is coherent + reachable via real routes ---------


def test_seed_produces_the_expected_coherent_dataset(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    r = client.post("/api/dev/seed")
    assert r.status_code == 200
    counts = r.json()["counts"]

    # Campaign + a real spread of postings/applications.
    assert counts["campaign"] == 1
    assert counts["postings"] >= 5
    assert counts["applications"] == counts["postings"]
    assert counts["resume_variants"] == 1
    # Two library documents (a résumé + a tailored cover letter) per P0-2.
    assert counts["materials"] == 2
    assert counts["revision_sessions"] == 1
    assert counts["submission_snapshots"] == 1
    assert counts["outcome_events"] >= 2
    # An activity trail (~15 rows) + a short run history (momentum/streak) per P0-2.
    assert 14 <= counts["action_events"] <= 16
    assert counts["agent_runs"] >= 3
    assert counts["pending_actions"] >= 4

    container = client.app.state.container
    storage = container.storage

    # The campaign is real and carries search criteria.
    demo_campaign = next(
        c for c in storage.campaigns.list() if str(c.id) == DEMO_CAMPAIGN_ID
    )
    assert demo_campaign.criteria.get("titles")
    assert demo_campaign.active is True

    # Postings vary in company/title/source (not just copy-pasted rows).
    postings = storage.postings.list_for_campaign(demo_campaign.id)
    assert len({p.company for p in postings}) == len(postings)
    assert len({p.source_key for p in postings}) >= 4
    for p in postings:
        assert p.viability_score is not None

    # A generated material + an OPEN revision session (the redline target).
    materials = [m for m in storage.documents.list_for_campaign(demo_campaign.id)]
    assert materials
    revision = storage.revisions.get_for_material(materials[0].id)
    assert revision is not None
    assert revision.turns

    # A submission snapshot exists for one application.
    apps = storage.applications.list_for_campaign(demo_campaign.id)
    snapshotted = [
        a for a in apps if storage.submission_snapshots.get_for_application(a.id)
    ]
    assert snapshotted


def test_seed_pending_actions_are_reachable_and_heterogeneous(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    assert client.post("/api/dev/seed").status_code == 200

    r = client.get(f"/api/pending-actions/{DEMO_CAMPAIGN_ID}")
    assert r.status_code == 200
    body = r.json()
    rows = body["items"]
    assert isinstance(rows, list)
    assert len(rows) >= 4
    kinds = {row["kind"] for row in rows}
    # At least the three kinds explicitly called out by the audit item: a held
    # change to approve, a missing-detail prompt, and a final-approval decision
    # — plus the digest/material/question kinds already covered.
    assert "integral_change" in kinds
    assert "missing_attr" in kinds
    assert "final_approval" in kinds
    assert "digest_approval" in kinds
    assert "material_review" in kinds
    assert "agent_question" in kinds


def test_seed_tracker_rows_cover_multiple_post_submission_states(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    assert client.post("/api/dev/seed").status_code == 200

    r = client.get(f"/api/post-submission/{DEMO_CAMPAIGN_ID}")
    assert r.status_code == 200
    rows = r.json()["applications"]
    assert len(rows) >= 2
    statuses = {row["status"] for row in rows}
    assert "AWAITING_RESPONSE" in statuses

    # One AWAITING_RESPONSE row carries the interview_invited signal, the other
    # does not — a real "different states" spread, not two identical rows.
    awaiting = [row for row in rows if row["status"] == "AWAITING_RESPONSE"]
    assert len(awaiting) == 2
    signalled = [row for row in awaiting if "interview_invited" in row["signals"]]
    plain = [row for row in awaiting if not row["signals"]]
    assert signalled
    assert plain
    assert signalled[0]["submitted_at"] is not None


# --- (c) re-seed is idempotent ------------------------------------------------


def test_reseed_is_idempotent_not_duplicating(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    r1 = client.post("/api/dev/seed")
    r2 = client.post("/api/dev/seed")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["counts"] == r2.json()["counts"]

    container = client.app.state.container
    storage = container.storage
    postings = storage.postings.list_for_campaign(DEMO_CAMPAIGN_ID)
    apps = storage.applications.list_for_campaign(DEMO_CAMPAIGN_ID)
    # Ids stayed stable — no duplicate rows accumulated across two seeds.
    assert len({str(p.id) for p in postings}) == len(postings)
    assert len({str(a.id) for a in apps}) == len(apps)

    r = client.get(f"/api/pending-actions/{DEMO_CAMPAIGN_ID}")
    rows = r.json()["items"]
    kinds_count: dict[str, int] = {}
    for row in rows:
        kinds_count[row["kind"]] = kinds_count.get(row["kind"], 0) + 1
    # Each kind appears exactly once — a re-seed replaced, not piled up.
    assert all(count == 1 for count in kinds_count.values())


# --- (d) reset ----------------------------------------------------------------


def test_reset_purges_and_reseed_after_reset_works(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    assert client.post("/api/dev/seed").status_code == 200

    r = client.post("/api/dev/seed/reset")
    assert r.status_code == 200
    assert r.json()["counts"]["campaigns"] == 1

    container = client.app.state.container
    storage = container.storage
    assert storage.campaigns.get(DEMO_CAMPAIGN_ID) is None
    assert storage.postings.list_for_campaign(DEMO_CAMPAIGN_ID) == []

    # Reset on an already-absent campaign is a clean no-op (idempotent reset).
    r2 = client.post("/api/dev/seed/reset")
    assert r2.status_code == 200
    assert r2.json()["counts"].get("campaigns", 0) == 0

    # Re-seeding after a reset works cleanly.
    r3 = client.post("/api/dev/seed")
    assert r3.status_code == 200
    assert storage.campaigns.get(DEMO_CAMPAIGN_ID) is not None
