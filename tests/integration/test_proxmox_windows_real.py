"""Real Proxmox Windows VM sandbox integration (FR-SANDBOX-1) — integration-gated.

Drives the REAL :class:`ProxmoxApiClient` against a running Proxmox node with a
licensed Windows VM (Chrome + qemu-guest-agent + RDP). Skipped unless
``PROXMOX_API_URL`` (+ token id/secret/node/template VMID) point at a reachable
node, so the default lane stays hermetic (no Proxmox / Windows / CDP / RDP).

To run against a real node:
    PROXMOX_API_URL=https://pve:8006 PROXMOX_NODE=pve1 \\
        PROXMOX_TOKEN_ID='root@pam!applicant' PROXMOX_TOKEN_SECRET=... \\
        PROXMOX_TEMPLATE_VMID=9000 \\
        uv run pytest -m integration tests/integration/test_proxmox_windows_real.py
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

_API = os.getenv("PROXMOX_API_URL", "")

skip_no_pve = pytest.mark.skipif(
    not _API,
    reason="Set PROXMOX_API_URL (+ token id/secret, node, template VMID) for a real PVE node.",
)


@skip_no_pve
def test_real_proxmox_windows_lifecycle():  # pragma: no cover - integration
    from applicant.adapters.sandbox.proxmox_client import ProxmoxApiClient
    from applicant.adapters.sandbox.proxmox_windows_sandbox import ProxmoxWindowsSandbox
    from applicant.adapters.sandbox.remote_view import WindowsRdpRemoteView
    from applicant.core.ids import ApplicationId, new_id

    client = ProxmoxApiClient(
        api_url=_API,
        token_id=os.environ["PROXMOX_TOKEN_ID"],
        token_secret=os.environ["PROXMOX_TOKEN_SECRET"],
        node=os.environ["PROXMOX_NODE"],
        verify_tls=os.getenv("PROXMOX_VERIFY_TLS", "1") != "0",
    )
    sandbox = ProxmoxWindowsSandbox(
        client,
        template_vmid=int(os.environ["PROXMOX_TEMPLATE_VMID"]),
        node=os.environ["PROXMOX_NODE"],
        clone_mode=os.getenv("PROXMOX_CLONE_MODE", "snapshot-revert"),
        remote_view=WindowsRdpRemoteView(),
    )
    session = sandbox.provision(ApplicationId(new_id()))
    try:
        assert session.cdp_endpoint  # reachable Chrome CDP endpoint on the Windows VM
        assert session.remote_view_url.startswith("rdp://")
    finally:
        sandbox.teardown(session.session_id)
