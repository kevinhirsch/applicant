"""Awareness trigger CRUD + owner isolation (Phase 2).

Isolated subprocess + temp DATABASE_URL, like the other DB-backed tests, so the
real service/models run immune to the shared session's stubbing. Skips when app
deps are absent.
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
    import core.database          # importing runs init_db() -> creates tables
    import core.proactive_models  # noqa: F401
    from services.awareness.service import AwarenessService
except ModuleNotFoundError as ex:
    print("SKIP", ex); sys.exit(0)

svc = AwarenessService()

t = svc.create_trigger("alice", "Pre-event nudge",
                       condition={"field": "next_event_minutes", "op": "lte", "value": 30},
                       cooldown_seconds=600)
assert t["name"] == "Pre-event nudge" and t["enabled"] is True and t["channel"] == "ntfy"

# update + toggle
u = svc.update_trigger("alice", t["id"], enabled=False, name="renamed")
assert u["enabled"] is False and u["name"] == "renamed"

# owner isolation
svc.create_trigger("bob", "Bob trigger")
assert [x["name"] for x in svc.list_triggers("alice")] == ["renamed"]
assert [x["name"] for x in svc.list_triggers("bob")] == ["Bob trigger"]
assert svc.update_trigger("bob", t["id"], enabled=True) is None     # can't touch alice's
assert svc.delete_trigger("bob", t["id"]) is False

# enabled_only filter
svc.create_trigger("alice", "active one")
names = sorted(x["name"] for x in svc.list_triggers("alice", enabled_only=True))
assert names == ["active one"]   # the renamed one was disabled above

# notification record + outcome
n = svc._record_notification("alice", t["id"], "Title", "Body", "ntfy", "sent")
assert svc.record_outcome("alice", n["id"], "useful") is True
assert svc.record_outcome("bob", n["id"], "useful") is False      # isolation
fed = svc.list_notifications("alice")
assert fed and fed[0]["outcome"] == "useful"

assert svc.delete_trigger("alice", t["id"]) is True
print("OK")
"""


def test_trigger_crud_and_isolation():
    p = subprocess.run([sys.executable, "-c", _SCRIPT], cwd=_ROOT,
                       capture_output=True, text=True)
    if "SKIP" in p.stdout:
        pytest.skip("deps not installed: " + p.stdout.strip())
    assert p.returncode == 0, (p.stdout + p.stderr)
    assert "OK" in p.stdout, (p.stdout + p.stderr)
