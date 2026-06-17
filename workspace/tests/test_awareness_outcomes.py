"""Awareness outcome tuning: dismissals auto-pause a noisy trigger (Phase 5).

Isolated subprocess + temp DATABASE_URL, like the other DB-backed tests.
Skips when app deps are absent.
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
    import core.database          # runs init_db()
    import core.proactive_models  # noqa: F401
    from services.awareness.service import AwarenessService
except ModuleNotFoundError as ex:
    print("SKIP", ex); sys.exit(0)

svc = AwarenessService()

# A trigger that gets persistently dismissed should auto-pause.
t = svc.create_trigger("alice", "Chatty trigger")
assert t["enabled"] is True
for _ in range(6):
    n = svc._record_notification("alice", t["id"], "ping", "body", "ntfy", "sent")
    assert svc.record_outcome("alice", n["id"], "dismissed") is True
paused = next(x for x in svc.list_triggers("alice") if x["id"] == t["id"])
assert paused["enabled"] is False, "noisy trigger should auto-pause"

# A consistently-useful trigger stays enabled.
t2 = svc.create_trigger("alice", "Helpful trigger")
for _ in range(6):
    n = svc._record_notification("alice", t2["id"], "ping", "body", "ntfy", "sent")
    svc.record_outcome("alice", n["id"], "useful")
helpful = next(x for x in svc.list_triggers("alice") if x["id"] == t2["id"])
assert helpful["enabled"] is True

# outcome on another owner's notification is rejected (isolation)
n3 = svc._record_notification("alice", t2["id"], "ping", "body", "ntfy", "sent")
assert svc.record_outcome("bob", n3["id"], "useful") is False
print("OK")
"""


def test_outcome_tuning_auto_pause():
    p = subprocess.run([sys.executable, "-c", _SCRIPT], cwd=_ROOT,
                       capture_output=True, text=True)
    if "SKIP" in p.stdout:
        pytest.skip("deps not installed: " + p.stdout.strip())
    assert p.returncode == 0, (p.stdout + p.stderr)
    assert "OK" in p.stdout, (p.stdout + p.stderr)
