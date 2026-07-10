"""InMemoryRoutineStore — the default process-lived RoutineStore adapter (#306).

Holds induced per-ATS routines in a process-lived dict guarded by an ``RLock`` (the
per-tick prefill loops share one instance, so the store owns its own lock — each
loop has a *different* lock). ACE curation lives here: ``record_success`` /
``record_failure`` move a routine's net score, and a routine that crosses the prune
threshold on net failure is dropped so it can no longer be injected as a prior.

Hermetic + import-safe (no external deps).

**Restart durability (Skyvern-parity #2).** Being process-lived made the store
*tick*-safe (one instance injected into every per-tick :class:`PrefillService`), but
a genuine process restart (an ``update.sh`` deploy, an OOM kill, a crash) still wiped
it — every AWM-induced per-ATS routine and every ACE success/failure weight was lost,
so #306's "coverage grows itself" did not survive a redeploy. Exactly like the resume
backoff ledger (DISC-2), the store now takes an optional ``persister`` (a duck-typed
``load() -> dict | None`` / ``save(dict) -> None`` snapshot store — the
``ConfigLedgerStore`` over the durable ``app_config`` table, so **no new table or
migration** is needed). When one is injected the store reloads its snapshot at boot
(:meth:`restore`) and re-persists after every mutation (:meth:`persist`), so the
induced routines + ACE weights survive a restart. Absent a persister (unit tests,
first boot without Postgres, hermetic lane) the store is byte-identical to before —
a pure in-memory object.

**Data-only invariant (NFR-TRUTH-1).** The snapshot serializes the whole
:class:`Routine` / :class:`RoutineStep` graph, which by construction carries only op
kinds + structural locators (``ref``/``role``/``name``) and attribute-cloud /
document-library references **by id** — there is no field that holds a literal
user-supplied value or secret, so a routine can never smuggle a fabricated answer
through persistence any more than it can through the planner prior.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from typing import Any

from applicant.ports.driven.routine_store import (
    DEFAULT_PRUNE_THRESHOLD,
    Routine,
    RoutineStep,
)

log = logging.getLogger(__name__)


class InMemoryRoutineStore:
    """Process-lived in-memory RoutineStore (default adapter), optionally durable."""

    def __init__(
        self,
        *,
        prune_threshold: int = DEFAULT_PRUNE_THRESHOLD,
        persister: Any = None,
    ) -> None:
        self._routines: dict[str, Routine] = {}
        self._lock = threading.RLock()
        # Net-failure margin (failures − successes) at which a routine is pruned.
        self._prune_threshold = int(prune_threshold)
        #: Optional restart-durable snapshot store (Skyvern-parity #2). Duck-typed:
        #: ``load() -> dict | None`` and ``save(dict) -> None``. Injected by the
        #: container; ``None`` keeps the store a pure in-memory object (unchanged).
        self._persister = persister

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
        self.persist()
        return routine

    def record_success(self, domain: str) -> None:
        if not domain:
            return
        with self._lock:
            existing = self._routines.get(domain)
            if existing is None:
                return
            self._routines[domain] = replace(existing, successes=existing.successes + 1)
        self.persist()

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
                result: Routine | None = None
            else:
                self._routines[domain] = updated
                result = updated
        self.persist()
        return result

    # --- introspection (tests / diagnostics) ------------------------------
    def all_domains(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._routines.keys())

    # --- restart durability (Skyvern-parity #2) ---------------------------
    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-able snapshot of every stored routine (taken under the lock).

        Serializes the whole :class:`Routine`/:class:`RoutineStep` graph. Every field
        is either a structural locator or an id / counter — there is NO literal value
        field, so the snapshot is data-only by construction (NFR-TRUTH-1). This is the
        exact shape :meth:`_load_snapshot` reads back.
        """
        with self._lock:
            return {
                "routines": {
                    domain: {
                        "domain": r.domain,
                        "steps": [
                            {
                                "kind": s.kind,
                                "ref": s.ref,
                                "attribute_id": s.attribute_id,
                                "document_id": s.document_id,
                                "role": s.role,
                                "name": s.name,
                            }
                            for s in r.steps
                        ],
                        "successes": r.successes,
                        "failures": r.failures,
                        "source": r.source,
                    }
                    for domain, r in self._routines.items()
                }
            }

    def _load_snapshot(self, data: dict[str, Any]) -> None:
        """Replace the routines from a :meth:`snapshot` dict, IN PLACE under the lock.

        Mutates the existing ``_routines`` dict (clear + refill) rather than rebinding
        it, mirroring ``ResumeLedger._load_snapshot`` — cheap insurance in case any
        caller ever captures a direct reference to the container. A malformed/partial
        entry is skipped so a corrupt blob never blocks boot.
        """
        with self._lock:
            self._routines.clear()
            for domain, raw in (data.get("routines") or {}).items():
                if not domain or not isinstance(raw, dict):
                    continue
                try:
                    steps = tuple(
                        RoutineStep(
                            kind=str(s.get("kind", "")),
                            ref=str(s.get("ref", "")),
                            attribute_id=str(s.get("attribute_id", "")),
                            document_id=str(s.get("document_id", "")),
                            role=str(s.get("role", "")),
                            name=str(s.get("name", "")),
                        )
                        for s in (raw.get("steps") or [])
                        if isinstance(s, dict)
                    )
                    self._routines[str(domain)] = Routine(
                        domain=str(raw.get("domain", domain)),
                        steps=steps,
                        successes=int(raw.get("successes", 1)),
                        failures=int(raw.get("failures", 0)),
                        source=str(raw.get("source", "induced")),
                    )
                except (TypeError, ValueError):  # pragma: no cover - skip a bad entry
                    continue

    def restore(self) -> None:
        """Reload the durable state from the persister at boot (no-op without one)."""
        if self._persister is None:
            return
        data = self._persister.load()
        if data:
            self._load_snapshot(data)

    def persist(self) -> None:
        """Persist the current routines (no-op without a persister).

        Called after every mutation. The persister itself never raises (it logs and
        drops on a storage blip), so a failed write leaves the in-memory store correct
        for the life of the process and only forfeits the durability of that one
        mutation — the tick is never broken.
        """
        if self._persister is None:
            return
        try:
            self._persister.save(self.snapshot())
        except Exception:  # pragma: no cover - defensive: a tick must never break on a write blip
            log.warning("routine_store_persist_failed", exc_info=True)
