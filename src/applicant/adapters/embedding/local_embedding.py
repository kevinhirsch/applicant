"""Local embedding adapter (NFR-LOCAL-1).

# STAGE B — owned by Phase 1; flesh out here.

A local embedding model for dedup/variant-scoring/conversion-signature learning.
The stub returns deterministic placeholder vectors so callers can wire against the
port; Phase 1 replaces this with a real local model.
"""

from __future__ import annotations


class LocalEmbedding:
    """EmbeddingPort adapter (deterministic placeholder)."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        # STAGE B: real local embedding model.
        return [[float(len(t)), 0.0, 0.0] for t in texts]

    def similarity(self, a: str, b: str) -> float:
        # STAGE B: cosine similarity over real embeddings.
        if not a and not b:
            return 1.0
        return 1.0 if a == b else 0.0
