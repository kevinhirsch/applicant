"""UsageLedger — process-lived LLM token/cost accumulator (P1-6 cost & pace guardrails).

The shared ``OpenAICompatibleLLM`` singleton (built ONCE at boot, per
``container.py``) calls :meth:`UsageLedger.record` after every completion that
reported usage — from ANY code path (chat, discovery, material generation,
résumé parse-verify, ...), not scoped to one request or campaign. This is the
single point where "how many tokens / how many dollars has the engine spent"
gets tallied.

Keyed by UTC date only — deliberately OWNER-level, not per-campaign. P1-10 lit
up multi-campaign (several campaigns can now run side by side, each with its own
base résumé, digest, and pacing ledger), and this ledger intentionally stays
un-scoped: the guardrail is about the OWNER's total LLM spend across every
campaign, and the shared ``OpenAICompatibleLLM`` singleton has no campaign
context to attribute a completion to (chat/parse-verify calls serve no single
campaign). Per-campaign *pacing* attribution lives where campaign context
exists — the agent loop's per-(campaign, day) throughput ledger and the
per-campaign ``agent_runs.stats`` drain target — never here.

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
    _lock: threading.Lock = field(default_factory=threading.Lock, compare=False, repr=False)

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

    def restore(self, day: date, row: dict[str, float]) -> None:
        """Credit a previously-drained row back (persist failed after a drain).

        ``drain`` + a failed ``agent_runs.start_run`` must not silently lose the
        popped usage (H-series: nothing degrades silently) — the caller hands the
        drained row back and it folds into the running total, calls included.
        """
        if not row:
            return
        with self._lock:
            tot = self._totals.setdefault(day, dict(_ZERO_ROW))
            tot["tokens_in"] += max(0, int(row.get("tokens_in", 0)))
            tot["tokens_out"] += max(0, int(row.get("tokens_out", 0)))
            tot["cost_usd"] += max(0.0, float(row.get("cost_usd", 0.0)))
            tot["calls"] += max(0, int(row.get("calls", 0)))

    def peek(self, day: date) -> dict[str, float]:
        """Read-only snapshot of ``day``'s not-yet-persisted totals (no clear)."""
        with self._lock:
            row = self._totals.get(day)
        return dict(row) if row else dict(_ZERO_ROW)
