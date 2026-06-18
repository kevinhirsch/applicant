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
def test_browser_real_defaults_off_so_ci_is_hermetic(monkeypatch):
    # Without BROWSER_REAL the engine uses the in-memory FakePageSource (no browser
    # binary) — tests/CI stay deterministic and browserless.
    monkeypatch.delenv("BROWSER_REAL", raising=False)
    container = build_container(Settings(_env_file=None))
    assert container.browser._use_real_browser is False


@pytest.mark.unit
def test_browser_real_setting_drives_real_browser():
    # BROWSER_REAL=true (the production default in docker-compose.prod.yml) makes the
    # container launch a real Chrome/Chromium for pre-fill (FR-PREFILL-1/2). Without
    # this wiring the engine would only ever SIMULATE pre-fill.
    container = build_container(Settings(_env_file=None, BROWSER_REAL=True))
    assert container.browser._use_real_browser is True


@pytest.mark.unit
def test_browser_profiles_dir_is_wired_from_settings():
    # FR-STEALTH-3: the per-tenant profile root is configurable so the deploy persists
    # signed-in sessions on a named volume (sign in once, reuse across applications).
    container = build_container(Settings(_env_file=None, BROWSER_PROFILES_DIR="/data/profiles"))
    assert container.browser._profiles._root == "/data/profiles"


@pytest.mark.unit
def test_proxmox_backend_falls_back_until_configured_but_persona_native():
    # No OOBE sandbox-connection step done -> backend not usable yet, so the app
    # still boots on LocalSandbox; the persona is already native (it IS Windows).
    container = build_container(Settings(SANDBOX_BACKEND="proxmox-windows"))
    assert isinstance(container.sandbox, LocalSandbox)
    assert container.browser._persona == "native"
    # The automated-work gate stays closed until the connection is collected.
    assert container.setup_service.is_sandbox_backend_ready() is False
