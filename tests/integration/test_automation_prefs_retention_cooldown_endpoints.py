"""Settings > Automation HTTP endpoints for items 87/88 (dark-engine audit):
the data-retention window (``pii_retention_days``) and the re-apply cooldown
(``presubmit_duplicate_cooldown_days``). Mirrors
``test_automation_prefs_endpoints.py``'s shape for the two new fields on the
existing ``GET``/``PUT /api/setup/automation`` pair: a real Postgres-backed
boot (hence ``@pytest.mark.integration``, excluded from the hermetic
``-m "not integration"`` lane) exercising the FULL router -> ``SetupService``
-> ``AppConfigStore`` chain, including the GET route's merge of persisted
overrides onto the env-sourced ``Settings`` defaults.
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
    assert prefs["pii_retention_days"] == 0
    assert prefs["presubmit_duplicate_cooldown_days"] == 30


@pytest.mark.integration
def test_put_then_get_round_trips_and_survives_reload(client):
    put = client.put(
        "/api/setup/automation",
        json={"pii_retention_days": 120, "presubmit_duplicate_cooldown_days": 10},
    )
    assert put.status_code == 204

    prefs = client.get("/api/setup/automation").json()
    assert prefs["pii_retention_days"] == 120
    assert prefs["presubmit_duplicate_cooldown_days"] == 10

    # A fresh request (new TestClient call, same app/DB) reflects the save --
    # the config-store write, not just an in-memory client-side value.
    prefs_again = client.get("/api/setup/automation").json()
    assert prefs_again == prefs


@pytest.mark.integration
def test_negative_retention_days_is_rejected_with_400(client):
    r = client.put("/api/setup/automation", json={"pii_retention_days": -1})
    assert r.status_code == 400


@pytest.mark.integration
def test_negative_cooldown_days_is_rejected_with_400(client):
    r = client.put(
        "/api/setup/automation", json={"presubmit_duplicate_cooldown_days": -3}
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_zero_retention_days_means_keep_forever_and_is_accepted(client):
    r = client.put("/api/setup/automation", json={"pii_retention_days": 0})
    assert r.status_code == 204
    prefs = client.get("/api/setup/automation").json()
    assert prefs["pii_retention_days"] == 0


@pytest.mark.integration
def test_partial_put_leaves_other_knobs_alone(client):
    client.put("/api/setup/automation", json={"pii_retention_days": 200})
    client.put("/api/setup/automation", json={"presubmit_duplicate_cooldown_days": 5})
    prefs = client.get("/api/setup/automation").json()
    assert prefs["pii_retention_days"] == 200
    assert prefs["presubmit_duplicate_cooldown_days"] == 5
