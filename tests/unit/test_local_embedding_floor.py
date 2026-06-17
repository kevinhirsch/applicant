"""Off-topic similarity must floor near 0 (viability scoring base).

The old ``(cos + 1) / 2`` remap pushed disjoint texts to ~0.5, inflating
off-topic JD viability to ~50/100. These tests fail before the floor fix and
pass after.
"""

from __future__ import annotations

from applicant.adapters.embedding.local_embedding import LocalEmbedding

_VIABILITY_THRESHOLD = 0.7


def test_offtopic_pair_is_near_zero():
    emb = LocalEmbedding()
    score = emb.similarity(
        "senior python backend engineer fastapi postgres distributed systems",
        "pastry chef bakery croissant sourdough buttercream frosting",
    )
    # Well below the 0.7 viability threshold (old remap returned ~0.5).
    assert score < 0.2
    assert score < _VIABILITY_THRESHOLD


def test_related_pair_stays_high():
    emb = LocalEmbedding()
    score = emb.similarity(
        "senior python backend engineer fastapi",
        "python backend engineer building fastapi services",
    )
    assert score > 0.5


def test_related_beats_unrelated_and_unrelated_floors():
    emb = LocalEmbedding()
    related = emb.similarity(
        "kubernetes platform engineer terraform go",
        "platform engineer working with kubernetes and terraform",
    )
    unrelated = emb.similarity(
        "kubernetes platform engineer terraform go",
        "marine biology coral reef ecosystem research",
    )
    assert related > unrelated
    assert unrelated < 0.2
