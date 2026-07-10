"""Skyvern-parity #2 — the discovery/prefill flywheel routine store must survive a
process restart, not just a tick.

``InMemoryRoutineStore`` (#306) was made process-lived (tick-safe: one instance injected
into every per-tick ``PrefillService``), but a genuine process restart (an ``update.sh``
deploy, an OOM kill, a crash) still wiped it — every AWM-induced per-ATS routine and all
its ACE success/failure weights were lost, so #306's "coverage grows itself" did not
survive a redeploy: the loop re-derived every plan cold-start again.

The fix gives the store an optional restart-durable snapshot store (``ConfigLedgerStore``
over the existing ``app_config`` table — no new table/migration): it reloads at boot
(``restore()``) and re-persists after every mutation (``persist()``). These tests pin:

  * the snapshot/restore round-trip across a *simulated restart* (a NEW store object
    backed by the SAME durable store), including the routine steps and the ACE weights;
  * every mutation site (``induce``, ``record_success``, ``record_failure`` incl. prune)
    persists, so a restart honors the learned coverage;
  * the durable snapshot is DATA-ONLY — op kinds + attribute/document ids + locators,
    never a literal user value (the Routine graph has no value field to leak);
  * a persist FAILURE never breaks a mutation (the tick is never broken);
  * with no persister the store is byte-identical to before (a pure in-memory no-op);
  * ``ConfigLedgerStore`` round-trips over a real SQLite ``app_config`` row (the DB-backed
    durability path, proving no migration is needed);
  * end-to-end container wiring: the container wires a durable persister and reloads it
    across a rebuild (a simulated restart) against a real DB.
"""

from __future__ import annotations

import tempfile
from typing import Any

from applicant.adapters.routine import InMemoryRoutineStore
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.ledger_persistence import ConfigLedgerStore
from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine, make_session_factory
from applicant.ports.driven.routine_store import DEFAULT_PRUNE_THRESHOLD, RoutineStep


class _FakePersister:
    """A ``load()``/``save(dict)`` snapshot store backed by one shared dict cell.

    A NEW ``InMemoryRoutineStore`` pointed at the SAME ``_FakePersister`` simulates a
    restart: the process-lived store is gone, but the durable snapshot survives — exactly
    what a real ``ConfigLedgerStore`` (over ``app_config``) gives across an actual restart.
    """

    def __init__(self) -> None:
        self.saved: dict[str, Any] | None = None
        self.save_calls = 0

    def load(self) -> dict[str, Any] | None:
        return dict(self.saved) if self.saved is not None else None

    def save(self, value: dict[str, Any]) -> None:
        self.save_calls += 1
        self.saved = dict(value)


_STEPS = (
    RoutineStep(kind="fill", ref="input#firstName", attribute_id="attr-first", role="textbox", name="First name"),
    RoutineStep(kind="upload", ref="input#resume", document_id="doc-base", role="button", name="Attach résumé"),
    RoutineStep(kind="select", ref="select#source", attribute_id="attr-source", role="combobox", name="How did you hear"),
)


# --- snapshot / restore round-trip -------------------------------------------------


def test_snapshot_restore_round_trip_across_a_simulated_restart():
    store = _FakePersister()
    s = InMemoryRoutineStore(persister=store)

    s.induce("workday.myworkdayjobs.com", _STEPS)
    s.record_success("workday.myworkdayjobs.com")  # ACE up-weight
    s.record_failure("workday.myworkdayjobs.com")  # ACE down-weight

    # Simulated restart: a brand-new store, same durable snapshot, reload at boot.
    revived = InMemoryRoutineStore(persister=store)
    assert revived.all_domains() == ()  # nothing yet (fresh object)
    revived.restore()

    r = revived.get("workday.myworkdayjobs.com")
    assert r is not None
    assert r.domain == "workday.myworkdayjobs.com"
    assert r.steps == _STEPS  # every structural step survived the round-trip
    # ACE weights survived: induce=1 success, record_success=+1, record_failure=+1 fail.
    assert r.successes == 2
    assert r.failures == 1
    assert r.score == 1
    assert r.source == "induced"


def test_restore_is_a_noop_when_nothing_was_ever_persisted():
    store = _FakePersister()
    s = InMemoryRoutineStore(persister=store)
    s.restore()  # store.load() is None
    assert s.all_domains() == ()


def test_every_mutation_site_persists():
    store = _FakePersister()
    s = InMemoryRoutineStore(persister=store)

    s.induce("greenhouse.io", _STEPS)
    assert store.save_calls == 1
    s.record_success("greenhouse.io")
    assert store.save_calls == 2
    s.record_failure("greenhouse.io")
    assert store.save_calls == 3


def test_prune_on_net_failure_is_persisted_so_the_stale_routine_stays_gone():
    store = _FakePersister()
    s = InMemoryRoutineStore(persister=store)

    # A single-success routine, then enough net failures to cross the prune threshold.
    s.induce("flaky.example.com", _STEPS)  # successes=1
    for _ in range(DEFAULT_PRUNE_THRESHOLD + 1):
        s.record_failure("flaky.example.com")
    assert s.get("flaky.example.com") is None  # pruned live

    # A restart must NOT resurrect the pruned routine (its removal was persisted).
    revived = InMemoryRoutineStore(persister=store)
    revived.restore()
    assert revived.get("flaky.example.com") is None


