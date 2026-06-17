"""Phase 0: the new proactive privileges exist and are default-off.

Runs in an isolated subprocess so the real ``core.auth`` is imported cleanly —
the shared pytest session has sibling tests that replace ``core.auth`` /
``core.database`` in ``sys.modules`` with MagicMock stubs, which would
otherwise leak in here. Skips when app deps aren't installed.
"""

import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SCRIPT = r"""
import os, sys, tempfile
# Importing core.auth pulls core/__init__ -> session_manager -> database, which
# runs init_db() at import; point it at a throwaway DB so it doesn't need ./data.
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mkstemp(suffix=".db")[1]
try:
    from core.auth import DEFAULT_PRIVILEGES, ADMIN_PRIVILEGES
except ModuleNotFoundError as ex:
    print("SKIP", ex); sys.exit(0)
assert DEFAULT_PRIVILEGES.get("can_use_awareness") is False
assert DEFAULT_PRIVILEGES.get("can_control_home") is False
assert ADMIN_PRIVILEGES.get("can_use_awareness") is True
assert ADMIN_PRIVILEGES.get("can_control_home") is True
print("OK")
"""


def test_new_privileges_present_and_default_off():
    p = subprocess.run([sys.executable, "-c", _SCRIPT], cwd=_ROOT,
                       capture_output=True, text=True)
    if "SKIP" in p.stdout:
        pytest.skip("app deps not installed: " + p.stdout.strip())
    assert p.returncode == 0, (p.stdout + p.stderr)
    assert "OK" in p.stdout, (p.stdout + p.stderr)
