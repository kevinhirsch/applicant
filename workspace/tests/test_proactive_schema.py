"""Phase 0: proactive-feature tables create cleanly and are owner-scopable.

Runs in an isolated subprocess (fresh interpreter) so the *real* SQLAlchemy
declarative models are built — the shared pytest session has sibling tests that
stub ``core.database`` in ``sys.modules``, which would corrupt ``Base`` here.
``DATABASE_URL`` is pointed at a throwaway temp file because importing
``core.database`` runs ``init_db()`` at import time. Skips when deps are absent.
"""

import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SCRIPT = r"""
import os, sys, uuid, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mkstemp(suffix=".db")[1]
try:
    from core.database import SessionLocal   # importing runs init_db() -> creates tables
    import core.proactive_models as pm
except ModuleNotFoundError as ex:
    print("SKIP", ex); sys.exit(0)

s = SessionLocal()
e = pm.Entity(id=str(uuid.uuid4()), owner="alice", type="person", name="Ryne")
s.add(e); s.flush()
s.add(pm.EntityFact(id=str(uuid.uuid4()), owner="alice", entity_id=e.id,
                    text="Ryne is Alice's boyfriend", category="relationship"))
s.commit()

f = s.query(pm.EntityFact).filter(pm.EntityFact.entity_id == e.id).one()
assert f.alpha == 1.0 and f.beta == 1.0 and f.confidence == 0.5 and f.uses == 0

# owner isolation
s.add(pm.Entity(id=str(uuid.uuid4()), owner="bob", type="person", name="Sam"))
s.commit()
assert [r.name for r in s.query(pm.Entity).filter(pm.Entity.owner == "alice").all()] == ["Ryne"]
assert [r.name for r in s.query(pm.Entity).filter(pm.Entity.owner == "bob").all()] == ["Sam"]

# awareness trigger defaults
t = pm.AwarenessTrigger(id=str(uuid.uuid4()), owner="alice", name="Pre-event nudge")
s.add(t); s.commit()
gt = s.query(pm.AwarenessTrigger).filter(pm.AwarenessTrigger.id == t.id).one()
assert gt.channel == "ntfy" and gt.enabled is True and gt.risk_tier == "low" and gt.cooldown_seconds == 0
print("OK")
"""


def test_schema_and_owner_scope():
    p = subprocess.run([sys.executable, "-c", _SCRIPT], cwd=_ROOT,
                       capture_output=True, text=True)
    if "SKIP" in p.stdout:
        pytest.skip("deps not installed: " + p.stdout.strip())
    assert p.returncode == 0, (p.stdout + p.stderr)
    assert "OK" in p.stdout, (p.stdout + p.stderr)
