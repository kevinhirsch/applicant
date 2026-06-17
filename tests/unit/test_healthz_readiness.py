"""Engine /healthz is a REAL readiness probe (not a static 200).

It must run a trivial ``SELECT 1`` against the configured DB and verify the
credential-vault key directory is usable; a failure of either returns HTTP 503
``{"status":"degraded"}`` so the prod healthcheck + the install/update heartbeat
hold until the engine can actually serve. The default in-memory boot path (no real
DB, ``engine is None``) still reports 200 ``ok``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from applicant.app.main import create_app


def test_healthz_ok_on_in_memory_boot():
    # The hermetic boot path has no Postgres (engine is None); /healthz still goes
    # green because there is no DB to probe and the key dir's parent is writable.
    app = create_app()
    with TestClient(app) as c:
        res = c.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "checks" in body
    # The DB check is reported as the in-memory sentinel on the no-DB path.
    assert body["checks"]["database"] == "in-memory"


def test_healthz_degraded_when_db_select_fails():
    # When a real engine is wired but the DB is unreachable, the SELECT 1 raises and
    # /healthz must return 503 degraded — never a false-green 200.
    app = create_app()

    class _BoomConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *_a, **_k):
            raise RuntimeError("db down")

    class _BoomEngine:
        def connect(self):
            return _BoomConn()

        def dispose(self):  # called by the lifespan on shutdown
            pass

    app.state.container.engine = _BoomEngine()

    with TestClient(app) as c:
        res = c.get("/healthz")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"].startswith("error")


def test_healthz_ok_when_db_select_succeeds():
    # A reachable DB (SELECT 1 returns) keeps /healthz green.
    app = create_app()

    class _OkConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *_a, **_k):
            return None

    class _OkEngine:
        def connect(self):
            return _OkConn()

        def dispose(self):  # called by the lifespan on shutdown
            pass

    app.state.container.engine = _OkEngine()

    with TestClient(app) as c:
        res = c.get("/healthz")
    assert res.status_code == 200
    assert res.json()["checks"]["database"] == "ok"
