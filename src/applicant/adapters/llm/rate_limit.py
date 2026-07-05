"""Per-provider LLM call rate limiter (dark-engine audit item 48, FR-DUR-2).

``LLM_RATE_LIMIT`` / ``LLM_RATE_PERIOD`` (``config.py``) describe a rolling-window
admission cap on outbound LLM calls, but nothing gated a call on it. This is a small,
self-contained rolling-window gate for the LLM *adapter* layer — it deliberately does
NOT depend on ``CapacityService``/the durable orchestration queue (an application-layer
concept) so the adapter stays a clean, hexagonal driven implementation with no upward
dependency. The rolling-window algorithm mirrors the shim's ``_Queue._rate_ok`` (evict
admissions older than the window, admit iff the window has room).

Keyed per ``(provider, base_url)`` so a multi-tier ladder spanning several providers/
endpoints doesn't share one bucket — a burst on tier 1 (e.g. a local Ollama) must not
gate tier 2 (e.g. OpenRouter).

Design points called out by the audit:

* ``limit`` of ``0`` (or ``None``) disables the gate entirely (matches the config
  comment "0 disables") — ``acquire`` then returns ``True`` immediately with no clock/
  lock overhead, so default-disabled construction is byte-identical to no gating.
* The wait is bounded: at most one ``sleep`` call, for at most ``period`` seconds (the
  time until the oldest admission in the window ages out) — never an unbounded retry
  loop. If the window is still full after that single bounded wait (e.g. a concurrent
  admission raced in), ``acquire`` returns ``False`` so the caller can fall back
  (climb the tier ladder) exactly like any other soft tier failure, rather than
  blocking indefinitely.
* ``clock``/``sleep`` are injectable so tests can exercise the bounded-wait path
  deterministically with no real wall-clock delay.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class LLMRateLimiter:
    """Rolling-window admission gate, one bucket per ``key`` (FR-DUR-2, #48)."""

    def __init__(
        self,
        limit: int | None,
        period: float | None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # "0 disables" (matches the LLM_RATE_LIMIT config comment): a non-positive
        # limit, or a missing period, means every ``acquire`` short-circuits True.
        self._limit = limit if (limit is not None and limit > 0) else None
        self._period = period if (period is not None and period > 0) else None
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        return self._limit is not None and self._period is not None

    def _evict(self, window: deque[float], now: float) -> None:
        period = self._period
        assert period is not None  # only called when enabled
        while window and now - window[0] >= period:
            window.popleft()

    def _try_admit(self, key: str, now: float) -> bool:
        """Admit ``key`` at ``now`` if its window has room (lock MUST be held)."""
        window = self._windows[key]
        self._evict(window, now)
        if len(window) < self._limit:  # type: ignore[arg-type]
            window.append(now)
            return True
        return False

    def acquire(self, key: str) -> bool:
        """Try to admit one call under ``key``'s rolling window.

        Disabled (``limit`` 0/``None``): always ``True``, no gating (byte-identical).
        Otherwise: admits immediately if the window has room; else waits ONCE for
        exactly the time until the oldest admission ages out (bounded by ``period`` —
        never longer, never a loop), then retries once. Still full after that single
        bounded wait -> ``False`` (the caller falls back, e.g. climbs the tier ladder).
        """
        if not self.enabled:
            return True
        with self._lock:
            now = self._clock()
            if self._try_admit(key, now):
                return True
            window = self._windows[key]
            # Bounded: the oldest entry is, by construction, within the window (it
            # would have been evicted above otherwise), so this is in [0, period].
            wait = max(0.0, self._period - (now - window[0]))  # type: ignore[operator]
        if wait > 0:
            self._sleep(wait)
        with self._lock:
            return self._try_admit(key, self._clock())

    def reset(self, key: str | None = None) -> None:
        """Test/ops helper: forget admission history (one key, or every key)."""
        with self._lock:
            if key is None:
                self._windows.clear()
            else:
                self._windows.pop(key, None)
