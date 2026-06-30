"""Routine-store adapters (#306 — AWM workflow-induction + ACE curation).

* ``in_memory`` — the DEFAULT process-lived adapter (no external deps, import-safe).
  One instance is created per process in ``app/container.py`` and injected into every
  per-tick :class:`~applicant.application.services.prefill_service.PrefillService`,
  exactly like the resume/curation ledgers, so the induced routines survive the
  scheduler's per-tick loop rebuild.
"""

from __future__ import annotations

from applicant.adapters.routine.in_memory import InMemoryRoutineStore

__all__ = ["InMemoryRoutineStore"]
