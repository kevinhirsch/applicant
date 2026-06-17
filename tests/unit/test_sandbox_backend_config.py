"""SANDBOX_BACKEND + STEALTH_PERSONA config validation + derivation (FR-SANDBOX-1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from applicant.app.config import (
    PROXMOX_CLONE_SNAPSHOT_REVERT,
    SANDBOX_BACKEND_LOCAL,
    SANDBOX_BACKEND_PROXMOX_WINDOWS,
    STEALTH_PERSONA_LINUX,
    STEALTH_PERSONA_NATIVE,
    Settings,
)


@pytest.mark.unit
class TestSandboxBackendConfig:
    def test_default_is_local(self):
        s = Settings()
        assert s.sandbox_backend == SANDBOX_BACKEND_LOCAL
        assert s.is_proxmox_windows_backend is False

    def test_proxmox_windows_selectable(self):
        s = Settings(SANDBOX_BACKEND="proxmox-windows")
        assert s.sandbox_backend == SANDBOX_BACKEND_PROXMOX_WINDOWS
        assert s.is_proxmox_windows_backend is True

    def test_invalid_backend_rejected(self):
        with pytest.raises(ValidationError):
            Settings(SANDBOX_BACKEND="aws-windows")

    def test_persona_derives_native_for_proxmox(self):
        s = Settings(SANDBOX_BACKEND="proxmox-windows")
        # No explicit persona -> derived from the backend (it IS Windows).
        assert s.stealth_persona == ""
        assert s.stealth_persona_resolved == STEALTH_PERSONA_NATIVE

    def test_persona_derives_linux_for_local(self):
        s = Settings(SANDBOX_BACKEND="local")
        assert s.stealth_persona_resolved == STEALTH_PERSONA_LINUX

    def test_explicit_persona_wins(self):
        s = Settings(SANDBOX_BACKEND="proxmox-windows", STEALTH_PERSONA="linux")
        assert s.stealth_persona_resolved == STEALTH_PERSONA_LINUX

    def test_invalid_persona_rejected(self):
        with pytest.raises(ValidationError):
            Settings(STEALTH_PERSONA="windows-spoof")

    def test_clone_mode_default_and_validation(self):
        assert Settings().proxmox_clone_mode == PROXMOX_CLONE_SNAPSHOT_REVERT
        with pytest.raises(ValidationError):
            Settings(PROXMOX_CLONE_MODE="full-clone-always")

    def test_takeover_method_validation(self):
        assert Settings(PROXMOX_TAKEOVER_METHOD="web-console").proxmox_takeover_method == (
            "web-console"
        )
        with pytest.raises(ValidationError):
            Settings(PROXMOX_TAKEOVER_METHOD="vnc-direct")
