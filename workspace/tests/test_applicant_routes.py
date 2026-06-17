"""Hermetic test for GET /api/applicant/features (routes/applicant_routes.py).

Mounts only the applicant router on a bare FastAPI app and monkeypatches the
feature computation so the endpoint is exercised without an engine. Also asserts
the endpoint never propagates an exception (always returns a payload).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_routes as applicant_routes
from routes.applicant_routes import setup_applicant_routes


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(setup_applicant_routes())
    return TestClient(app)


def test_features_endpoint_returns_computed_payload(client, monkeypatch):
    payload = {
        "engine_available": True,
        "engine_url": "http://api:8000",
        "sections": {"compare": {"key": "compare", "state": "disabled"}},
    }
    monkeypatch.setattr(applicant_routes, "compute_features", lambda: payload)

    resp = client.get("/api/applicant/features")
    assert resp.status_code == 200
    assert resp.json() == payload


def test_features_endpoint_degrades_on_internal_error(client, monkeypatch):
    def boom():
        raise RuntimeError("engine layer blew up")

    monkeypatch.setattr(applicant_routes, "compute_features", boom)

    resp = client.get("/api/applicant/features")
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine_available"] is False
    assert body["sections"] == {}