def test_the_persisted_snapshot_is_data_only_never_a_literal_value():
    # NFR-TRUTH-1: the durable blob carries ONLY op kinds, ids and structural locators.
    # A user's actual answer ("Jane", an email, a phone) must never appear in it.
    store = _FakePersister()
    s = InMemoryRoutineStore(persister=store)
    s.induce("lever.co", _STEPS)

    snap = store.saved
    assert snap is not None
    routine = snap["routines"]["lever.co"]
    # Field set is exactly the structural graph — no "value"/"answer"/"text" field exists.
    assert set(routine) == {"domain", "steps", "successes", "failures", "source"}
    for step in routine["steps"]:
        assert set(step) == {"kind", "ref", "attribute_id", "document_id", "role", "name"}
        assert "value" not in step and "answer" not in step


def test_a_persist_failure_never_breaks_a_mutation():
    class _BoomPersister:
        def load(self) -> dict[str, Any] | None:
            return None

        def save(self, value: dict[str, Any]) -> None:
            raise RuntimeError("storage blip")

    s = InMemoryRoutineStore(persister=_BoomPersister())
    # None of these must raise even though every persist attempt explodes.
    s.induce("boom.example.com", _STEPS)
    s.record_success("boom.example.com")
    s.record_failure("boom.example.com")
    # The in-memory state is still correct for the life of the process.
    assert s.get("boom.example.com") is not None


def test_no_persister_is_a_pure_in_memory_noop():
    s = InMemoryRoutineStore()  # no persister
    s.induce("nodb.example.com", _STEPS)
    s.persist()  # must not raise
    s.restore()  # must not raise, must not clear the in-memory state
    assert s.get("nodb.example.com") is not None


def test_malformed_snapshot_entries_are_skipped_not_fatal():
    s = InMemoryRoutineStore()
    s._load_snapshot(
        {
            "routines": {
                "good.example.com": {
                    "domain": "good.example.com",
                    "steps": [{"kind": "fill", "ref": "a", "attribute_id": "x"}],
                    "successes": 4,
                    "failures": 1,
                    "source": "induced",
                },
                "bad.example.com": "not-a-dict",
                "": {"steps": []},  # empty domain key is skipped
            }
        }
    )
    assert s.get("good.example.com") is not None
    assert s.get("good.example.com").successes == 4
    assert s.get("bad.example.com") is None
    assert s.all_domains() == ("good.example.com",)


# --- ConfigLedgerStore (the real adapter) ------------------------------------------


def test_config_ledger_store_in_memory_round_trip():
    mem = InMemoryAppConfigStore()
    store = ConfigLedgerStore("agent.routine_store", memory_store=mem)
    s = InMemoryRoutineStore(persister=store)
    s.induce("workday.myworkdayjobs.com", _STEPS)

    revived = InMemoryRoutineStore(persister=ConfigLedgerStore("agent.routine_store", memory_store=mem))
    revived.restore()
    assert revived.get("workday.myworkdayjobs.com") is not None
    assert revived.get("workday.myworkdayjobs.com").steps == _STEPS


def test_config_ledger_store_round_trips_over_a_real_sqlite_app_config_row():
    # The DB-backed durability path: a fresh session per op (scheduler-thread-safe),
    # persisted to the app_config table that already exists — proving no migration.
    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    try:
        store = ConfigLedgerStore("agent.routine_store", session_factory=session_factory)
        s = InMemoryRoutineStore(persister=store)
        s.induce("greenhouse.io", _STEPS)
        s.record_success("greenhouse.io")

        # A brand-new store over the SAME DB (simulated restart) reads it back.
        revived = InMemoryRoutineStore(
            persister=ConfigLedgerStore("agent.routine_store", session_factory=session_factory)
        )
        revived.restore()
        r = revived.get("greenhouse.io")
        assert r is not None
        assert r.steps == _STEPS
        assert r.successes == 2  # induce + record_success survived the DB round-trip
    finally:
        engine.dispose()


# --- end-to-end container wiring (real DB, simulated restart) -----------------------


def test_container_routine_store_persists_and_restores_across_a_rebuild():
    from applicant.app.config import Settings
    from applicant.app.container import build_container

    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    settings = Settings(DATABASE_URL=f"sqlite:///{db}")

    c1 = build_container(settings)
    store1 = c1.prefill_service._routine_store
    assert store1._persister is not None

    store1.induce("workday.myworkdayjobs.com", _STEPS)

    # Rebuilding the container against the SAME DB simulates a process restart: its
    # freshly-built store must reload the snapshot (restore() runs during build).
    c2 = build_container(settings)
    store2 = c2.prefill_service._routine_store
    r = store2.get("workday.myworkdayjobs.com")
    assert r is not None
    assert r.steps == _STEPS
