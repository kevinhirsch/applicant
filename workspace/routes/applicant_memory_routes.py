# routes/applicant_memory_routes.py
"""Workspace-side proxy for the engine's attribute cloud + conversion learning.

This is the **Memory / Profile** lane of the Stage-2 integration. The workspace
Brain modal grows a "Profile" tab that lets the owner manage the engine's
*attribute cloud* (the structured facts the engine pre-fills into job
applications) and review what the engine has *learned* on its own (the resume
conversion choice, plus AI-suggested attributes awaiting confirmation).

Everything here is a thin proxy over :class:`src.applicant_engine.ApplicantEngineClient`:

* the engine is the source of truth — we never persist attribute/learning state
  in the workspace DB, we just forward to ``http://api:8000`` and reshape the
  JSON for the front-end;
* every engine failure surfaces through the typed :class:`EngineError`, which we
  translate into a clean HTTP response so a wired UI surface degrades gracefully
  (a down engine reports ``engine_available: false`` rather than 500ing);
* writes require the existing ``can_manage_memory`` privilege, matching the rest
  of the Brain modal (memories / skills / entities). Reads require a logged-in
  user. User management / auth is untouched.

The engine is per-campaign. The workspace resolves a campaign once (an explicit
``campaign_id`` query/body field wins; otherwise the engine's first campaign) so
the front-end never has to know about campaign plumbing.

Mounted in ``app.py`` next to the other Applicant route includes. The section is
greyed by the 2.0 feature-activation layer until the engine's ``attribute_editor``
/ ``criteria_editor`` surfaces go live, so these endpoints only do real work once
the engine is configured.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_privilege, require_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request bodies (workspace-facing; reshaped onto the engine's contract).
# ---------------------------------------------------------------------------


class AddAttributeIn(BaseModel):
    name: str
    value: str
    aliases: list[str] = []
    is_integral: bool = False
    is_sensitive: bool = False
    confirm: bool = False
    campaign_id: Optional[str] = None


class AiAddAttributeIn(BaseModel):
    name: str
    value: str
    confirm: bool = False
    campaign_id: Optional[str] = None


class BindAttributeIn(BaseModel):
    site_key: str
    field_selector: str
    attribute_id: Optional[str] = None
    shared: bool = False
    metadata: dict = {}
    campaign_id: Optional[str] = None


class AcquireMissingIn(BaseModel):
    name: str
    value: str
    confirm: bool = False
    campaign_id: Optional[str] = None


class PreviewLearningIn(BaseModel):
    source: str = ""
    campaign_id: Optional[str] = None


class EditCriteriaIn(BaseModel):
    titles: Optional[list[str]] = None
    locations: Optional[list[str]] = None
    work_modes: Optional[list[str]] = None
    keywords: Optional[list[str]] = None
    salary_floor: Optional[int] = None
    human_readable: Optional[str] = None
    confirm: bool = False
    clear_learned: bool = False
    campaign_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def _raise_engine_http(exc: EngineError) -> None:
    """Translate an :class:`EngineError` into an HTTPException for the front-end.

    * a timeout / connection failure (no ``status``) -> 503 (engine offline);
    * an engine HTTP status is forwarded verbatim so the UI can react to the
      engine's own gates — notably 409 (confirmation required, FR-FB-3) and 422
      (sensitive-field violation, FR-ATTR-6).
    """
    if exc.status is None:
        raise HTTPException(503, "The Applicant engine is unavailable right now.") from exc
    detail = exc.detail if exc.detail is not None else exc.message
    raise HTTPException(exc.status, detail) from exc


async def _resolve_campaign(engine: ApplicantEngineClient, explicit: Optional[str]) -> str:
    """Resolve the campaign to operate on.

    An explicit id (query/body) always wins. Otherwise we take the engine's first
    campaign. Raises 409 if there is no campaign yet (onboarding not started) so
    the UI can prompt the user instead of sending requests to a missing campaign.

    The campaign lookup itself talks to the engine, so a down/unreachable engine
    surfaces here as an :class:`EngineError`. Translate it through the same clean
    HTTP mapping every other engine call uses (503 / engine status) so a resolve
    on an offline engine degrades gracefully instead of escaping as a raw 500.
    """
    if explicit:
        return explicit
    try:
        campaigns = await engine.list_campaigns()
    except EngineError as exc:
        _raise_engine_http(exc)
    if isinstance(campaigns, list) and campaigns:
        first = campaigns[0]
        cid = first.get("id") if isinstance(first, dict) else None
        if cid:
            return str(cid)
    raise HTTPException(409, "No Applicant campaign exists yet. Finish onboarding first.")


def setup_applicant_memory_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/memory", tags=["applicant-memory"])

    # -- status / activation ------------------------------------------------

    @router.get("/status")
    async def memory_status(request: Request, campaign_id: Optional[str] = None) -> dict:
        """Lightweight readiness probe for the Profile tab.

        Reports whether the engine is reachable, the resolved campaign, and how
        many attributes / what learning state exist — enough for the front-end to
        decide whether to render the tab's contents or an "engine not ready" note.
        Never raises on a down/unconfigured engine: it just reports ``ready: false``.
        """
        require_user(request)
        async with ApplicantEngineClient() as engine:
            if not await engine.engine_available():
                return {"ready": False, "engine_available": False, "campaign_id": None}
            try:
                cid = await _resolve_campaign(engine, campaign_id)
            except HTTPException:
                return {"ready": False, "engine_available": True, "campaign_id": None}
            attr_count = None
            learned = None
            try:
                attrs = await engine.list_attributes(cid)
                if isinstance(attrs, dict):
                    attr_count = len(attrs.get("items", []) or [])
            except EngineError:
                pass
            try:
                conv = await engine.conversion_engine(cid)
                if isinstance(conv, dict):
                    learned = conv.get("engine")
            except EngineError:
                pass
            return {
                "ready": True,
                "engine_available": True,
                "campaign_id": cid,
                "attribute_count": attr_count,
                "learned_engine": learned,
            }

    # -- attribute cloud ----------------------------------------------------

    @router.get("/attributes")
    async def list_attributes(request: Request, campaign_id: Optional[str] = None) -> dict:
        """The campaign's attribute cloud (the facts the engine pre-fills)."""
        require_user(request)
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, campaign_id)
            try:
                data = await engine.list_attributes(cid)
            except EngineError as exc:
                _raise_engine_http(exc)
            return data if isinstance(data, dict) else {"campaign_id": cid, "items": []}

    @router.post("/attributes")
    async def add_attribute(request: Request, body: AddAttributeIn) -> dict:
        """Add (or update) an attribute by hand.

        Forwards the engine's confirmation gate (409) and sensitive-field policy
        (422) so the UI can ask the user to confirm an integral change or supply a
        sensitive value explicitly.
        """
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, body.campaign_id)
            payload = {
                "campaign_id": cid,
                "name": body.name,
                "value": body.value,
                "aliases": body.aliases,
                "is_integral": body.is_integral,
                "is_sensitive": body.is_sensitive,
                "confirm": body.confirm,
            }
            try:
                return await engine.add_attribute(payload)
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.post("/attributes/ai-add")
    async def ai_add_attribute(request: Request, body: AiAddAttributeIn) -> dict:
        """Confirm/commit an AI-suggested attribute (FR-ATTR-4)."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, body.campaign_id)
            payload = {
                "campaign_id": cid,
                "name": body.name,
                "value": body.value,
                "confirm": body.confirm,
            }
            try:
                return await engine.ai_add_attribute(payload)
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.delete("/attributes/{attribute_id}")
    async def delete_attribute(
        request: Request, attribute_id: str, campaign_id: Optional[str] = None
    ) -> dict:
        """Remove a stored attribute by hand (FR-ATTR-3)."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, campaign_id)
            try:
                return await engine.delete_attribute(cid, attribute_id)
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.post("/attributes/bind")
    async def bind_attribute(request: Request, body: BindAttributeIn) -> dict:
        """Pin an attribute to a specific application-form field (FR-ATTR-2)."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, body.campaign_id)
            payload = {
                "site_key": body.site_key,
                "field_selector": body.field_selector,
                "attribute_id": body.attribute_id,
                "campaign_id": cid,
                "shared": body.shared,
                "metadata": body.metadata,
            }
            try:
                return await engine.bind_attribute(payload)
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.post("/attributes/acquire-missing")
    async def acquire_missing(request: Request, body: AcquireMissingIn) -> dict:
        """Supply a detail the engine flagged as missing, resuming any stalled
        application that was blocked on it (FR-ATTR-5)."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, body.campaign_id)
            payload = {
                "campaign_id": cid,
                "name": body.name,
                "value": body.value,
                "confirm": body.confirm,
            }
            try:
                return await engine.acquire_missing_attribute(payload)
            except EngineError as exc:
                _raise_engine_http(exc)

    # -- conversion learning (what the engine learned) ----------------------

    @router.get("/learning")
    async def learning_state(request: Request, campaign_id: Optional[str] = None) -> dict:
        """The current resume-conversion engine choice the engine has settled on."""
        require_user(request)
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, campaign_id)
            try:
                return await engine.conversion_engine(cid)
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.post("/learning/preview")
    async def learning_preview(request: Request, body: PreviewLearningIn) -> dict:
        """Build the conversion preview the user accepts/rejects (FR-RESUME-3a)."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, body.campaign_id)
            try:
                return await engine.conversion_preview(cid, body.source)
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.post("/learning/accept")
    async def learning_accept(request: Request, campaign_id: Optional[str] = None) -> dict:
        """Accept what the engine learned (LaTeX becomes the primary engine)."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, campaign_id)
            try:
                return await engine.conversion_accept(cid)
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.post("/learning/reject")
    async def learning_reject(request: Request, campaign_id: Optional[str] = None) -> dict:
        """Reject what the engine learned (fall back to the docx engine)."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, campaign_id)
            try:
                return await engine.conversion_reject(cid)
            except EngineError as exc:
                _raise_engine_http(exc)

    # -- criteria (adjacent: what roles the engine targets) -----------------

    @router.get("/criteria")
    async def get_criteria(request: Request, campaign_id: Optional[str] = None) -> dict:
        """The campaign's search criteria, including any learned adjustments."""
        require_user(request)
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, campaign_id)
            try:
                return await _criteria_get(engine, cid)
            except EngineError as exc:
                _raise_engine_http(exc)

    @router.put("/criteria")
    async def edit_criteria(request: Request, body: EditCriteriaIn) -> dict:
        """Edit the campaign's criteria (integral edits route through the 409 gate)."""
        require_privilege(request, "can_manage_memory")
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, body.campaign_id)
            changes = body.model_dump(exclude_none=True, exclude={"campaign_id"})
            try:
                return await _criteria_put(engine, cid, changes)
            except EngineError as exc:
                _raise_engine_http(exc)

    # -- learned converting-role signature (what the engine learned converts) --

    @router.get("/signature")
    async def converting_signature(request: Request, campaign_id: Optional[str] = None) -> dict:
        """The learned converting-role signature (per-facet digest of what converts).

        A transparent, read-only view of the bias the engine has learned from the
        roles that actually convert, so the user can see it next to the learned
        criteria adjustments (and override the criteria if they disagree).
        """
        require_user(request)
        async with ApplicantEngineClient() as engine:
            cid = await _resolve_campaign(engine, campaign_id)
            try:
                return await _signature_get(engine, cid)
            except EngineError as exc:
                _raise_engine_http(exc)

    return router


# ---------------------------------------------------------------------------
# Criteria helpers.
#
# Criteria are on the engine client's contract as "getters/setters as needed"
# but no dedicated client method ships yet, and the shared client is off-limits
# to this lane. Rather than duplicate httpx error handling, we issue the two
# criteria requests through the client's own request seam (the same path every
# client method uses), so tests still mock a single transport and every failure
# still becomes a typed EngineError. These map 1:1 to the engine ``criteria``
# router (GET/PUT /api/criteria/{campaign_id}).
# ---------------------------------------------------------------------------


async def _criteria_get(engine: ApplicantEngineClient, campaign_id: str) -> Any:
    return await engine._request("GET", f"/api/criteria/{campaign_id}")


async def _criteria_put(engine: ApplicantEngineClient, campaign_id: str, changes: dict) -> Any:
    return await engine._request("PUT", f"/api/criteria/{campaign_id}", json=changes)


async def _signature_get(engine: ApplicantEngineClient, campaign_id: str) -> Any:
    """Read the learned converting-role signature (criteria router, FR-LEARN-5)."""
    return await engine._request("GET", f"/api/criteria/{campaign_id}/signature")
