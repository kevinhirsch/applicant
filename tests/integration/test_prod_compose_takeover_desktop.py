"""Prod compose: parameterized takeover-desktop service (FR-SANDBOX-2/3).

The takeover desktop is a containerized, web-streamed Ubuntu desktop (DE = an image
swap via TAKEOVER_DESKTOP_IMAGE). These tests assert the service exists with the
shm/security bits the desktop images need, defaults to the Cinnamon webtop, and that
the full prod compose still validates (`docker compose ... config`, docker-gated).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_COMPOSE = Path(__file__).resolve().parents[2] / "docker" / "docker-compose.prod.yml"


@pytest.mark.integration
def test_takeover_desktop_service_parameterized_and_hardened():
    spec = yaml.safe_load(_COMPOSE.read_text())
    svc = spec["services"]["takeover-desktop"]

    # DE is an image swap; defaults to the Cinnamon webtop, override via env.
    assert "TAKEOVER_DESKTOP_IMAGE" in svc["image"]
    assert "ubuntu-cinnamon" in svc["image"]  # default DE

    # Desktop images need a large /dev/shm + relaxed seccomp (browser + DE).
    assert svc["shm_size"]
    assert any("seccomp" in opt for opt in svc.get("security_opt", []))

    # Opt-in (profile) so it does not auto-start; existing services untouched.
    assert "takeover" in svc.get("profiles", [])
    assert "api" in spec["services"] and "postgres" in spec["services"]


@pytest.mark.integration
def test_prod_compose_config_validates():
    if shutil.which("docker") is None:  # integration-gated: no Docker in the hermetic lane
        pytest.skip("docker not available; compose validation is integration-gated.")
    proc = subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE), "config"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
