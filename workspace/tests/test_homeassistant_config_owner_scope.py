"""HA config store: owner isolation + encrypted-token round-trip (Phase 4).

Isolated subprocess + temp DATABASE_URL, like the other DB-backed tests. The
encrypted token uses src.secret_storage, which self-creates its key dir, so no
extra setup is needed. Skips when app deps are absent.
"""

import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SCRIPT = r"""
import os, sys, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mkstemp(suffix=".db")[1]
try:
    import core.database          # runs init_db() -> creates tables
    import core.proactive_models  # noqa: F401
    from services.homeassistant.service import HomeAssistantConfigStore
except ModuleNotFoundError as ex:
    print("SKIP", ex); sys.exit(0)

store = HomeAssistantConfigStore()

# create + read (token never leaked by default; token_set flag instead)
store.set("alice", base_url="http://ha.local:8123/", token="secret-token-123",
          enabled=True, allowlist=["light", "alarm_control_panel.home"])
cfg = store.get("alice")
assert cfg["enabled"] is True
assert cfg["base_url"] == "http://ha.local:8123"   # trailing slash stripped
assert cfg["token_set"] is True
assert "token" not in cfg
assert cfg["allowlist"] == ["light", "alarm_control_panel.home"]

# encrypted token round-trips when explicitly requested
assert store.get("alice", include_token=True)["token"] == "secret-token-123"

# owner isolation: bob has no config
assert store.get("bob") is None

# update merges (one row per owner)
store.set("alice", enabled=False)
cfg2 = store.get("alice")
assert cfg2["enabled"] is False and cfg2["token_set"] is True  # token preserved
print("OK")
"""


def test_ha_config_owner_scope_and_token():
    p = subprocess.run([sys.executable, "-c", _SCRIPT], cwd=_ROOT,
                       capture_output=True, text=True)
    if "SKIP" in p.stdout:
        pytest.skip("deps not installed: " + p.stdout.strip())
    assert p.returncode == 0, (p.stdout + p.stderr)
    assert "OK" in p.stdout, (p.stdout + p.stderr)
