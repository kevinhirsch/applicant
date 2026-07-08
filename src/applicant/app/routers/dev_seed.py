"""Dev/demo seed router (audit §6 quick-win #49) — env-gated, OFF by default.

The exhaustive product audit found that the front-door "opens every surface
empty" — no seed/demo data path exists, so the trust-core daily loop (digest ->
redline -> approve -> takeover -> submit), the populated Portal, and the
post-submission tracker can never be rendered or exercised end to end. This
router is the fix: it inserts (or resets) the coherent demo dataset built by
``applicant.application.services.dev_seed`` through the REAL repositories, so
the surfaces render it exactly as they would for a genuine user.

HARD GATE: every route on this router 404s unless ``DEMO_MODE=1`` (back-compat
alias: ``APPLICANT_ALLOW_SEED=1``) is set in the process environment, checked
FRESH on every request (not cached at import/startup) via ``_seed_enabled()``.
With the var unset — the default, including every production deploy — this
router behaves as if it were never registered: no route in this file is
reachable. This is a dev/demo affordance only; it is deliberately NOT gated
behind ``require_llm_configured`` (a fresh, unconfigured instance is exactly
when a demo seed is wanted). The seed/reset are invoked directly against the
internal ``api`` service (mirrors ``scripts/seed_demo.py``, its CLI sibling,
which shares this module's pure builders + persist/purge functions); the
white-labeled workspace front-door reaches the *status* + *reset* endpoints
through its own ``DEMO_MODE``-gated, owner-scoped proxy so the "Demo data"
banner + one-click "Clear demo data" affordance can render.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.deps import get_onboarding_service, get_setup_service, get_storage
from applicant.application.services import dev_seed
from applicant.core.ids import CampaignId


def _seed_enabled() -> bool:
    """``True`` only when ``DEMO_MODE=1`` (or the alias ``APPLICANT_ALLOW_SEED=1``)
    is set right now.

    Read directly from ``os.environ`` (not the cached ``Settings``/``get_settings``
    singleton) so flipping the env var takes effect immediately, and so nothing
    about this gate can be baked in at import/startup time. ``DEMO_MODE`` is the
    canonical name; ``APPLICANT_ALLOW_SEED`` is kept as a back-compat alias so the
    existing CLI/operator invocation keeps working.
    """
    return (
        os.environ.get("DEMO_MODE") == "1"
        or os.environ.get("APPLICANT_ALLOW_SEED") == "1"
    )


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
def seed(
    body: SeedIn = SeedIn(),
    storage=Depends(get_storage),
    setup_service=Depends(get_setup_service),
    onboarding_service=Depends(get_onboarding_service),
) -> dict:
    """Insert (or replace, on re-seed) the coherent demo dataset for one campaign.

    Every row is written through the real repositories (``dev_seed.persist``),
    so it renders on the front-door exactly as genuine data would: a campaign,
    seven varied postings, applications spanning digest/redline/final-approval/
    blocked/tracker states, a résumé variant + material + open revision
    session, a submission snapshot, outcome events, and six heterogeneous
    Portal pending-actions. Idempotent — every repo ``add`` upserts by id, so
    re-seeding replaces rather than duplicates the demo rows.

    Also opens the two setup gates when they aren't already satisfied, so the
    seeded surfaces actually render instead of 409'ing — the seed's whole point
    is an operable end-to-end demo:

    * ``ensure_demo_llm`` opens the LLM gate (``require_llm_configured``) so most
      read surfaces (Portal, tracker, learning) render.
    * ``ensure_demo_apply_ready`` writes the demo campaign's base-résumé intake so
      the hard apply-gate (``require_automated_work``, behind which the digest
      sits) opens too.

    Both are non-destructive: a real, already-configured LLM / a campaign that is
    already apply-ready is left untouched.
    """
    llm_gate_opened = dev_seed.ensure_demo_llm(setup_service)
    bundle = dev_seed.build_demo_bundle(body.campaign_id)
    counts = dev_seed.persist(storage, bundle)
    # After the campaign row exists, satisfy the apply-gate (base-résumé intake).
    apply_gate_opened = dev_seed.ensure_demo_apply_ready(onboarding_service, body.campaign_id)
    return {
        "seeded": True,
        "campaign_id": body.campaign_id,
        "counts": counts,
        "llm_gate_opened": llm_gate_opened,
        "apply_gate_opened": apply_gate_opened,
        "pending_action_kinds": sorted({a.kind for a in bundle.pending_actions}),
    }


@router.get("/status")
def status(
    campaign_id: str = dev_seed.DEMO_CAMPAIGN_ID,
    storage=Depends(get_storage),
) -> dict:
    """Report whether the demo dataset is currently loaded (front-door banner).

    ``demo_active`` is ``True`` iff the demo campaign row exists — the single,
    stable anchor everything else hangs off. Reachable only under ``DEMO_MODE``
    (the router gate), so the front-door treats a 404 here as "not in demo
    mode" and simply hides the banner. Returns a light per-store count so the
    banner can show "N demo rows loaded" without loading the whole dataset.
    """
    campaign = storage.campaigns.get(CampaignId(campaign_id))
    demo_active = campaign is not None
    counts: dict[str, int] = {}
    if demo_active:
        counts = {
            "postings": len(storage.postings.list_for_campaign(CampaignId(campaign_id))),
            "applications": len(
                storage.applications.list_for_campaign(CampaignId(campaign_id))
            ),
            "pending_actions": len(
                storage.pending_actions.list_open(CampaignId(campaign_id))
            ),
        }
    return {"demo_active": demo_active, "campaign_id": campaign_id, "counts": counts}


@router.post("/reset")
def reset(body: SeedResetIn = SeedResetIn(), storage=Depends(get_storage)) -> dict:
    """Purge the demo campaign (reuses the existing #363 purge-campaign cascade).

    Idempotent: resetting an already-absent (or never-seeded) campaign id
    reports zero counts rather than raising, so this is safe to call
    unconditionally before a re-seed.
    """
    counts = dev_seed.purge(storage, body.campaign_id)
    return {"reset": True, "campaign_id": body.campaign_id, "counts": counts}
