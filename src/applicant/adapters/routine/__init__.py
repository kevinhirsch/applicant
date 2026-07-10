"""Routine-store adapters (#306 — AWM workflow-induction + ACE curation).

* ``in_memory`` — the DEFAULT process-lived adapter (no external deps, import-safe).
  One instance is created per process in ``app/container.py`` and injected into every
  per-tick :class:`~applicant.application.services.prefill_service.PrefillService`,
  exactly like the resume/curation ledgers, so the induced routines survive the
  scheduler's per-tick loop rebuild. Given an optional ``persister`` (the
  ``ConfigLedgerStore`` over the durable ``app_config`` table, wired by the container),
  it also snapshots after every mutation and reloads at boot, so the routines + ACE
  weights survive a genuine process RESTART (Skyvern-parity #2) — no new table/migration.
  Absent a persister it is byte-identical to a pure in-memory store.
"""

from __future__ import annotations

from applicant.adapters.routine.in_memory import InMemoryRoutineStore

__all__ = ["InMemoryRoutineStore"]
