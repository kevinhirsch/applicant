"""Native Proxmox Windows VM sandbox backend (FR-SANDBOX-1/4, FR-STEALTH-1).

Drives the :class:`ProxmoxWindowsSandbox` adapter with the in-memory
:class:`FakeProxmoxClient` so the whole provision/teardown lifecycle, CDP-endpoint
wiring, snapshot-revert vs linked-clone bookkeeping, and the tokenized RDP takeover
URL are unit-tested with NO Proxmox / Windows / CDP / RDP (the default lane).
"""

from __future__ import annotations

import pytest

from applicant.adapters.sandbox.proxmox_client import (
    FakeProxmoxClient,
    chrome_cdp_command,
)
from applicant.adapters.sandbox.proxmox_windows_sandbox import (
    CLEAN_SNAPSHOT,
    ProxmoxWindowsSandbox,
)
from applicant.adapters.sandbox.remote_view import WindowsRdpRemoteView
from applicant.core.ids import ApplicationId, new_id
from applicant.ports.driven.sandbox import (
    RemoteViewPort,
    SandboxPort,
    SandboxSession,
)


def _sandbox(*, clone_mode="snapshot-revert", method="rdp", url_template=""):
    client = FakeProxmoxClient()
    client.register_template(9000)
    rv = WindowsRdpRemoteView(method=method, url_template=url_template)
    return (
        ProxmoxWindowsSandbox(
            client,
            template_vmid=9000,
            node="pve1",
            clone_mode=clone_mode,
            cdp_port=9222,
            remote_view=rv,
        ),
        client,
    )


@pytest.mark.unit
class TestProxmoxWindowsSandbox:
    def test_satisfies_sandbox_port(self):
        sandbox, _ = _sandbox()
        assert isinstance(sandbox, SandboxPort)
        assert isinstance(sandbox.remote_view(), RemoteViewPort)

    def test_provision_returns_cdp_and_takeover(self):
        sandbox, client = _sandbox()
        aid = ApplicationId(new_id())
        session = sandbox.provision(aid)
        assert isinstance(session, SandboxSession)
        # CDP endpoint wired to the guest IP + port (the engine drives THIS browser).
        assert session.cdp_endpoint == "http://10.0.0.50:9222"
        # Tokenized RDP takeover URL (one-click).
        assert session.remote_view_url.startswith("rdp://")
        assert "token=" in session.remote_view_url

    def test_provision_launches_chrome_over_cdp(self):
        sandbox, client = _sandbox()
        sandbox.provision(ApplicationId(new_id()))
        # The guest_exec launched Chrome with --remote-debugging-port/-address.
        assert client.exec_log, "expected a guest_exec Chrome-CDP launch"
        _, cmd = client.exec_log[-1]
        assert cmd == chrome_cdp_command(port=9222, address="0.0.0.0")
        assert any("--remote-debugging-port=9222" in p for p in cmd)
        assert any("--remote-debugging-address=0.0.0.0" in p for p in cmd)

    def test_snapshot_revert_mode_rolls_back_and_starts_persistent_vm(self):
        sandbox, client = _sandbox(clone_mode="snapshot-revert")
        sandbox.provision(ApplicationId(new_id()))
        # No clone created; the persistent template VMID is reverted + started.
        assert client.cloned == []
        assert client.rolled_back.get(9000) == CLEAN_SNAPSHOT
        assert client.vm_status(9000) == "running"

    def test_linked_clone_mode_clones_per_session(self):
        sandbox, client = _sandbox(clone_mode="linked-clone")
        sandbox.provision(ApplicationId(new_id()))
        assert len(client.cloned) == 1
        cloned_vmid = client.cloned[0]
        assert client.vm_status(cloned_vmid) == "running"

    def test_teardown_linked_clone_destroys_and_invalidates(self):
        sandbox, client = _sandbox(clone_mode="linked-clone")
        session = sandbox.provision(ApplicationId(new_id()))
        cloned_vmid = client.cloned[0]
        sandbox.teardown(session.session_id)
        # Clone destroyed, session gone, takeover token invalidated.
        assert cloned_vmid not in client.existing
        assert sandbox.get(session.session_id) is None
        assert sandbox.remote_view().token_valid(session.session_id, "anything") is False

    def test_teardown_snapshot_revert_keeps_vm_but_reverts(self):
        sandbox, client = _sandbox(clone_mode="snapshot-revert")
        session = sandbox.provision(ApplicationId(new_id()))
        sandbox.teardown(session.session_id)
        # Persistent VM kept (still exists), stopped, and reverted to clean snapshot.
        assert 9000 in client.existing
        assert client.vm_status(9000) == "stopped"
        assert client.rolled_back.get(9000) == CLEAN_SNAPSHOT

    def test_teardown_is_idempotent(self):
        sandbox, _ = _sandbox()
        session = sandbox.provision(ApplicationId(new_id()))
        sandbox.teardown(session.session_id)
        sandbox.teardown(session.session_id)  # no error

    def test_multi_session_and_for_application(self):
        sandbox, _ = _sandbox(clone_mode="linked-clone")
        a1, a2 = ApplicationId(new_id()), ApplicationId(new_id())
        s1 = sandbox.provision(a1)
        s2 = sandbox.provision(a2)
        assert s1.session_id != s2.session_id
        assert sandbox.active_count() == 2
        assert sandbox.for_application(a1).session_id == s1.session_id
        sandbox.teardown(s1.session_id)
        assert sandbox.for_application(a1) is None
        assert sandbox.active_count() == 1

    def test_web_console_takeover_uses_template(self):
        sandbox, _ = _sandbox(
            method="web-console",
            url_template="https://guac.local/?host={host}&token={token}&vmid={vmid}",
        )
        session = sandbox.provision(ApplicationId(new_id()))
        assert session.remote_view_url.startswith("https://guac.local/?host=")
        assert "token=" in session.remote_view_url

    def test_app_url_carried_for_continuity(self):
        client = FakeProxmoxClient()
        client.register_template(9000)
        sandbox = ProxmoxWindowsSandbox(
            client,
            template_vmid=9000,
            node="pve1",
            app_url_for=lambda aid: "https://acme.example/apply/123",
        )
        session = sandbox.provision(ApplicationId(new_id()))
        assert session.application_url == "https://acme.example/apply/123"
