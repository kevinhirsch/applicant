"""Blanket ``bash -n`` syntax check over every deploy/lifecycle script (P3-1).

install.sh, update.sh, backup.sh, restore.sh, and backup-restore-drill.sh each
already had their own ``bash -n`` regression test; proxmox-deploy.sh and
updater-daemon.sh did not, so a syntax regression in either would only be
caught at real-deploy time (a Proxmox VM boot or the updater sidecar starting).
This closes that gap generically: every ``*.sh`` directly under ``scripts/``
(not its ``lib/`` helpers, which are sourced fragments, not standalone
scripts) gets a syntax check, so a new script added later is covered
automatically without a new test file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_SCRIPTS = sorted(_SCRIPTS_DIR.glob("*.sh"))


def test_at_least_the_known_lifecycle_scripts_are_present():
    names = {p.name for p in _SCRIPTS}
    for expected in (
        "install.sh",
        "update.sh",
        "proxmox-deploy.sh",
        "backup.sh",
        "restore.sh",
        "backup-restore-drill.sh",
        "updater-daemon.sh",
    ):
        assert expected in names, f"expected script scripts/{expected} not found"


@pytest.mark.parametrize("script", _SCRIPTS, ids=lambda p: p.name)
def test_script_is_valid_bash(script: Path):
    res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, f"{script.name}: {res.stderr}"
