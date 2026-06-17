"""install.sh keeps the published host port and the heartbeat target in lock-step.

The prod compose publishes the front door on ``${APP_PORT:-8000}``. install.sh, by
contrast, only knew ``APP_URL`` — so a custom ``APP_URL`` port (e.g. ``:9000``) was
polled by the heartbeat while compose still published ``8000`` (its default),
producing a false "did not come up healthy" failure. The fix derives ``APP_PORT``
from ``APP_URL`` (unless explicitly set), EXPORTS it (so compose publishes it), and
persists it to ``.env`` (so updates stay consistent).

Hermetic: static text assertions plus an isolated run of just the derivation block —
the full ``--apply`` path is not exercised (it would build images and write the repo's
own ``.env``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install.sh"


def test_install_script_is_valid_bash():
    res = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_app_port_is_derived_exported_and_persisted():
    text = _SCRIPT.read_text(encoding="utf-8")
    # Derived from APP_URL when not explicitly provided, then exported for compose.
    assert 'APP_PORT="${APP_URL##*:}"' in text
    assert "export APP_PORT" in text
    # Persisted to .env so update.sh (which sources .env) publishes the same port.
    assert "APP_PORT=${APP_PORT}" in text
    # The heartbeat polls the very same APP_PORT (no second, divergent derivation).
    assert 'heartbeat "${APP_PORT}"' in text


# The exact derivation block lifted from install.sh; if the script's logic changes,
# the static assertions above will flag it and this snippet should be updated to match.
_DERIVE = r"""
set -euo pipefail
APP_URL="${APP_URL:-http://localhost:8000}"
if [[ -z "${APP_PORT:-}" ]]; then APP_PORT="${APP_URL##*:}"; fi
[[ "${APP_PORT}" =~ ^[0-9]+$ ]] || APP_PORT=8000
export APP_PORT
echo "${APP_PORT}"
"""


def _derive(app_url: str | None = None, app_port: str | None = None) -> str:
    env = {"PATH": "/usr/bin:/bin"}
    if app_url is not None:
        env["APP_URL"] = app_url
    if app_port is not None:
        env["APP_PORT"] = app_port
    res = subprocess.run(["bash", "-c", _DERIVE], capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_app_port_follows_app_url():
    assert _derive(app_url="http://localhost:9000") == "9000"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_explicit_app_port_wins_over_app_url():
    assert _derive(app_url="http://localhost:9000", app_port="7777") == "7777"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_app_port_falls_back_to_8000_on_garbage_url():
    assert _derive(app_url="not-a-url-no-port") == "8000"
    assert _derive() == "8000"
