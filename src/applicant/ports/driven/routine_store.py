"""RoutineStore port (#306 — the self-improvement flywheel's memory of what worked).

After a SUCCESSFUL pre-fill page, the engine **induces** a reusable per-ATS
**routine** from the execution trace (AWM workflow-induction): the compact,
data-only op-sequence that actually filled the page, keyed by the page's
**domain / ATS tenant**. On the next encounter of the same domain, the stored
routine is injected into the planner as a *prior* ("a routine that worked here
before: …"), so coverage grows itself rather than re-deriving every plan
cold-start.

This is the planner's long-lived memory, so — exactly like the resume backoff
ledger and the curation ledger (see ``app/container.py``) — it must be a
**process-lived** object injected into every per-tick :class:`PrefillService`,
NOT stored on a per-tick instance (the scheduler rebuilds the loop each tick and
any per-instance state silently resets). The default adapter is in-memory and
import-safe; a DB-backed adapter can implement the same Protocol later.

**ACE curation:** each routine carries a success/failure counter updated when it
is reused. A routine that keeps failing on reuse is pruned (or down-weighted) so
a stale routine can't poison future plans.

A routine is **data, not free text** — a tuple of :class:`RoutineStep` (op kind +
the structural slots the executor cares about), never a literal value. It carries
no fabricated answers: like the typed Plan DSL, fill/select/upload steps reference
the attribute-cloud / document-library *by id*, so a routine can never smuggle a
fabricated value into a form (NFR-TRUTH-1 holds by construction).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Default number of consecutive (net) failures on reuse before a routine is pruned.
#: Kept small so a stale routine stops poisoning plans quickly; the success counter
#: offsets failures so a mostly-working routine survives the odd transient miss.
DEFAULT_PRUNE_THRESHOLD = 3


@dataclass(frozen=True)
class RoutineStep:
    """One structural step of an induced routine (data, never a literal value).

    Mirrors the load-bearing slots of the typed Plan ops: ``kind`` is the
    :class:`~applicant.core.entities.plan.OpKind` value; ``ref`` is the stable
    element handle; ``attribute_id`` / ``document_id`` reference the attribute
    cloud / document library **by id** (never a value). ``role`` / ``name`` carry
    the locator hints the planner used to find the element, so the prior can be
    re-grounded against a slightly-shifted DOM.
    """

    kind: str
    ref: str = ""
    attribute_id: str = ""
    document_id: str = ""
    role: str = ""
    name: str = ""


@dataclass(frozen=True)
class Routine:
    """A reusable per-ATS workflow induced from a successful pre-fill trace.

    ``domain`` is the ATS tenant / host the routine is keyed by. ``steps`` is the
    compact, ordered op-sequence that worked. ``successes`` / ``failures`` are the
    ACE-curation counters updated on reuse; ``score`` (successes − failures) drives
    pruning. ``source`` records how it was learned (induction by default).
    """

    domain: str
    steps: tuple[RoutineStep, ...] = ()
    successes: int = 1
    failures: int = 0
    source: str = "induced"

    @property
    def score(self) -> int:
        """Net reliability used for pruning/down-weighting (successes − failures)."""
        return self.successes - self.failures

    def as_prior_text(self) -> str:
        """Render the routine as a compact planning-prior hint for the LLM prompt.

        Data → a terse, deterministic, line-per-step summary — never free text and
        never a literal value (only op kinds + ids/locators), so it cannot leak a
        fabricated answer into the plan.
        """
        lines = []
        for s in self.steps:
            slots = []
            if s.ref:
                slots.append(f"ref={s.ref}")
            if s.attribute_id:
                slots.append(f"attribute_id={s.attribute_id}")
            if s.document_id:
                slots.append(f"document_id={s.document_id}")
            if s.role:
                slots.append(f"role={s.role}")
            if s.name:
                slots.append(f"name={s.name}")
            lines.append(f"- {s.kind} " + " ".join(slots) if slots else f"- {s.kind}")
        return "\n".join(lines)


@runtime_checkable
class RoutineStore(Protocol):
    """Outbound port for induced per-ATS routines (#306 AWM + ACE).

    Implementations MUST be process-lived / DB-backed and thread-safe enough for
    the per-tick loops to share one instance (each per-tick loop has its own lock,
    so the store owns its own).
    """

    def get(self, domain: str) -> Routine | None:
        """Return the stored routine for ``domain``, or ``None`` if none is live.

        A routine that has been pruned (or never existed) returns ``None`` so the
        planner falls back to a cold plan.
        """
        ...

    def induce(self, domain: str, steps: tuple[RoutineStep, ...]) -> Routine | None:
        """AWM workflow-induction: store/refresh the routine for ``domain``.

        Called after a SUCCESSFUL pre-fill page with the op-sequence that worked.
        Returns the stored routine, or ``None`` if ``steps`` is empty (nothing to
        induce). Re-inducing an existing domain refreshes its steps and counts a
        success (ACE up-weight).
        """
        ...

    def record_success(self, domain: str) -> None:
        """ACE: a reused routine led to a successful page — up-weight it."""
        ...

    def record_failure(self, domain: str) -> Routine | None:
        """ACE: a reused routine led to a failure — down-weight it.

        Returns the routine if it survives, or ``None`` once it crosses the prune
        threshold and is removed (so a stale routine stops being injected).
        """
        ...
