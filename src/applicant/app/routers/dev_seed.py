"""Dev/demo seed router (audit §6 quick-win #49) — env-gated, OFF by default.

The exhaustive product audit found that the front-door "opens every surface
empty" — no seed/demo data path exists, so the trust-core daily loop (digest ->
redline -> approve -> takeover -> submit), the populated Portal, and the
post-submission tracker can never be rendered or exercised end to end. This
router is the fix: it inserts (or resets) the coherent demo dataset built by
``applicant.application.services.dev_seed`` through the REAL repositories, so
the surfaces render it exactly as they would for a genuine user.

HARD GATE: every route on this router 404s unless ``APPLICANT_ALLOW_SEED=1`` is
set in the process environment, checked FRESH on every request (not cached at
import/startup) via ``_seed_enabled()``. With the var unset — the default,
including every production deploy — this router behaves as if it were never
registered: no route in this file is reachable. This is a dev/demo affordance
only; it is deliberately NOT gated behind ``require_llm_configured`` (a fresh,
unconfigured instance is exactly when a demo seed is wanted) and it is
intentionally NOT reachable from the white-labeled workspace front-door — it is
an operator/playtest tool, invoked directly against the internal ``api``
service (mirrors ``scripts/seed_demo.py``, its CLI sibling, which shares this
module's pure builders + persist/purge functions).
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.deps import get_storage
from applicant.application.services import dev_seed


def _seed_enabled() -> bool:
    """``True`` only when ``APPLICANT_ALLOW_SEED=1`` is set right now.

    Read directly from ``os.environ`` (not the cached ``Settings``/``get_settings``
    singleton) so flipping the env var takes effect immediately, and so nothing
    about this gate can be baked in at import/startup time.
    """
    return os.environ.get("APPLICANT_ALLOW_SEED") == "1"


def require_seed_enabled() -> None:
    """FastAPI dependency: 404 (route effectively doesn't exist) when disabled.

    A 404 rather than a 403 is deliberate — this must read to a caller (and to
    anything probing routes) as "this endpoint does not exist", not as "it
    exists but you're not allowed", so a production deploy carries no visible
    trace of a seed affordance. Applied at the ROUTER level (not per-route) so
    every current and future route on this router inherits the gate.
    """
    if not _seed_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(
    prefix="/api/dev/seed",
    tags=["dev-seed"],
    dependencies=[Depends(require_seed_enabled)],
)


class SeedIn(BaseModel):
    campaign_id: str = dev_seed.DEMO_CAMPAIGN_ID


class SeedResetIn(BaseModel):
    campaign_id: str = dev_seed.DEMO_CAMPAIGN_ID


@router.post("")
def seed(body: SeedIn = SeedIn(), storage=Depends(get_storage)) -> dict:
    """Insert (or replace, on re-seed) the coherent demo dataset for one campaign.

    Every row is written through the real repositories (``dev_seed.persist``),
    so it renders on the front-door exactly as genuine data would: a campaign,
    seven varied postings, applications spanning digest/redline/final-approval/
    blocked/tracker states, a résumé variant + material + open revision
    session, a submission snapshot, outcome events, and six heterogeneous
    Portal pending-actions. Idempotent — every repo ``add`` upserts by id, so
    re-seeding replaces rather than duplicates the demo rows.
    """
    bundle = dev_seed.build_demo_bundle(body.campaign_id)
    counts = dev_seed.persist(storage, bundle)
    return {
        "seeded": True,
        "campaign_id": body.campaign_id,
        "counts": counts,
        "pending_action_kinds": sorted({a.kind for a in bundle.pending_actions}),
    }


@router.post("/reset")
def reset(body: SeedResetIn = SeedResetIn(), storage=Depends(get_storage)) -> dict:
    """Purge the demo campaign (reuses the existing #363 purge-campaign cascade).

    Idempotent: resetting an already-absent (or never-seeded) campaign id
    reports zero counts rather than raising, so this is safe to call
    unconditionally before a re-seed.
    """
    counts = dev_seed.purge(storage, body.campaign_id)
    return {"reset": True, "campaign_id": body.campaign_id, "counts": counts}
