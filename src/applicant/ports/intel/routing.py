"""Deterministic context-size routing: estimate tokens, choose local/cloud tier.

FR-INTEL-3 — pure, no model call, no network, no engine logic.
The token estimate is a chars/4 heuristic, not a real tokenizer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from applicant.ports.intel.envelope import envelope


@dataclass
class RouteDecision:
    """Outcome of a context-routing decision."""

    recommendation: str  # "LOCAL" | "LOCAL-SINGLE" | "CLOUD"
    estimated_tokens: int
    concurrency: int
    why: str
    split_hint: Optional[str] = None


# ---- Heuristic token estimation (chars/4) ----


def estimate_tokens(
    text: Optional[str] = None,
    paths: Optional[list[str]] = None,
    base_tokens: int = 9000,
) -> int:
    """Estimate token count from raw text and/or file contents.

    Uses a rough chars/4 heuristic — NOT a real tokenizer.
    Deterministic: same inputs always return the same int.
    Missing files are silently treated as 0 content (no error raised).
    """
    total_chars = 0
    if text:
        total_chars += len(text)
    if paths:
        for p in paths:
            try:
                total_chars += len(Path(p).read_text(encoding="utf-8", errors="ignore"))
            except (FileNotFoundError, OSError):
                pass  # missing file -> 0
    return base_tokens + (total_chars // 4)


# ---- Routing decision ----

_DUAL_DEFAULT = 40000
_HEADROOM = 6000


def route(estimated_tokens: int, profile_name: str = "reference") -> RouteDecision:
    """Return a RouteDecision based on estimated tokens and the hardware profile.

    Thresholds are derived from the profile's ctx_cap (with 6K headroom)
    and a fixed dual-concurrency ceiling (40K default).
    """
    prof = envelope(profile_name)
    concurrency: int = prof["concurrency"]
    ctx_cap: int = prof["ctx_cap"]

    # Cloud-only profiles (concurrency == 0) always route to CLOUD.
    if concurrency == 0:
        return RouteDecision(
            recommendation="CLOUD",
            estimated_tokens=estimated_tokens,
            concurrency=0,
            why="profile cloud-only",
            split_hint="split into <40000-token local chunks",
        )

    local_single_below: int = ctx_cap - _HEADROOM  # e.g. 96000-6000 = 90000
    local_dual_below: int = _DUAL_DEFAULT  # 40000

    if estimated_tokens < local_dual_below:
        return RouteDecision(
            recommendation="LOCAL",
            estimated_tokens=estimated_tokens,
            concurrency=concurrency,
            why=f"estimated {estimated_tokens} < local dual-cap {local_dual_below}; {concurrency} concurrent OK",
        )

    if estimated_tokens <= local_single_below:
        return RouteDecision(
            recommendation="LOCAL-SINGLE",
            estimated_tokens=estimated_tokens,
            concurrency=1,
            why=f"estimated {estimated_tokens} between local dual-cap {local_dual_below} and single-cap {local_single_below}; run alone",
        )

    return RouteDecision(
        recommendation="CLOUD",
        estimated_tokens=estimated_tokens,
        concurrency=0,
        why=f"estimated {estimated_tokens} > local single-cap {local_single_below}",
        split_hint="split into <40000-token local chunks",
    )


# ---- Convenience composite ----


def context_estimate(
    text: Optional[str] = None,
    paths: Optional[list[str]] = None,
    base_tokens: int = 9000,
    profile_name: str = "reference",
) -> RouteDecision:
    """Estimate tokens and route in one call."""
    est = estimate_tokens(text=text, paths=paths, base_tokens=base_tokens)
    return route(est, profile_name=profile_name)
