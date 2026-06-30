"""Per-job-board (per-domain) request pacing (FR-DISC-*, #195).

The engine clamps campaign-level throughput (``core.entities.campaign.clamp_throughput``)
but that says nothing about how fast requests hit any ONE job board. Discovering ten
postings from the same ``linkedin.com`` domain in a single burst is exactly the pattern
anti-bot detection trips on. This pure-core rule holds the **per-domain interval** policy
so every scheduling path shares one definition and the pacing can never be bypassed.

Pure + side-effect-free (no clock import at module level): the caller supplies ``now`` so
the rule stays deterministic and hermetically testable. ``SourcePacer`` is a tiny stateful
holder of the last-allowed timestamp per domain that drives the decision through the pure
:func:`next_allowed_at` helper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

#: Default minimum seconds between two requests to the SAME job-board domain. A
#: conservative spacing that keeps a burst of same-board postings under anti-bot radar
#: while still letting discovery make steady progress. Operator-overridable per pacer.
DEFAULT_PER_DOMAIN_INTERVAL_SECONDS: float = 2.0


def domain_of(url: str) -> str:
    """Extract the bare registrable host (lowercased, no ``www.``) from a URL.

    Best-effort and total: a blank/garbage URL yields ``""`` so the caller can treat
    un-attributable requests as a single bucket rather than crashing.
    """
    if not url:
        return ""
    host = (urlparse(url).netloc or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    # Drop any ``user:pass@`` and ``:port`` decoration.
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host


def next_allowed_at(
    last_allowed_at: float | None,
    *,
    interval_seconds: float = DEFAULT_PER_DOMAIN_INTERVAL_SECONDS,
) -> float:
    """The earliest monotonic timestamp at which the next request to a domain may fire.

    With no prior request (``last_allowed_at is None``) the answer is ``0.0`` — fire
    immediately. Otherwise it is ``last_allowed_at + interval_seconds``.
    """
    if last_allowed_at is None:
        return 0.0
    return last_allowed_at + max(0.0, float(interval_seconds))


@dataclass
class SourcePacer:
    """Stateful per-domain pacer enforcing a configurable minimum interval (#195).

    Lives as a process-scoped object (like the resume backoff ledger) so pacing
    survives across the per-tick service rebuild. Holds the last-allowed timestamp per
    domain and answers two questions through the pure :func:`next_allowed_at` helper:

    * :meth:`ready` — may a request to ``url`` fire at ``now`` yet?
    * :meth:`record` — mark that a request to ``url`` fired at ``now``.

    The caller supplies ``now`` (a monotonic seconds value) so the pacer is deterministic
    and never imports a clock itself.
    """

    interval_seconds: float = DEFAULT_PER_DOMAIN_INTERVAL_SECONDS
    _last: dict[str, float] = field(default_factory=dict)

    def next_allowed_at(self, url: str) -> float:
        """Earliest time a request to ``url``'s domain may fire."""
        return next_allowed_at(
            self._last.get(domain_of(url)), interval_seconds=self.interval_seconds
        )

    def ready(self, url: str, now: float) -> bool:
        """True when ``now`` has reached the domain's next-allowed time."""
        return now >= self.next_allowed_at(url)

    def record(self, url: str, now: float) -> None:
        """Mark that a request to ``url``'s domain fired at ``now``."""
        self._last[domain_of(url)] = now

    def reset(self) -> None:
        """Forget all per-domain history (e.g. between independent runs)."""
        self._last.clear()
