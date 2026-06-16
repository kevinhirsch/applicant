"""Embedding contract against the LocalEmbedding adapter (NFR-LOCAL-1).

Architecture §6: every adapter ships a contract test. Proves deterministic, offline,
no-download embeddings with a usable similarity signal in [0, 1].
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.ports.driven.embedding import EmbeddingPort


@pytest.mark.contract
class TestLocalEmbeddingContract:
    @pytest.fixture
    def adapter(self) -> LocalEmbedding:
        return LocalEmbedding()

    def test_satisfies_port_protocol(self, adapter):
        assert isinstance(adapter, EmbeddingPort)

    def test_embed_one_vector_per_text(self, adapter):
        vecs = adapter.embed(["hello world", "another", ""])
        assert len(vecs) == 3
        assert all(isinstance(v, list) and v for v in vecs)
        # fixed dimensionality
        assert len({len(v) for v in vecs}) == 1

    def test_embed_is_deterministic(self, adapter):
        assert adapter.embed(["repeatable text"]) == adapter.embed(["repeatable text"])

    def test_similarity_in_unit_range(self, adapter):
        for a, b in [("x", "y"), ("same", "same"), ("", "")]:
            s = adapter.similarity(a, b)
            assert 0.0 <= s <= 1.0

    def test_identical_text_is_maximally_similar(self, adapter):
        assert adapter.similarity("backend engineer", "backend engineer") == pytest.approx(1.0)

    def test_overlap_beats_disjoint(self, adapter):
        related = adapter.similarity(
            "senior python backend engineer fastapi",
            "python backend engineer building fastapi services",
        )
        unrelated = adapter.similarity(
            "senior python backend engineer fastapi",
            "pastry chef bakery croissant",
        )
        assert related > unrelated

    def test_empty_vs_nonempty_is_zero(self, adapter):
        assert adapter.similarity("", "nonempty") == 0.0
