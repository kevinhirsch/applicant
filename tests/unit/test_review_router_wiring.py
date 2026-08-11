"""Integrate step: the EPIC REVIEW-UX router is registered on the app.

RUX-1/2/3 built ``src/applicant/app/routers/review.py`` but left registration to the
Integrate step (its module WIRING note). This pins that the ``/api/review`` surface is
actually mounted by ``register_routers`` so the review proxy has a live engine to hit.
"""
from __future__ import annotations

from applicant.app.main import create_app


def _registered_paths(app) -> set[str]:
    """All endpoint paths registered on the app.

    This FastAPI build wraps each ``include_router`` in an ``_IncludedRouter`` mount
    whose own ``.path`` is not the endpoint path — the real paths live on its
    ``original_router.routes`` (mirrors ``test_compare_router._registered_paths``).
    """
    paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    return paths


def test_review_router_is_registered():
    app = create_app()
    paths = {p for p in _registered_paths(app) if p.startswith("/api/review")}
    assert paths, "no /api/review routes registered — review router not wired"
    # The RUX-1/2/3 surface: source (RUX-1), the three-way decision (RUX-2), refine (RUX-3).
    assert "/api/review/{application_id}/source" in paths
    assert "/api/review/{application_id}/continue" in paths
    assert "/api/review/{application_id}/save-for-later" in paths
    assert "/api/review/{application_id}/discard" in paths
    assert "/api/review/{application_id}/apply-instruction" in paths
