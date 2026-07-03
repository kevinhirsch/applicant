"""Manual PII-retention sweep trigger (dark-engine audit item 37).

``DataLifecycleService.prune_pii_older_than`` (#363) was previously reachable
ONLY from the dormant scheduler tick -- there was no way for an operator to run
a sweep on demand or see what it actually removed. This proves the wired
``POST /api/admin/retention/prune`` route end-to-end: real per-store pruned
counts from the SAME process-lived ``container.storage`` instance the
scheduler would read, the persisted Settings > Automation retention window
used as the default (mirroring what a scheduled sweep would use), and an
explicit ``?days=`` override that applies to just that one run without being
persisted.

Hermetic: in-memory storage (the green-increment lane forces ``DATABASE_URL``
unreachable), real container services, LLM gate opened like the peer router
tests (``test_admin_lessons_route.py``).
"""

from __future__ import annotations

import datetime as _dt

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.ids import AttributeId, CampaignId, OnboardingProfileId, new_id


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        # Open the LLM gate (the router carries require_llm_configured).
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _registered_paths(app) -> set[str]:
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


def test_retention_prune_route_is_registered(client):
    paths = _registered_paths(client.app)
    assert "/api/admin/retention/prune" in paths


def test_default_window_zero_is_a_well_formed_no_op(client):
    """No operator has ever saved a retention window -- 0 means keep forever,
    a legitimate no-op, not an error."""
    r = client.post("/api/admin/retention/prune")
    assert r.status_code == 200
    body = r.json()
    assert body["skipped"] is True
    assert body["pruned"] == 0
    assert body["requested_days"] == 0
    assert body["by_store"] == {}


def test_sweep_uses_persisted_retention_days_and_prunes_real_rows(client):
    # Seed the SAME process-lived storage the route's DataLifecycleService reads.
    storage = client.app.state.container.storage
    cid = CampaignId(new_id())
    now = _dt.datetime.now(_dt.UTC)
    old = now - _dt.timedelta(days=120)
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="phone", value="555"),
        recorded_at=old,
    )
    storage.onboarding_profiles.add(
        OnboardingProfile(id=OnboardingProfileId(new_id()), campaign_id=cid, intake={"x": 1}),
        recorded_at=old,
    )
    # In-window PII (recorded just now) must be retained.
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="email", value="a@b.c"),
        recorded_at=now,
    )

    put = client.put("/api/setup/automation", json={"pii_retention_days": 30})
    assert put.status_code == 204

    r = client.post("/api/admin/retention/prune")
    assert r.status_code == 200
    body = r.json()
    assert body.get("skipped") is not True
    assert body["requested_days"] == 30
    assert body["window_days"] == 30
    assert body["pruned"] == 2
    assert body["by_store"]["attributes"] == 1
    assert body["by_store"]["onboarding_profiles"] == 1

    # Old attribute pruned; in-window one retained -- proves the real cascade ran.
    remaining = storage.attributes.list_for_campaign(cid)
    assert len(remaining) == 1
    assert remaining[0].name == "email"
    assert storage.onboarding_profiles.get_for_campaign(cid) is None


def test_explicit_days_override_applies_once_and_is_not_persisted(client):
    storage = client.app.state.container.storage
    cid = CampaignId(new_id())
    old = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=10)
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name="phone", value="555"),
        recorded_at=old,
    )

    # Persisted window stays at the default (0 = keep forever); the explicit
    # ?days=5 overrides just THIS run.
    r = client.post("/api/admin/retention/prune", params={"days": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["requested_days"] == 5
    assert body["window_days"] == 5
    assert body["pruned"] == 1
    assert storage.attributes.list_for_campaign(cid) == []

    prefs = client.get("/api/setup/automation").json()
    assert prefs["pii_retention_days"] == 0

    # A follow-up sweep with no override falls back to the persisted 0 (skip).
    r2 = client.post("/api/admin/retention/prune")
    assert r2.json()["skipped"] is True
