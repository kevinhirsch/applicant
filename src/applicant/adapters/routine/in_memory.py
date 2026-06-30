"""InMemoryRoutineStore — the default process-lived RoutineStore adapter (#306).

Holds induced per-ATS routines in a process-lived dict guarded by an ``RLock`` (the
per-tick prefill loops share one instance, so the store owns its own lock — each
loop has a *different* lock). ACE curation lives here: ``record_success`` /
``record_failure`` move a routine's net score, and a routine that crosses the prune
threshold on net failure is dropped so it can no longer be injected as a prior.

Hermetic + import-safe (no external deps). A DB-backed adapter can implement the
same :class:`~applicant.ports.driven.routine_store.RoutineStore` Protocol later for
durability across process restarts.
"""

from __future__ import annotations

import threading
from dataclasses import replace

from applicant.ports.driven.routine_store import (
    DEFAULT_PRUNE_THRESHOLD,
    Routine,
    RoutineStep,
)


class InMemoryRoutineStore:
    """Process-lived in-memory RoutineStore (default adapter)."""

    def __init__(self, *, prune_threshold: int = DEFAULT_PRUNE_THRESHOLD) -> None:
        self._routines: dict[str, Routine] = {}
        self._lock = threading.RLock()
        # Net-failure margin (failures − successes) at which a routine is pruned.
        self._prune_threshold = int(prune_threshold)

    def get(self, domain: str) -> Routine | None:
        if not domain:
            return None
        with self._lock:
            return self._routines.get(domain)

    def induce(self, domain: str, steps: tuple[RoutineStep, ...]) -> Routine | None:
        if not domain or not steps:
            return None
        with self._lock:
            existing = self._routines.get(domain)
            if existing is None:
                routine = Routine(domain=domain, steps=tuple(steps))
            else:
                # Refresh the recipe with the latest working trace and up-weight:
                # re-inducing the same domain means it worked again (ACE success).
                routine = replace(
                    existing,
                    steps=tuple(steps),
                    successes=existing.successes + 1,
                )
            self._routines[domain] = routine
            return routine

    def record_success(self, domain: str) -> None:
        if not domain:
            return
        with self._lock:
            existing = self._routines.get(domain)
            if existing is None:
                return
            self._routines[domain] = replace(existing, successes=existing.successes + 1)

    def record_failure(self, domain: str) -> Routine | None:
        if not domain:
            return None
        with self._lock:
            existing = self._routines.get(domain)
            if existing is None:
                return None
            updated = replace(existing, failures=existing.failures + 1)
            # ACE prune: once a routine's net failures cross the threshold it is
            # removed, so a stale routine stops poisoning future plans.
            if (updated.failures - updated.successes) >= self._prune_threshold:
                del self._routines[domain]
                return None
            self._routines[domain] = updated
            return updated

    # --- introspection (tests / diagnostics) ------------------------------
    def all_domains(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._routines.keys())
