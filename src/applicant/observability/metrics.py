"""Operational metrics + scheduler liveness/heartbeat (FR-OBS-2 / NFR-OPS).

Before this, ``observability/`` was logging-only: each scheduler tick emitted a
structured log line but nothing exposed a *queryable* operational surface and
nothing alerted when the 24/7 loop fell over. A repeated-failure stall therefore
showed up only as a stream of warning log lines — never an operator-facing alert.

This module adds a tiny, dependency-free, in-process metrics registry that:

* counts ticks (total / succeeded / failed) and tracks **consecutive failures**;
* records a **scheduler-liveness heartbeat** (the wall-clock of the last tick) so a
  status surface can answer "is the loop alive and when did it last run";
* decides — purely, from the counters — when N consecutive failures should raise
  ONE operator alert (``consecutive_failure_alert``), and remembers that it already
  alerted so the caller fires the notification ladder exactly once per stall episode
  (idempotent; it re-arms only after a tick succeeds again).

It deliberately ships NO prometheus/statsd/otel dependency: it is the in-memory
read-model the agent-status surface tails (mirroring ``logging._LOG_RING``), and the
hook a real exporter can later scrape. A process-lived module-level singleton backs
the free functions the 24/7 loop and the BDD acceptance specs call; the
``Metrics`` class is also importable so a fresh, isolated instance can be injected
in tests (no global bleed-through).

Time is an injected clock everywhere (``record_tick(now=...)``) so the surface is
unit-tested deterministically with no real sleeps.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: Default number of CONSECUTIVE failed ticks that raises one operator alert. A
#: small N catches a real stall fast while tolerating a single transient blip; the
#: scheduler reads the configurable ``LOOP_FAILURE_ALERT_THRESHOLD`` and passes it in.
DEFAULT_FAILURE_ALERT_THRESHOLD = 3


@dataclass
class _Counters:
    """The mutable tick counters + liveness heartbeat (FR-OBS-2)."""

    ticks_total: int = 0
    ticks_succeeded: int = 0
    ticks_failed: int = 0
    consecutive_failures: int = 0
    last_heartbeat: datetime | None = None
    last_tick_success: bool | None = None
    #: True once an alert has been raised for the CURRENT failure streak — so the
    #: caller raises the ladder exactly once per stall (re-armed on the next success).
    alerted: bool = False
    extra: dict[str, int] = field(default_factory=dict)


class Metrics:
    """A small, thread-safe, in-process operational-metrics registry (FR-OBS-2).

    One writer (the 24/7 loop) and a handful of readers (status surface), but the
    scheduler tick now runs OFF the event loop on a worker thread, so the
    read-modify-write of the counters is guarded against two overlapping ticks.
    """

    def __init__(
        self, *, failure_alert_threshold: int = DEFAULT_FAILURE_ALERT_THRESHOLD
    ) -> None:
        # A 0/negative threshold would alert on the very first failure (or never make
        # sense); clamp to at least 1 so the surface always behaves coherently.
        self._threshold = max(1, int(failure_alert_threshold))
        self._c = _Counters()
        self._lock = threading.Lock()

    @property
    def failure_alert_threshold(self) -> int:
        return self._threshold

    def set_failure_alert_threshold(self, threshold: int) -> None:
        """Re-point the consecutive-failure alert threshold (clamped to >= 1)."""
        with self._lock:
            self._threshold = max(1, int(threshold))

    def record_tick(
        self, *, success: bool, now: datetime | None = None, **counters: int
    ) -> None:
        """Record one scheduler tick (FR-OBS-2).

        Bumps the total + per-outcome counters, refreshes the liveness heartbeat to
        ``now`` (injected clock; defaults to wall-clock), grows or resets the
        consecutive-failure streak, and re-arms the alert latch on a success so the
        next stall can alert again. ``**counters`` accumulates optional named gauges
        (e.g. ``campaigns``, ``ladder_fired``) so a real exporter has them later.
        """
        now = now or datetime.now(UTC)
        with self._lock:
            self._c.ticks_total += 1
            self._c.last_heartbeat = now
            self._c.last_tick_success = bool(success)
            if success:
                self._c.ticks_succeeded += 1
                self._c.consecutive_failures = 0
                # A healthy tick re-arms the alert so a FUTURE stall alerts again.
                self._c.alerted = False
            else:
                self._c.ticks_failed += 1
                self._c.consecutive_failures += 1
            for key, value in counters.items():
                self._c.extra[key] = self._c.extra.get(key, 0) + int(value)

    def consecutive_failure_alert(self) -> dict | None:
        """Return an operator-alert payload IFF the failure threshold is crossed.

        Returns ``None`` when the loop is healthy / below threshold. Once the
        consecutive-failure streak reaches the threshold it returns a small,
        plain-language alert descriptor (count + threshold) — and is **idempotent**:
        the first call past the threshold returns the payload and latches ``alerted``,
        so a subsequent call during the SAME stall returns ``None`` (no spam). The
        latch clears on the next successful tick (see :meth:`record_tick`), so a new
        stall alerts again.
        """
        with self._lock:
            if self._c.consecutive_failures < self._threshold:
                return None
            if self._c.alerted:
                return None
            self._c.alerted = True
            return {
                "consecutive_failures": self._c.consecutive_failures,
                "threshold": self._threshold,
                "last_heartbeat": (
                    self._c.last_heartbeat.isoformat()
                    if self._c.last_heartbeat
                    else None
                ),
            }

    def snapshot(self) -> dict:
        """A read-only point-in-time view of the metrics surface (FR-OBS-2)."""
        with self._lock:
            c = self._c
            return {
                "ticks_total": c.ticks_total,
                "ticks_succeeded": c.ticks_succeeded,
                "ticks_failed": c.ticks_failed,
                "consecutive_failures": c.consecutive_failures,
                "failure_alert_threshold": self._threshold,
                "last_heartbeat": (
                    c.last_heartbeat.isoformat() if c.last_heartbeat else None
                ),
                "last_tick_success": c.last_tick_success,
                "alerting": c.consecutive_failures >= self._threshold,
                **dict(c.extra),
            }

    def reset(self) -> None:
        """Clear all counters (used by tests to isolate the process-lived singleton)."""
        with self._lock:
            self._c = _Counters()


#: The process-lived metrics registry the 24/7 loop writes and the status surface
#: reads (mirrors ``logging._LOG_RING``). Tests can ``reset()`` it or construct a
#: fresh ``Metrics()`` to avoid global bleed-through.
_METRICS = Metrics()


def get_metrics() -> Metrics:
    """Return the process-lived metrics registry."""
    return _METRICS


def record_tick(*, success: bool, now: datetime | None = None, **counters: int) -> None:
    """Record one tick on the process-lived registry (free-function convenience)."""
    _METRICS.record_tick(success=success, now=now, **counters)


def consecutive_failure_alert() -> dict | None:
    """Operator-alert payload on the process-lived registry, or ``None``."""
    return _METRICS.consecutive_failure_alert()


def snapshot() -> dict:
    """A read-only snapshot of the process-lived registry."""
    return _METRICS.snapshot()


def reset() -> None:
    """Reset the process-lived registry (test isolation)."""
    _METRICS.reset()
