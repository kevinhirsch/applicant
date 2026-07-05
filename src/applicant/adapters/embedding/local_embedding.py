"""Local embedding adapter (NFR-LOCAL-1).

# STAGE B — owned by Phase 1.

A deterministic, dependency-free, **hashing-based** embedding so dedup, variant
scoring, and conversion-signature learning work fully offline with **no model
download** (NFR-LOCAL-1). A real local model (e.g. a sentence-transformer served on
the network) implements the same ``EmbeddingPort`` and drops in later.

The hashing trick maps token hashes into a fixed-width vector; cosine similarity over
those vectors is stable across runs/processes and gives a meaningful (if coarse)
lexical-overlap signal, which is all Phase 1 learning needs.
"""

from __future__ import annotations

import hashlib
import math
import re

_DIM = 64
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _hash_bucket(token: str) -> tuple[int, float]:
    """Map a token to a (bucket, sign) using a stable hash (no randomness)."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    h = int.from_bytes(digest, "big")
    bucket = h % _DIM
    sign = 1.0 if (h >> 8) & 1 else -1.0
    return bucket, sign


def _vector(text: str) -> list[float]:
    vec = [0.0] * _DIM
    for tok in _tokens(text):
        bucket, sign = _hash_bucket(tok)
        vec[bucket] += sign
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class LocalEmbedding:
    """EmbeddingPort adapter (deterministic hashing-based; no model download)."""

    #: dark-engine audit #79: a real (sentence-transformer-backed) adapter would
    #: set these to something like ("sentence-transformer", "model-backed") when
    #: it drops in behind the same ``EmbeddingPort`` — this backend is always the
    #: basic offline hashing-trick, disclosed honestly rather than left silent.
    backend = "hashing-trick"
    quality_tier = "basic"

    def describe(self) -> dict:
        """Plain-language disclosure of which embedding backend is active (#79).

        Powers dedup, resume-variant scoring, and conversion-signature learning
        fully offline with no model download — but the lexical-overlap signal it
        gives is coarse, not true semantic similarity. Read-only; never claims a
        quality this backend doesn't have.
        """
        return {
            "backend": self.backend,
            "quality_tier": self.quality_tier,
            "model_backed": False,
            "detail": (
                "Matching runs on a basic offline word-overlap comparison, not a "
                "trained language model. It works everywhere with no setup, but "
                "semantic matches (paraphrases, synonyms) are less precise than a "
                "model-backed embedding would give."
            ),
        }

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vector(t) for t in texts]

    def similarity(self, a: str, b: str) -> float:
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        # The port contract says ~0 for unrelated text and ~1 for identical.
        # The old ``(cos + 1) / 2`` remap pushed genuinely-disjoint texts (cosine
        # near 0) to ~0.5, which inflated off-topic JD viability scores to ~50/100.
        # Clamp the raw cosine into [0, 1] instead: orthogonal (no token overlap)
        # vectors land near 0, related vectors stay high. Negative cosine (anti-
        # correlated hash signs) also floors at 0.
        cos = _cosine(_vector(a), _vector(b))
        return max(0.0, min(1.0, cos))
