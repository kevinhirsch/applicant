"""Regression: the LLM gate recovers from a transient Postgres blip WITHOUT a
restart (K2).

The container-level app-config store holds the single *boot* Session (built once
at startup, lives for the whole process — unlike route-handler storage, which is
per-request). After a transient Postgres blip that aborts the boot Session's
transaction, every subsequent read raises
``PendingRollbackError: can't reconnect until invalid transaction is rolled back``.
Because ~25 routers gate on ``require_llm_configured`` →
``container.setup_service.is_setup_gate_open()`` → the app-config store, all of
them wedge at HTTP 500 until the engine is restarted.

These tests prove the fix at two altitudes:
  (1) the store itself rolls back + retries once and returns the persisted value
      after a blip (the unit of recovery);
  (2) the WIRED gate — a ``require_llm_configured``-protected route over a booted
      app whose ``setup_service`` reads through a poisoned boot Session — returns
      its normal response (200/409, not a stuck 500) on the request AFTER the blip,
      WITHOUT reconstructing the container.

On origin/main both fail: the store re-raises ``PendingRollbackError`` and the
gate dependency turns it into a 500 that never clears.
"""

from __future__ import annotations

import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import PendingRollbackError

from applicant.adapters.storage.app_config_store import SqlAlchemyAppConfigStore
from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine, make_session_factory
from applicant.app.main import create_app


class _PoisonedSession:
    """A real SQLAlchemy Session that simulates the post-blip stuck state.

    Once :meth:`poison` is called, the next ``execute`` raises
    ``PendingRollbackError`` — exactly what Postgres surfaces when a prior
    statement aborted the transaction and nothing rolled it back — until
    ``rollback()`` is called, which clears the poison and rolls the real session
    back so a fresh transaction can begin. This faithfully reproduces both the
    bug (no rollback ⇒ permanently stuck) and the recovery (rollback ⇒ next
    statement succeeds).
    """

    def __init__(self, real) -> None:
        self._real = real
        self._poisoned = False

    def poison(self) -> None:
        self._poisoned = True

    def execute(self, *args, **kwargs):
        if self._poisoned:
            raise PendingRollbackError(
                "Can't reconnect until invalid transaction is rolled back",
                None,
                None,
            )
        return self._real.execute(*args, **kwargs)

    def rollback(self):
        self._poisoned = False
        return self._real.rollback()

    def commit(self):
        return self._real.commit()

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def poisoned_store():
    """A SqlAlchemyAppConfigStore over a real (sqlite) session we can poison."""
    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    real = make_session_factory(engine)()
    session = _PoisonedSession(real)
    store = SqlAlchemyAppConfigStore(session)
    yield store, session
    real.close()
    engine.dispose()


# --- (1) the store recovers on the next read after a blip ----------------------
def test_get_recovers_after_pending_rollback(poisoned_store):
    store, session = poisoned_store
    store.set("llm.tier_ladder", {"tiers": [{"model": "m"}]})
    assert store.get("llm.tier_ladder") == {"tiers": [{"model": "m"}]}

    session.poison()  # transient blip leaves the boot session's txn aborted

    # On origin/main this re-raises PendingRollbackError (stuck 500). With the fix
    # the store rolls back + retries once and returns the persisted value.
    assert store.get("llm.tier_ladder") == {"tiers": [{"model": "m"}]}


def test_set_recovers_after_pending_rollback(poisoned_store):
    store, session = poisoned_store
    store.set("llm.tier_ladder", {"tiers": [{"model": "m"}]})

    session.poison()

    # The write must also recover (the upsert + commit run on the same boot
    # session) and the new value must persist.
    store.set("llm.tier_ladder", {"tiers": [{"model": "m2"}]})
    assert store.get("llm.tier_ladder") == {"tiers": [{"model": "m2"}]}


# --- (2) the WIRED gate recovers without reconstructing the container ----------
@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _wire_sql_store_into_gate(container):
    """Point the container's setup_service at a poisoned SqlAlchemy config store.

    Returns the (store, poisoned_session) so the test can trigger the blip. This
    swaps ONLY the gate's backing store — the container is otherwise untouched and
    is NOT rebuilt, which is the whole point: recovery must happen in-process.
    """
    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    real = make_session_factory(engine)()
    session = _PoisonedSession(real)
    store = SqlAlchemyAppConfigStore(session)
    # SetupService is not frozen; the gate reads through this store.
    container.setup_service._store = store
    return store, session


def test_llm_gate_recovers_without_restart(client):
    container = client.app.state.container
    store, session = _wire_sql_store_into_gate(container)

    # Configure the LLM through the real setup endpoint so the tier ladder is
    # persisted in the (now SQLAlchemy-backed) gate store and the gate is OPEN.
    r = client.post(
        "/api/setup/llm",
        json={
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3.1",
        },
    )
    assert r.status_code == 204

    # Sanity: a require_llm_configured-gated route is reachable (not 409, not 500)
    # while the gate is open and healthy.
    before = client.post("/api/compare/applications", json=[])
    assert before.status_code == 200

    # Transient Postgres blip aborts the boot session's transaction.
    session.poison()

    # THE REGRESSION: the very next gated request must recover in-process. On
    # origin/main the gate read raises PendingRollbackError -> HTTP 500 that stays
    # stuck until restart. With the fix the store rolls back + retries and the
    # gate returns its normal response (200 here; 409 only if setup were missing).
    after = client.post("/api/compare/applications", json=[])
    assert after.status_code != 500, (
        "gate stuck at 500 after a transient DB blip — must recover without a restart"
    )
    assert after.status_code == 200
