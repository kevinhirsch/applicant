"""RecallIndex port (FR-MIND-3 — cross-session recall).

The agent can recall its own past runs/conversations by **full-text** and
**semantic** search over the engine's durable history. Conceptually this is
Postgres FTS (the re-home of upstream's SQLite FTS5) plus the already-deployed
chromadb for embedding recall (``NFR-LOCAL-1`` — embeddings local). Recall is
**on-demand** (a tool the loop calls), so it costs tokens only when used, and is
scoped to the owner/campaign.

This slice ships only the in-memory adapter; the Postgres FTS + chromadb adapter
lands when the surface un-dormants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RecallHit:
    """One recalled past run/conversation excerpt (FR-MIND-3).

    ``score`` is a 0..1 relevance (higher = better); ``run_id`` ties back to the
    durable run; ``campaign_id`` is set when the source run was campaign-scoped.
    """

    run_id: str
    text: str
    score: float = 0.0
    campaign_id: str | None = None


@runtime_checkable
class RecallIndex(Protocol):
    """Outbound port for full-text + semantic recall of past runs (FR-MIND-3)."""

    def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
        """Add (or update) one past run/conversation excerpt to the recall index."""
        ...

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        scope: str | None = None,
        campaign_id: str | None = None,
    ) -> tuple[RecallHit, ...]:
        """Return up to ``limit`` recall hits ranked by relevance to ``query``.

        ``scope``/``campaign_id`` scope the search to the owner/campaign. The result
        is bounded by ``limit`` so recall never floods the prompt (FR-MIND-13).
        """
        ...
