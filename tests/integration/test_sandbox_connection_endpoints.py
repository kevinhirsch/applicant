"""Sandbox-connection OOBE endpoints: collect + vault + non-secret readback (FR-OOBE)."""

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
def test_collect_sandbox_connection_and_readback(client):
    # Not configured initially.
    g0 = client.get("/api/setup/sandbox-connection").json()
    assert g0["configured"] is False

    body = {
        "proxmox_api_url": "https://pve.local:8006",
        "proxmox_node": "pve1",
        "proxmox_token_id": "root@pam!applicant",
        "proxmox_token_secret": "super-secret",
        "template_vmid": 9000,
        "clone_mode": "snapshot-revert",
        "cdp_port": 9222,
        "rdp_username": "Applicant",
        "rdp_password": "hunter2",
        "takeover_method": "rdp",
    }
    r = client.post("/api/setup/sandbox-connection", json=body)
    assert r.status_code == 204

    g1 = client.get("/api/setup/sandbox-connection").json()
    assert g1["configured"] is True
    conn = g1["connection"]
    # Non-secrets present; secrets NEVER returned (FR-VAULT-3, NFR-PRIV-1).
    assert conn["proxmox_node"] == "pve1"
    assert conn["template_vmid"] == 9000
    assert "proxmox_token_secret" not in conn
    assert "rdp_password" not in conn
    assert "token_secret" not in conn


@pytest.mark.integration
def test_missing_required_field_is_400(client):
    r = client.post(
        "/api/setup/sandbox-connection",
        json={
            "proxmox_api_url": "",
            "proxmox_node": "pve1",
            "proxmox_token_id": "x",
            "proxmox_token_secret": "y",
            "template_vmid": 9000,
        },
    )
    assert r.status_code == 400
