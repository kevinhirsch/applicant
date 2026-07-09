"""Durable JSON snapshots for process-lived agent-loop ledgers (DISC-2).

The 24/7 scheduler keeps a handful of process-lived ledgers (see
``application/services/agent_loop.py``) that must survive **across ticks** — the
resume backoff window, the resume-failure streak, and the give-up set. Those are
already tick-durable (one instance injected into every per-tick loop), but a real
process restart (an ``update.sh`` deploy, an OOM kill, a crash) wiped them: the
resume backoff reset to empty, so every parked application looked immediately
"due" again and the loop could re-attempt everything at once — a retry storm
against the ATS/sandbox (DISC-2).

This adapter gives such a ledger a small, restart-durable backing store built on
the SAME ``app_config`` key/value table the OOBE ladder/wizard state already
persists to — so no new table or migration is needed. The snapshot is a plain
JSON-able dict written under one key.

**Scheduler-thread safety (CONC-2).** The 24/7 tick runs on a worker thread and
must never touch the process-lived boot ``Session`` (concurrent use of one
non-thread-safe Session raises "concurrent operations are not permitted"). So on
the real-DB lane this store opens a FRESH session per read/write via the
``session_factory`` — exactly the isolation ``AuditLogService`` uses for its own
per-event writes — and closes it immediately. When no database is configured
(hermetic boot / tests) it falls back to a shared in-memory config store; no
cross-restart durability is possible there anyway (nothing survives the restart),
so the in-memory round-trip is purely for in-process consistency.
"""

from __future__ import annotations

import logging
from typing import Any

from applicant.adapters.storage.app_config_store import SqlAlchemyAppConfigStore

log = logging.getLogger(__name__)


class ConfigLedgerStore:
    """Restart-durable ``load()``/``save(dict)`` snapshot keyed in ``app_config``.

    Duck-typed to what a ledger needs (``load() -> dict | None`` and
    ``save(dict) -> None``) so the ``application``-layer ledger can depend on it
    without importing an adapter (hexagonal layering: the persister is injected
    by the container, never imported by ``agent_loop``).
    """

    def __init__(
        self,
        key: str,
        *,
        session_factory: Any = None,
        memory_store: Any = None,
    ) -> None:
        #: app_config key this ledger's snapshot lives under.
        self._key = key
        #: Real-DB lane: open a fresh Session per op (scheduler-thread-safe).
        self._session_factory = session_factory
        #: No-DB lane: a shared in-memory AppConfigStore (in-process only).
        self._memory = memory_store

    def load(self) -> dict[str, Any] | None:
        """Return the persisted snapshot dict, or ``None`` if none is stored.

        Never raises into the caller — a read blip degrades to "no snapshot"
        (an empty ledger), which is exactly the pre-DISC-2 behaviour, so boot is
        never blocked by a transient storage hiccup.
        """
        try:
            if self._session_factory is not None:
                sess = self._session_factory()
                try:
                    return SqlAlchemyAppConfigStore(sess).get(self._key)
                finally:
                    sess.close()
            if self._memory is not None:
                return self._memory.get(self._key)
        except Exception:  # pragma: no cover - defensive: boot must not break on a read blip
            log.warning("ledger_snapshot_load_failed", exc_info=True)
        return None

    def save(self, value: dict[str, Any]) -> None:
        """Persist ``value`` under this ledger's key.

        Never raises into the caller (a persistence blip must never break a
        scheduler tick); a failed write is logged and dropped — the in-memory
        ledger is still correct for the life of the process, only the
        restart-durability of THIS mutation is lost.
        """
        try:
            if self._session_factory is not None:
                sess = self._session_factory()
                try:
                    SqlAlchemyAppConfigStore(sess).set(self._key, value)
                finally:
                    sess.close()
                return
            if self._memory is not None:
                self._memory.set(self._key, value)
        except Exception:  # pragma: no cover - defensive: a tick must never break on a write blip
            log.warning("ledger_snapshot_save_failed", exc_info=True)
