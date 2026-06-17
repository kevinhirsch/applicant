"""Container wiring of the sandbox backend (FR-SANDBOX-1, FR-STEALTH-1).

The composition root selects the sandbox backend by SANDBOX_BACKEND and threads the
derived stealth persona into the browser. The native proxmox-windows backend is
gated on the OOBE sandbox-connection step: until it is configured the container falls
back to LocalSandbox so the app still boots (no Proxmox reachable here).
"""

from __future__ import annotations

import pytest

from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.app.config import Settings
from applicant.app.container import build_container


@pytest.mark.unit
def test_local_backend_wires_local_sandbox():
    container = build_container(Settings(SANDBOX_BACKEND="local"))
    assert isinstance(container.sandbox, LocalSandbox)
    # Local backend -> coherent linux spoof persona on the browser.
    assert container.browser._persona == "linux"


@pytest.mark.unit
def test_proxmox_backend_falls_back_until_configured_but_persona_native():
    # No OOBE sandbox-connection step done -> backend not usable yet, so the app
    # still boots on LocalSandbox; the persona is already native (it IS Windows).
    container = build_container(Settings(SANDBOX_BACKEND="proxmox-windows"))
    assert isinstance(container.sandbox, LocalSandbox)
    assert container.browser._persona == "native"
    # The automated-work gate stays closed until the connection is collected.
    assert container.setup_service.is_sandbox_backend_ready() is False
