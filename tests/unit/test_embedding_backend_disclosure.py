"""``LocalEmbedding.describe()`` — plain-language backend disclosure (dark-engine
audit #79).

``LocalEmbedding`` is a deterministic hashing-trick backend (no model
download); nothing previously told the operator that memory/dedup matching
runs on this basic offline signal rather than a trained model. This proves
the disclosure is honest (never claims ``model_backed``) and stable (the
``/api/admin/embedding-backend`` route reads these exact fields — see
``tests/unit/test_admin_captcha_capacity_embedding_routes.py``).
"""

from __future__ import annotations

from applicant.adapters.embedding.local_embedding import LocalEmbedding


def test_describe_reports_the_hashing_trick_backend_honestly():
    info = LocalEmbedding().describe()
    assert info["backend"] == "hashing-trick"
    assert info["quality_tier"] == "basic"
    assert info["model_backed"] is False
    assert isinstance(info["detail"], str) and info["detail"]


def test_describe_never_claims_model_backed():
    """A basic offline backend must never advertise itself as model-backed —
    that would mislead the operator about semantic-match quality."""
    info = LocalEmbedding().describe()
    assert info["model_backed"] is False
