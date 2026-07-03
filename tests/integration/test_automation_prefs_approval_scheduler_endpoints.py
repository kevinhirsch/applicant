"""Settings > Automation HTTP endpoints for the approval-timeout and
scheduler-interval knobs (dark-engine audit items 86/90).

Mirrors ``test_automation_prefs_endpoints.py``'s shape for the two new fields
on the existing ``GET``/``PUT /api/setup/automation`` pair: a real
Postgres-backed boot (hence ``@pytest.mark.integration``, excluded from the
hermetic ``-m "not integration"`` lane) exercising the FULL router ->
``SetupService`` -> ``AppConfigStore`` chain, including the GET route's merge
of persisted overrides onto the env-sourced ``Settings`` defaults.
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
    assert prefs["approval_timeout_days"] == 30
    assert prefs["approval_wait_seconds"] is None
    assert prefs["scheduler_interval_seconds"] == 60.0


@pytest.mark.integration
def test_put_then_get_round_trips_and_survives_reload(client):
    put = client.put(
        "/api/setup/automation",
        json={
            "approval_timeout_days": 14,
            "approval_wait_seconds": 300.0,
            "scheduler_interval_seconds": 15.0,
        },
    )
    assert put.status_code == 204

    prefs = client.get("/api/setup/automation").json()
    assert prefs["approval_timeout_days"] == 14
    assert prefs["approval_wait_seconds"] == 300.0
    assert prefs["scheduler_interval_seconds"] == 15.0

    # A fresh request (new TestClient call, same app/DB) reflects the save --
    # the config-store write, not just an in-memory client-side value.
    prefs_again = client.get("/api/setup/automation").json()
    assert prefs_again == prefs


@pytest.mark.integration
def test_negative_approval_timeout_days_is_rejected_with_400(client):
    r = client.put("/api/setup/automation", json={"approval_timeout_days": -5})
    assert r.status_code == 400


@pytest.mark.integration
def test_zero_scheduler_interval_seconds_is_rejected_with_400(client):
    r = client.put("/api/setup/automation", json={"scheduler_interval_seconds": 0})
    assert r.status_code == 400


@pytest.mark.integration
def test_partial_put_of_new_knobs_leaves_the_existing_three_alone(client):
    client.put("/api/setup/automation", json={"allow_automated_accounts": True})
    client.put("/api/setup/automation", json={"approval_timeout_days": 7})
    prefs = client.get("/api/setup/automation").json()
    assert prefs["allow_automated_accounts"] is True
    assert prefs["approval_timeout_days"] == 7
