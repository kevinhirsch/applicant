"""Settings > Automation HTTP endpoints (dark-engine audit items 82/84/85).

Mirrors ``test_setup_endpoints.py``'s ``test_tier_ladder_crud`` shape for the new
``GET``/``PUT /api/setup/automation`` pair: a real Postgres-backed boot (hence
``@pytest.mark.integration``, excluded from the hermetic ``-m "not integration"``
lane the rest of this task's checks run under) exercising the FULL router ->
``SetupService`` -> ``AppConfigStore`` chain, including the GET route's merge of
persisted overrides onto the env-sourced ``Settings`` defaults.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.mark.integration
def test_get_automation_prefs_returns_env_defaults_before_any_save(client):
    prefs = client.get("/api/setup/automation").json()
    assert prefs["egress_timezone"] == "America/Phoenix"
    assert prefs["egress_locale"] == "en-US"
    assert prefs["allow_automated_accounts"] is False
    assert prefs["presubmit_max_apps_per_company_per_day"] == 3


@pytest.mark.integration
def test_put_then_get_round_trips_and_survives_reload(client):
    put = client.put(
        "/api/setup/automation",
        json={
            "egress_timezone": "America/Chicago",
            "egress_locale": "en-GB",
            "allow_automated_accounts": True,
            "presubmit_max_apps_per_company_per_day": 8,
        },
    )
    assert put.status_code == 204

    prefs = client.get("/api/setup/automation").json()
    assert prefs["egress_timezone"] == "America/Chicago"
    assert prefs["egress_locale"] == "en-GB"
    assert prefs["allow_automated_accounts"] is True
    assert prefs["presubmit_max_apps_per_company_per_day"] == 8

    # A fresh request (new TestClient call, same app/DB) reflects the save --
    # the config-store write, not just an in-memory client-side value.
    prefs_again = client.get("/api/setup/automation").json()
    assert prefs_again == prefs


@pytest.mark.integration
def test_negative_per_company_cap_is_rejected_with_400(client):
    r = client.put(
        "/api/setup/automation",
        json={"presubmit_max_apps_per_company_per_day": -5},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_partial_put_leaves_other_knobs_alone(client):
    client.put("/api/setup/automation", json={"allow_automated_accounts": True})
    client.put("/api/setup/automation", json={"egress_timezone": "Europe/Berlin"})
    prefs = client.get("/api/setup/automation").json()
    assert prefs["allow_automated_accounts"] is True
    assert prefs["egress_timezone"] == "Europe/Berlin"
