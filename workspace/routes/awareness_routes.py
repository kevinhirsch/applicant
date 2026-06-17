# routes/awareness_routes.py
"""HTTP API for the proactive Awareness loop (Phase 2, Applicant parity).

Owner-scoped; every endpoint requires the opt-in ``can_use_awareness``
privilege. The background loop itself only runs when ``APPLICANT_AWARENESS`` is
enabled, but trigger CRUD + the manual tick are available whenever a user has
the privilege so they can set up and test triggers.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from src.auth_helpers import get_current_user, require_privilege
from services.awareness.service import AwarenessService

logger = logging.getLogger(__name__)

_service = AwarenessService()


class TriggerCreate(BaseModel):
    name: str
    condition: Optional[dict] = None
    description: str = ""
    channel: str = "ntfy"
    cooldown_seconds: int = 0
    risk_tier: str = "low"
    enabled: bool = True


class TriggerUpdate(BaseModel):
    name: Optional[str] = None
    condition: Optional[dict] = None
    description: Optional[str] = None
    channel: Optional[str] = None
    cooldown_seconds: Optional[int] = None
    risk_tier: Optional[str] = None
    enabled: Optional[bool] = None


class OutcomeIn(BaseModel):
    outcome: str  # useful | dismissed | acted


def setup_awareness_routes() -> APIRouter:
    router = APIRouter()

    @router.get("/api/awareness/triggers")
    async def list_triggers(request: Request):
        require_privilege(request, "can_use_awareness")
        owner = get_current_user(request)
        return {"triggers": _service.list_triggers(owner)}

    @router.post("/api/awareness/triggers")
    async def create_trigger(request: Request, body: TriggerCreate):
        require_privilege(request, "can_use_awareness")
        owner = get_current_user(request)
        return _service.create_trigger(
            owner, body.name, condition=body.condition, description=body.description,
            channel=body.channel, cooldown_seconds=body.cooldown_seconds,
            risk_tier=body.risk_tier, enabled=body.enabled,
        )

    @router.patch("/api/awareness/triggers/{trigger_id}")
    async def update_trigger(request: Request, trigger_id: str, body: TriggerUpdate):
        require_privilege(request, "can_use_awareness")
        owner = get_current_user(request)
        t = _service.update_trigger(owner, trigger_id, **body.dict(exclude_unset=True))
        if t is None:
            raise HTTPException(404, "trigger not found")
        return t

    @router.delete("/api/awareness/triggers/{trigger_id}")
    async def delete_trigger(request: Request, trigger_id: str):
        require_privilege(request, "can_use_awareness")
        owner = get_current_user(request)
        if not _service.delete_trigger(owner, trigger_id):
            raise HTTPException(404, "trigger not found")
        return {"ok": True}

    @router.get("/api/awareness/notifications")
    async def list_notifications(request: Request, limit: int = 50):
        require_privilege(request, "can_use_awareness")
        owner = get_current_user(request)
        return {"notifications": _service.list_notifications(owner, limit=limit)}

    @router.post("/api/awareness/notifications/{notif_id}/outcome")
    async def set_outcome(request: Request, notif_id: str, body: OutcomeIn):
        require_privilege(request, "can_use_awareness")
        owner = get_current_user(request)
        if not _service.record_outcome(owner, notif_id, body.outcome):
            raise HTTPException(404, "notification not found")
        return {"ok": True}

    @router.post("/api/awareness/tick")
    async def manual_tick(request: Request):
        """Run one tick now (for testing a configured trigger set)."""
        require_privilege(request, "can_use_awareness")
        owner = get_current_user(request)
        return await _service.run_tick(owner)

    return router
