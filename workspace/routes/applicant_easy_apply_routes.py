# routes/applicant_easy_apply_routes.py
"""Easy Apply assisted-mode proxy (P2-14, road-to-market backlog).

P1-11 already tags a role's built-in quick-apply channel at discovery time and
surfaces it as an "Easy Apply" chip in the digest/Tracker (detection only, zero
automation). This is the next step the owner explicitly scoped for right now:
an ASSISTED-MODE product surface -- a deep link to the real posting, the
candidate's own prepared materials, and a plain checklist -- with real
LIVE-account automation (walking the quick-apply modal on a real, owner-
controlled account) deferred until the owner supplies one for proof runs. The
user drives every action themselves; this proxy adds no engine logic, it only
forwards to the engine's ``/api/setup/easy-apply-consent`` +
``/api/easy-apply/*`` routes.

Safety: the consent screen this backs is a real stop-boundary surface, not
decoration. Both the consent GET/POST *and* the assisted-mode brief GET are
gated by ``require_engine_owner`` (DISC-15/15b) rather than the plain
``require_user`` most setup-config proxies use elsewhere -- the engine is
single-tenant (no owner concept of its own), and consent-recording /
assisted-mode content is exactly the class of safety-relevant surface CLAUDE.md
calls out for the stricter gate: a second, unrelated workspace account must not
be able to read or flip the real owner's consent record, or draw the real
owner's prepared-materials pointer. ``campaign_id`` is validated against THIS
request's own ``list_campaigns()`` fan-out before the brief is forwarded --
the same never-trust-a-caller-supplied-id guard ``applicant_followups_routes.py``
/ ``applicant_tracker_routes.py`` use.

Endpoints (all under ``/api/applicant/easy-apply``):

* ``GET  /consent`` -- whether the consent screen has been accepted.
* ``POST /consent`` -- record acceptance (idempotent).
* ``GET  /{campaign_id}/{posting_id}`` -- the assisted-mode brief (deep link +
  checklist + prepared-materials pointer) for one of the owner's OWN Easy-Apply
  postings. Passes through the engine's own 409 (consent not yet given) / 404
  (posting doesn't exist / isn't Easy-Apply) unchanged.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from src.applicant_engine import (
    ApplicantEngineClient,
    EngineError,
    shared_engine_http_client,
    soft_degrade,
)
from src.auth_helpers import require_engine_owner

logger = logging.getLogger(__name__)


def _require_owner(request: Request) -> str:
    """Require the ENGINE-OWNER account, not just any authenticated user
    (DISC-15/15b) -- see the module docstring for why this surface gets the
    stricter gate rather than the plain ``require_user`` most setup-config
    proxies use."""
    return require_engine_owner(request)


def setup_applicant_easy_apply_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/easy-apply", tags=["applicant-easy-apply"])

    @router.get("/consent")
    async def get_consent(request: Request) -> dict:
        """Whether the assisted-mode consent screen has been accepted yet."""
        _require_owner(request)
        # Ride the shared app-lifetime pool (falls back to a private pool on a
        # bare test app) -- same pattern as applicant_activity/health/portal.
        async with ApplicantEngineClient(client=shared_engine_http_client(request)) as engine:
            try:
                data = await engine.easy_apply_consent_status()
            except EngineError as exc:
                logger.debug("easy-apply: consent status read failed: %s", exc)
                return soft_degrade(exc, {"given": False, "given_at": None})
        return data if isinstance(data, dict) else {"given": False, "given_at": None}

    @router.post("/consent", status_code=201)
    async def give_consent(request: Request) -> dict:
        """Record that the owner read and accepted the consent screen."""
        _require_owner(request)
        async with ApplicantEngineClient(client=shared_engine_http_client(request)) as engine:
            try:
                data = await engine.easy_apply_consent_give()
            except EngineError as exc:
                logger.info("easy-apply: recording consent failed: %s", exc)
                raise HTTPException(status_code=exc.status or 502, detail=str(exc)) from exc
        return data if isinstance(data, dict) else {"given": True, "given_at": None}

    @router.get("/{campaign_id}/{posting_id}")
    async def assist(request: Request, campaign_id: str, posting_id: str) -> dict:
        """The assisted-mode brief for one of the owner's OWN Easy-Apply
        postings (deep link + checklist + prepared-materials pointer).

        ``campaign_id`` is validated against this request's own
        ``list_campaigns()`` fan-out BEFORE the brief is forwarded -- never
        trust a caller-supplied id. The engine's own 409 (consent not yet
        given) / 404 (posting missing/not Easy-Apply) pass straight through.
        """
        _require_owner(request)
        async with ApplicantEngineClient(client=shared_engine_http_client(request)) as engine:
            try:
                campaigns = await engine.list_campaigns()
            except EngineError as exc:
                logger.debug("easy-apply: campaigns read failed: %s", exc)
                raise HTTPException(
                    status_code=503, detail="The Applicant engine is not reachable right now."
                ) from exc
            owned = {
                str(c.get("id"))
                for c in campaigns
                if isinstance(c, dict) and c.get("id")
            } if isinstance(campaigns, list) else set()
            if campaign_id not in owned:
                raise HTTPException(status_code=404, detail="No such job search.")
            try:
                data = await engine.easy_apply_assist(campaign_id, posting_id)
            except EngineError as exc:
                logger.debug(
                    "easy-apply: assist read failed for %s/%s: %s",
                    campaign_id, posting_id, exc,
                )
                raise HTTPException(status_code=exc.status or 502, detail=str(exc)) from exc
        return data if isinstance(data, dict) else {}

    return router
