"""UsageLedger — process-lived LLM token/cost accumulator (P1-6 cost & pace guardrails).

The shared ``OpenAICompatibleLLM`` singleton (built ONCE at boot, per
``container.py``) calls :meth:`UsageLedger.record` after every completion that
reported usage — from ANY code path (chat, discovery, material generation,
résumé parse-verify, ...), not scoped to one request or campaign. This is the
single point where "how many tokens / how many dollars has the engine spent"
gets tallied.

Keyed by UTC date only: MVP-1 runs a single active campaign (see
``core/entities/campaign.py``) and the guardrail is about the OWNER's total LLM
spend, not one campaign's slice of it, so there is no per-campaign key to thread
through the adapter singleton.

Durability mirrors the existing ``AgentLoop._acted`` daily-throughput ledger:
this in-memory total is the NOT-YET-persisted delta. The scheduler's tick
(``AgentLoop._drain_usage_stats``, called from both ``_record_intent`` and
``_record_skip_reason``) drains it into the existing ``agent_runs.stats`` JSON
blob — no schema change needed, mirroring the skip-reason precedent — so at most
one scheduler interval (~60s) of usage is ever at risk from a restart.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date

_ZERO_ROW = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0}


@dataclass
class UsageLedger:
    """Thread-safe running total of not-yet-persisted LLM usage, by UTC day."""

    _totals: dict[date, dict[str, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, day: date, *, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
        """Add one completion's usage to ``day``'s running total.

        Deliberately does NOT prune other days here: ``drain`` is the only
        persistence path for this ledger (see the module docstring), so an
        un-drained day (the scheduler paused, or a clock jumped) must keep
        accumulating rather than being silently discarded when a new day's
        entry appears — dropping it would be exactly the kind of silent data
        loss the H-series honesty invariants forbid. In practice the dict stays
        tiny because the scheduler drains "today" roughly once per tick.
        """
        with self._lock:
            row = self._totals.setdefault(day, dict(_ZERO_ROW))
            row["tokens_in"] += max(0, int(tokens_in))
            row["tokens_out"] += max(0, int(tokens_out))
            row["cost_usd"] += max(0.0, float(cost_usd))
            row["calls"] += 1

    def drain(self, day: date) -> dict[str, float]:
        """Pop and return ``day``'s not-yet-persisted totals, zeroing them."""
        with self._lock:
            row = self._totals.pop(day, None)
        return dict(row) if row else dict(_ZERO_ROW)

    def peek(self, day: date) -> dict[str, float]:
        """Read-only snapshot of ``day``'s not-yet-persisted totals (no clear)."""
        with self._lock:
            row = self._totals.get(day)
        return dict(row) if row else dict(_ZERO_ROW)
