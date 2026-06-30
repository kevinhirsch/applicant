# routes/applicant_routes.py
"""Applicant integration routes — the Stage-2 FOUNDATION endpoint.

Exposes ``GET /api/applicant/features``: the derived feature-state for the
workspace surfaces that are mapped to the Applicant engine. The frontend reads
this on boot (alongside the existing ``/api/auth/features``) to activate those
sections progressively — locked until the engine is configured, ``disabled`` for
present-but-unbacked surfaces (Compare).

This is intentionally read-only and additive: it does not touch auth, user
management, or the workspace's own ``/api/auth/features`` mechanism. The four
Stage-2 lanes mount their own engine-wired routers on top of this; the contract
in ``workspace/APPLICANT_INTEGRATION.md`` keeps their files disjoint.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request

from src.applicant_features import compute_features
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


def setup_applicant_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant", tags=["applicant"])

    @router.get("/features")
    async def applicant_features(request: Request) -> dict:
        """Derived Applicant section state (engine setup status + dormant registry).

        Auth-protected like sibling proxy routes: engine configuration reveals
        which capabilities are active (LLM, channels, onboarding) and leaks
        engine metadata to any unauthenticated caller. ``compute_features`` is
        sync (short httpx calls to the in-network engine) so we run it in a
        threadpool to avoid blocking the event loop, and it never raises.
        """
        require_user(request)
        try:
            return await asyncio.to_thread(compute_features)
        except Exception as exc:  # defensive: the UI must always get a payload
            logger.warning("applicant features computation failed: %s", exc)
            return {"engine_available": False, "engine_url": "", "sections": {}}

    return router
