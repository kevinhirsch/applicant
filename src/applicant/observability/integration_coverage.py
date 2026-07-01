"""Integration-coverage ledger — un-exercised boundary accounting (issue #181).

The integration tests for the real adapters (TeX/LibreOffice render, the real
browser, Postgres-backed storage) are ``@pytest.mark.integration`` and **skip when
the dependency is absent**. A skip is a *signal* — the deployed image still needs
that dependency — but a bare ``pytest.skip`` makes the un-exercised boundary vanish
from the report: nobody sees that the LaTeX path was never actually run.

This module turns each such skip into a *tracked gap*: tests record the boundary
they could not exercise (and why) into a process-lived ledger, and the suite / a CI
step can surface the accumulated gaps so an operator knows exactly which real
boundaries the run did NOT cover. Pure in-memory bookkeeping — no IO, no network.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class UnexercisedBoundary:
    """One real-adapter boundary a run could not exercise, and why."""

    boundary: str  # e.g. "resume_render.latex", "browser.prefill", "storage.postgres"
    reason: str  # the missing dependency / skip reason
    test_id: str = ""  # the test node id that recorded it (optional)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class IntegrationCoverageLedger:
    """A process-lived ledger of un-exercised real-adapter boundaries.

    Thread-safe so the pytest-xdist workers + the recording test bodies do not race.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gaps: list[UnexercisedBoundary] = []

    def record(self, boundary: str, reason: str, *, test_id: str = "") -> UnexercisedBoundary:
        """Record a boundary the run could not exercise (a tracked gap)."""
        entry = UnexercisedBoundary(boundary=boundary, reason=reason, test_id=test_id)
        with self._lock:
            self._gaps.append(entry)
        return entry

    def gaps(self) -> list[UnexercisedBoundary]:
        """Every recorded un-exercised boundary (a copy, newest last)."""
        with self._lock:
            return list(self._gaps)

    def boundaries(self) -> set[str]:
        """The distinct boundary names that went un-exercised this run."""
        with self._lock:
            return {g.boundary for g in self._gaps}

    def is_empty(self) -> bool:
        with self._lock:
            return not self._gaps

    def clear(self) -> None:
        with self._lock:
            self._gaps.clear()

    def report(self) -> dict:
        """A flat report of the tracked gaps for logging / a CI summary."""
        gaps = self.gaps()
        return {
            "unexercised_count": len(gaps),
            "boundaries": sorted({g.boundary for g in gaps}),
            "gaps": [
                {"boundary": g.boundary, "reason": g.reason, "test_id": g.test_id}
                for g in gaps
            ],
        }


#: The process-lived ledger every test records into (one per interpreter).
LEDGER = IntegrationCoverageLedger()


def record_unexercised_boundary(
    boundary: str, reason: str, *, test_id: str = ""
) -> UnexercisedBoundary:
    """Record an un-exercised real-adapter boundary into the shared ledger (#181).

    Call this from an integration test's skip path instead of a bare ``pytest.skip``
    so the boundary surfaces as a tracked gap rather than vanishing. Returns the
    recorded entry.
    """
    return LEDGER.record(boundary, reason, test_id=test_id)


def coverage_report() -> dict:
    """The accumulated un-exercised-boundary report for the current run."""
    return LEDGER.report()
