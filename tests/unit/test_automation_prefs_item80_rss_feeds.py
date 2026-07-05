"""Settings > Automation persistence for ``discovery_rss_feeds`` (dark-engine audit
item 80, B7): "RSS discovery sources are hardcoded with no add-feed UI."

Mirrors item 101's (``discovery_proxies``) own test shape exactly (see
``test_automation_prefs_batch_b8b.py``) -- same ``AutomationPrefsIn`` field,
same SSRF/format validation (``validate_operator_urls``), same status codes.

Two layers of coverage, matching that file's own shape:

  1. ``SetupService.get_automation_prefs``/``set_automation_prefs`` directly
     (config-store persistence + validation), and
  2. ``GET``/``PUT /api/setup/automation`` through a real app so the
     env-default merge in the router (``get_automation_prefs`` in
     ``setup.py``) is proven, not just the service.

Each assertion here was hand-verified to go RED when the corresponding piece
of the wiring is reverted (file-copy backup, never ``git stash`` -- shared
across sibling worktrees in this session), then GREEN again after restoring.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.main import create_app
from applicant.application.services.setup_service import SetupService


def _svc(store=None) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore())


# ── SetupService: persistence + validation ─────────────────────────────────


def test_get_automation_prefs_is_empty_before_anything_is_saved():
    svc = _svc()
    prefs = svc.get_automation_prefs()
    assert "discovery_rss_feeds" not in prefs


def test_set_then_get_round_trips_the_feed_list():
    svc = _svc()
    svc.set_automation_prefs(
        discovery_rss_feeds="https://boards.example.com/careers.rss,https://other.example.com/jobs.atom"
    )
    prefs = svc.get_automation_prefs()
    assert prefs["discovery_rss_feeds"] == (
        "https://boards.example.com/careers.rss,https://other.example.com/jobs.atom"
    )


def test_empty_discovery_rss_feeds_is_allowed():
    """Empty string is a legitimate value -- it means "no custom feeds, use only
    the built-in default" -- and must not be rejected as invalid."""
    svc = _svc()
    svc.set_automation_prefs(discovery_rss_feeds="")
    prefs = svc.get_automation_prefs()
    assert prefs["discovery_rss_feeds"] == ""


def test_discovery_rss_feeds_rejects_a_disallowed_scheme():
    """SSRF guard (item 12), exactly like ``discovery_proxies``: a ``file://``
    entry is rejected via ``InvalidInput`` (a ``DomainError``, mapped to 422 at
    the router), not a plain ``ValueError``."""
    from applicant.core.errors import InvalidInput

    svc = _svc()
    with pytest.raises(InvalidInput):
        svc.set_automation_prefs(discovery_rss_feeds="file:///etc/passwd")
    assert svc.get_automation_prefs() == {}


def test_discovery_rss_feeds_rejects_the_cloud_metadata_address():
    from applicant.core.errors import InvalidInput

    svc = _svc()
    with pytest.raises(InvalidInput):
        svc.set_automation_prefs(
            discovery_rss_feeds="http://169.254.169.254/latest/meta-data/"
        )
    assert svc.get_automation_prefs() == {}


def test_partial_save_leaves_discovery_rss_feeds_untouched():
    svc = _svc()
    svc.set_automation_prefs(discovery_rss_feeds="https://boards.example.com/careers.rss")
    svc.set_automation_prefs(egress_timezone="America/New_York")
    prefs = svc.get_automation_prefs()
    assert prefs["discovery_rss_feeds"] == "https://boards.example.com/careers.rss"
    assert prefs["egress_timezone"] == "America/New_York"


# ── router: GET/PUT /api/setup/automation ───────────────────────────────────


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_get_defaults_to_settings_value_when_nothing_persisted(client):
    """Before any operator save, GET must reflect the real env-sourced
    ``Settings`` default (config.py) -- empty, matching today's hardcoded-only
    behavior with no config."""
    prefs = client.get("/api/setup/automation").json()
    assert prefs["discovery_rss_feeds"] == ""


def test_put_persists_and_round_trips_on_next_get(client):
    put = client.put(
        "/api/setup/automation",
        json={"discovery_rss_feeds": "https://boards.example.com/careers.rss"},
    )
    assert put.status_code == 204
    prefs = client.get("/api/setup/automation").json()
    assert prefs["discovery_rss_feeds"] == "https://boards.example.com/careers.rss"


def test_put_rejects_malformed_discovery_rss_feed_with_422(client):
    """SSRF-checked via ``validate_operator_urls`` (item 12), raising the domain
    ``InvalidInput`` -- mapped to 422 by the global handler, distinct from the
    plain-``ValueError``-derived 400s (matches ``discovery_proxies``'s own
    behavior exactly)."""
    resp = client.put(
        "/api/setup/automation", json={"discovery_rss_feeds": "file:///etc/passwd"}
    )
    assert resp.status_code == 422
    assert "disallowed scheme" in resp.json()["detail"]


def test_put_a_field_other_than_discovery_rss_feeds_leaves_it_untouched(client):
    client.put(
        "/api/setup/automation",
        json={"discovery_rss_feeds": "https://boards.example.com/careers.rss"},
    )
    resp = client.put("/api/setup/automation", json={"resume_render": "off"})
    assert resp.status_code == 204
    prefs = client.get("/api/setup/automation").json()
    assert prefs["discovery_rss_feeds"] == "https://boards.example.com/careers.rss"
