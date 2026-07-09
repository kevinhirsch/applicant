"""DISC-2 — the resume ledger must survive a process restart, not just a tick.

``ResumeLedger`` was made process-lived (tick-safe: one instance injected into every
per-tick ``AgentLoop``), but a genuine process restart (an ``update.sh`` deploy, an
OOM kill, a crash) still wiped it. The backoff window (``last_resume``) reset to empty,
so on the next boot every parked application looked immediately "due" and the loop
could re-attempt everything at once — a retry storm against the ATS/sandbox.

The fix gives the ledger a restart-durable snapshot store (``ConfigLedgerStore`` over
the existing ``app_config`` table — no new table/migration): it reloads at boot
(``restore()``) and re-persists after every mutation (``persist()``). These tests pin:

  * the snapshot/restore round-trip across a *simulated restart* (a NEW ledger object
    backed by the SAME durable store), including datetimes, the failure streak, and
    the give-up set;
  * ``_load_snapshot`` mutates the state containers IN PLACE (never rebinds them) so
    the direct references ``AgentLoop.__init__`` captures stay valid;
  * every ``AgentLoop`` mutation site (``_mark_resumed``, ``_record_resume_failure``,
    ``retry_given_up``) persists, so a restart honors the backoff / give-up (no storm)
    and an operator retry clears the give-up durably;
  * ``ConfigLedgerStore`` round-trips over both the in-memory lane and a real SQLite
    ``app_config`` row (the DB-backed durability path, proving no migration is needed);
  * with no persister the ledger is byte-identical to before (a pure in-memory object).
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.adapters.storage.ledger_persistence import ConfigLedgerStore
from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine, make_session_factory
from applicant.application.services.agent_loop import (
    _RESUME_FAILURE_CAP,
    AgentLoop,
    ResumeLedger,
)
from applicant.application.services.agent_run_service import AgentRunService
from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, new_id
from applicant.core.state_machine import ApplicationState


class _FakePersister:
    """A ``load()``/``save(dict)`` snapshot store backed by one shared dict cell.

    A NEW ``ResumeLedger`` pointed at the SAME ``_FakePersister`` instance simulates a
    restart: the process-lived in-memory ledger is gone, but the durable snapshot the
    persister holds survives — exactly what a real ``ConfigLedgerStore`` (over
    ``app_config``) gives across an actual restart.
    """

    def __init__(self) -> None:
        self.saved: dict[str, Any] | None = None
        self.save_calls = 0

    def load(self) -> dict[str, Any] | None:
        # Return a copy so callers can't mutate the "persisted" blob by reference.
        return dict(self.saved) if self.saved is not None else None

    def save(self, value: dict[str, Any]) -> None:
        self.save_calls += 1
        self.saved = dict(value)


# --- ledger snapshot / restore round-trip -----------------------------------------


def test_snapshot_restore_round_trip_across_a_simulated_restart():
    store = _FakePersister()
    led = ResumeLedger(persister=store)
    t = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)

    led.last_resume["app-1"] = t
    led.failures["app-1"] = 3
    led.giveup.add("app-2")
    led.persist()

    # Simulated restart: a brand-new ledger, same durable store, reload at boot.
    revived = ResumeLedger(persister=store)
    assert revived.last_resume == {}  # nothing yet (fresh object)
    revived.restore()

    assert revived.last_resume == {"app-1": t}
    assert revived.last_resume["app-1"].tzinfo is not None  # tz survived the isoformat
    assert revived.failures == {"app-1": 3}
    assert revived.giveup == {"app-2"}


def test_restore_is_a_noop_when_nothing_was_ever_persisted():
    store = _FakePersister()
    led = ResumeLedger(persister=store)
    led.restore()  # store.load() is None
    assert led.last_resume == {}
    assert led.failures == {}
    assert led.giveup == set()


def test_load_snapshot_mutates_containers_in_place_for_agentloop_aliasing():
    # AgentLoop.__init__ captures direct references to these dicts/sets; restore()
    # must update them in place, never rebind, or those aliases go stale.
    led = ResumeLedger()
    last_resume_ref = led.last_resume
    failures_ref = led.failures
    giveup_ref = led.giveup

    led._load_snapshot(
        {
            "last_resume": {"a": "2026-06-16T12:00:00+00:00"},
            "failures": {"a": 2},
            "giveup": ["b"],
        }
    )

    assert led.last_resume is last_resume_ref
    assert led.failures is failures_ref
    assert led.giveup is giveup_ref
    assert led.last_resume["a"] == datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


def test_no_persister_is_a_pure_in_memory_noop():
    led = ResumeLedger()  # no persister
    led.last_resume["x"] = datetime.now(UTC)
    led.persist()  # must not raise
    led.restore()  # must not raise, must not clear the in-memory state
    assert "x" in led.last_resume


def test_malformed_snapshot_entries_are_skipped_not_fatal():
    led = ResumeLedger()
    led._load_snapshot(
        {
            "last_resume": {"good": "2026-06-16T12:00:00+00:00", "bad": "not-a-date"},
            "failures": {"good": 5, "bad": "NaN"},
            "giveup": ["z"],
        }
    )
    assert "good" in led.last_resume and "bad" not in led.last_resume
    assert led.failures == {"good": 5}
    assert led.giveup == {"z"}


# --- ConfigLedgerStore (the real adapter) -----------------------------------------


def test_config_ledger_store_in_memory_round_trip():
    mem = InMemoryAppConfigStore()
    store = ConfigLedgerStore("agent.resume_ledger", memory_store=mem)
    assert store.load() is None
    store.save({"failures": {"a": 1}, "giveup": ["b"], "last_resume": {}})
    assert store.load() == {"failures": {"a": 1}, "giveup": ["b"], "last_resume": {}}


def test_config_ledger_store_round_trips_over_a_real_sqlite_app_config_row():
    # The DB-backed durability path: a fresh session per op (scheduler-thread-safe),
    # persisted to the app_config table that already exists — proving no migration.
    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    try:
        store = ConfigLedgerStore("agent.resume_ledger", session_factory=session_factory)
        assert store.load() is None
        snap = {
            "last_resume": {"app-1": "2026-06-16T12:00:00+00:00"},
            "failures": {"app-1": 4},
            "giveup": ["app-2"],
        }
        store.save(snap)

        # A brand-new store over the SAME DB (simulated restart) reads it back.
        revived = ConfigLedgerStore("agent.resume_ledger", session_factory=session_factory)
        assert revived.load() == snap
    finally:
        engine.dispose()


# --- AgentLoop mutation sites persist ---------------------------------------------


def _storage_with_app(status: ApplicationState) -> tuple[InMemoryStorage, CampaignId, ApplicationId]:
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=None,
            status=status,
            role_name="Senior Engineer",
        )
    )
    storage.commit()
    return storage, cid, aid


def _loop(storage: InMemoryStorage, ledger: ResumeLedger) -> AgentLoop:
    return AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        resume_ledger=ledger,
    )


def test_mark_resumed_persists_so_a_restart_honors_the_backoff_no_storm():
    storage, _cid, aid = _storage_with_app(ApplicationState.BLOCKED_MISSING_ATTR)
    store = _FakePersister()
    loop = _loop(storage, ResumeLedger(persister=store))

    now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    loop._mark_resumed(aid, now)
    assert store.save_calls >= 1  # the backoff timestamp was persisted

    # Simulated restart: a fresh ledger + fresh loop, same durable store.
    revived = ResumeLedger(persister=store)
    revived.restore()
    revived_loop = _loop(storage, revived)

    # Still inside the 300s window -> NOT due -> the loop won't re-drive it. Before
    # DISC-2 the backoff was empty on boot and _resume_due returned True (the storm).
    assert revived_loop._resume_due(aid, now + timedelta(seconds=90)) is False
    # And once the window elapses it becomes due again (backoff, not a permanent block).
    assert revived_loop._resume_due(aid, now + timedelta(seconds=600)) is True


def test_record_resume_failure_persists_the_giveup_across_a_restart():
    storage, _cid, aid = _storage_with_app(ApplicationState.BLOCKED_QUESTION)
    store = _FakePersister()
    loop = _loop(storage, ResumeLedger(persister=store))

    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(aid)

    # Simulated restart: the give-up cap must NOT reset (else the poison app gets a
    # fresh N tries every boot and churns the sandbox forever).
    revived = ResumeLedger(persister=store)
    revived.restore()
    assert str(aid) in revived.giveup
    assert revived.failures[str(aid)] >= _RESUME_FAILURE_CAP


def test_retry_given_up_clears_the_giveup_durably():
    storage, _cid, aid = _storage_with_app(ApplicationState.BLOCKED_QUESTION)
    store = _FakePersister()
    ledger = ResumeLedger(persister=store)
    loop = _loop(storage, ledger)

    for _ in range(_RESUME_FAILURE_CAP):
        loop._record_resume_failure(aid)
    assert str(aid) in ledger.giveup

    assert loop.retry_given_up(str(aid)) is True

    # A restart after the operator's retry must NOT resurrect the stale give-up.
    revived = ResumeLedger(persister=store)
    revived.restore()
    assert str(aid) not in revived.giveup
    assert str(aid) not in revived.failures


# --- end-to-end container wiring (real DB, simulated restart) ----------------------


def test_container_resume_ledger_persists_and_restores_across_a_rebuild():
    from applicant.app.config import Settings
    from applicant.app.container import build_container

    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    settings = Settings(DATABASE_URL=f"sqlite:///{db}")

    c1 = build_container(settings)
    # The container wired a durable persister onto the process-lived ledger the shared
    # AgentLoop (and every per-tick rebuild) carries.
    led1 = c1.agent_loop._resume_ledger
    assert led1.persister is not None

    t = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    led1.last_resume["app-1"] = t
    led1.giveup.add("app-2")
    led1.persist()

    # Rebuilding the container against the SAME DB simulates a process restart: its
    # freshly-built ledger must reload the snapshot (restore() runs during build).
    c2 = build_container(settings)
    led2 = c2.agent_loop._resume_ledger
    assert led2.last_resume == {"app-1": t}
    assert led2.giveup == {"app-2"}
