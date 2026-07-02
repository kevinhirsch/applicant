# routes/applicant_results_routes.py
"""Results surface ↔ engine bridge (surfacing-only, NON-admin).

The engine already computes, per campaign, a plain-language read-model of the
outcome/learning it has accrued: the conversion funnel (matched → approved →
submitted), each discovery source's own funnel ranked by how well it converts,
and the learned "what converts for you" role signature. Today that data is only
reachable through the ADMIN-gated Activity/Debug surface — the #1 audit finding
is that a regular owner has no first-class window onto their own results.

This proxy SURFACES that same data in the front-door as a NON-admin, owner-scoped
"Results" surface. It adds no engine logic and creates no new engine state — it is
a thin, auth-protected proxy over :class:`src.applicant_engine.ApplicantEngineClient`
(the browser never reaches the engine directly), modelled exactly on the sibling
``applicant_activity_routes.py``:

* the owner is authenticated by the front-door (``require_user``); the engine's own
  gates (the LLM/setup gate on the learning read) still apply and are forwarded
  honestly as a GATED state (never weakened);
* scoping mirrors the Pending-Actions Portal: NOT gated behind one active campaign —
  the proxy resolves the owner's campaign(s) via ``list_campaigns()`` and returns the
  first/most-relevant one's results; and
* every engine failure degrades soft — an unreachable engine returns
  ``engine_available: false`` with a well-formed empty body, a setup gate returns
  ``gated: true`` with the engine's own message, and no campaign / no data yet
  returns ``has_data: false`` — so the surface renders its designed empty state
  instead of throwing.

The engine data source is ``GET /api/admin/learning/{campaign_id}`` (surfaced by
:meth:`ApplicantEngineClient.admin_learning`). It is plain-language, secret-free,
and built purely from persisted learning state. Note: that endpoint is gated at the
ENGINE layer behind the LLM/setup gate (not an *admin* gate) — the workspace still
authenticates the owner and proxies it exactly like every other owner-scoped
surface. The engine's learning summary funnel currently ends at "submitted"; there
is no campaign-level interview/offer aggregate exposed yet (see the INTEGRATION
SPEC note), so those stages degrade to a designed "not tracked yet" state rather
than fabricated numbers.

Endpoint (one prefix, ``/api/applicant/results``):

* ``GET /api/applicant/results`` — the funnel + per-source conversion + the learned
  "what converts for you" signature + the decline-reason word rollup (words most
  common in the owner's OWN mandatory decline feedback, FR-FB-1 — grounded in
  their own language, never a guessed taxonomy) for the owner's first campaign.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require an authenticated owner (the global gate also enforces this)."""
    return require_user(request)


def _campaign_label(campaign: dict) -> str:
    """Best human label for a campaign dict from the engine."""
    return str(campaign.get("name") or campaign.get("id") or "")


async def _owner_campaigns(engine: ApplicantEngineClient) -> "list[dict] | dict":
    """Resolve the owner's campaigns, or a soft-degrade payload on failure.

    Mirrors ``applicant_activity_routes._owner_campaigns``: on success returns a
    ``list`` (possibly empty — "online, no campaign yet"); on an
    :class:`EngineError` returns a ``dict`` built by :func:`soft_degrade`, which
    distinguishes a client-correctable GATE (``gated: true`` + the engine's
    message, ``engine_available: true``) from a genuine TRANSPORT-OFFLINE
    (``engine_available: false``). Callers detect the failure with
    ``isinstance(result, list)`` and return the dict as-is.
    """
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        logger.debug("results: campaigns read failed (status=%s): %s", exc.status, exc)
        return soft_degrade(exc, {"has_data": False})
    return [c for c in campaigns if isinstance(c, dict)] if isinstance(campaigns, list) else []


def _first_campaign(campaigns: list[dict]) -> Optional[tuple[str, str]]:
    """The first campaign's ``(id, label)`` if any, else ``None``."""
    for campaign in campaigns:
        cid = campaign.get("id")
        if cid:
            return str(cid), _campaign_label(campaign)
    return None


def _has_any_volume(summary: dict, sources: list) -> bool:
    """True when there is any real result volume to render.

    A brand-new user has a reachable engine and a campaign but zero learning
    volume — that must read as the designed empty state, not a chart of zeros. We
    treat "has data" as any matched/approved/submitted count > 0 across the funnel.
    """
    if not isinstance(summary, dict):
        return bool(sources)
    for key in ("total_matched", "total_approved", "total_submitted"):
        try:
            if int(summary.get(key, 0) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def setup_applicant_results_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/results", tags=["applicant-results"])

    @router.get("")
    async def results(request: Request) -> dict:
        """The owner's results: funnel + per-source conversion + learned signature.

        Proxies the engine's plain-language learning summary for the owner's first
        campaign: the overall funnel (``summary`` — matched/approved/submitted),
        each source's own funnel ranked by conversion (``sources``), the roles that
        actually convert (``converting_roles``), the decline-reason word rollup
        (``decline_reasons``), and the exploration budget. Degrades
        soft: an unreachable engine returns ``engine_available: false``; a setup gate
        returns ``gated: true`` with the engine's message; no campaign or no volume
        yet returns ``has_data: false`` with a well-formed empty body so the surface
        renders its designed empty state.
        """
        _require_user(request)
        empty = {
            "summary": {},
            "sources": [],
            "converting_roles": [],
            "decline_reasons": [],
        }
        async with ApplicantEngineClient() as engine:
            campaigns = await _owner_campaigns(engine)
            if not isinstance(campaigns, list):
                # Gate or transport-offline dict from soft_degrade — forward as-is
                # with the empty result scaffold so the UI has a well-formed body.
                return {**empty, **campaigns}
            first = _first_campaign(campaigns)
            if first is None:
                return {
                    **empty,
                    "engine_available": True,
                    "has_data": False,
                }
            cid, cname = first
            try:
                data = await engine.admin_learning(cid)
            except EngineError as exc:
                logger.debug("results: learning fetch failed for %s: %s", cid, exc)
                # A setup/LLM gate on the learning read is honest GATED state, not
                # "offline". soft_degrade classifies it and forwards the message.
                degraded = soft_degrade(exc, {**empty, "has_data": False})
                degraded.setdefault("campaign_id", cid)
                degraded["campaign_name"] = cname
                return degraded

        payload = data if isinstance(data, dict) else {}
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
        sources = [s for s in sources if isinstance(s, dict)]
        roles = payload.get("converting_roles") if isinstance(payload.get("converting_roles"), list) else []
        decline_reasons = (
            payload.get("decline_reasons") if isinstance(payload.get("decline_reasons"), list) else []
        )
        decline_reasons = [
            r for r in decline_reasons if isinstance(r, dict) and r.get("reason")
        ]

        out = {
            "engine_available": True,
            "has_data": _has_any_volume(summary, sources),
            "campaign_id": payload.get("campaign_id") or cid,
            "campaign_name": cname,
            "summary": summary,
            "sources": sources,
            "converting_roles": [r for r in roles if r],
            "converting_samples": payload.get("converting_samples"),
            "exploration_budget": payload.get("exploration_budget"),
            # Words most common in the user's own decline feedback (FR-FB-1), ranked
            # by count; [] when nothing declined yet — surfacing-only, no new data.
            "decline_reasons": decline_reasons,
        }
        return out

    return router
