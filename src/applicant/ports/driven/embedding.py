"""Embedding port (NFR-LOCAL-1).

Local embedding model used for dedup, variant scoring, and conversion-signature
learning. Runs locally; no cloud dependency (NFR-LOCAL-1).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingPort(Protocol):
    """Outbound port for local text embeddings."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return an embedding vector per input text (local model)."""
        ...

    def similarity(self, a: str, b: str) -> float:
        """Cosine similarity in [0, 1] between two texts (dedup/scoring)."""
        ...
