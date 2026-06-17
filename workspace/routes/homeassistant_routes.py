# routes/homeassistant_routes.py
"""HTTP API for Home Assistant control (Phase 4, Applicant parity).

Owner-scoped; every endpoint requires the opt-in ``can_control_home``
privilege. State-changing calls are constrained to the user's entity allowlist
and, when the risk policy is enforced (``APPLICANT_RISK_POLICY``), require an
explicit ``confirm`` because ``ha_call_service`` is classified HIGH risk.
The agent reaches these via the existing ``app_api`` loopback tool.
"""

import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from src.auth_helpers import get_current_user, require_privilege
from src import policy
from services.homeassistant.service import (
    HomeAssistantConfigStore,
    HomeAssistantClient,
    HomeAssistantError,
)

logger = logging.getLogger(__name__)

_store = HomeAssistantConfigStore()
_client = HomeAssistantClient(_store)


class HAConfig(BaseModel):
    base_url: Optional[str] = None
    token: Optional[str] = None
    enabled: Optional[bool] = None
    allowlist: Optional[List[str]] = None


class HACall(BaseModel):
    domain: str
    service: str
    entity_id: str
    data: Optional[Dict[str, Any]] = None
    confirm: bool = False


def setup_homeassistant_routes() -> APIRouter:
    router = APIRouter()

    @router.get("/api/homeassistant/config")
    async def get_config(request: Request):
        require_privilege(request, "can_control_home")
        owner = get_current_user(request)
        return _store.get(owner) or {"enabled": False, "allowlist": [], "token_set": False}

    @router.put("/api/homeassistant/config")
    async def set_config(request: Request, body: HAConfig):
        require_privilege(request, "can_control_home")
        owner = get_current_user(request)
        return _store.set(owner, base_url=body.base_url, token=body.token,
                          enabled=body.enabled, allowlist=body.allowlist)

    @router.get("/api/homeassistant/states")
    async def list_states(request: Request):
        require_privilege(request, "can_control_home")
        owner = get_current_user(request)
        try:
            return {"states": await _client.get_states(owner)}
        except HomeAssistantError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f"Home Assistant request failed: {e}")

    @router.post("/api/homeassistant/call")
    async def call_service(request: Request, body: HACall):
        require_privilege(request, "can_control_home")
        owner = get_current_user(request)
        # HIGH-risk gate: when enforcement is on, a state-changing call needs an
        # explicit confirm (the standing pre-authorization is the confirm flag).
        if policy.requires_confirmation("ha_call_service", pre_authorized=body.confirm):
            raise HTTPException(
                409,
                "Confirmation required: controlling the home is a high-risk action. "
                "Re-send with confirm=true to proceed.",
            )
        try:
            return await _client.call_service(owner, body.domain, body.service,
                                              body.entity_id, body.data)
        except HomeAssistantError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f"Home Assistant request failed: {e}")

    return router
