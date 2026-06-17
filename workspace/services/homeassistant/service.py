"""Home Assistant config store + guarded REST client (Phase 4).

Owner-scoped config (encrypted token + entity allowlist) and a thin async REST
client. Control calls are constrained to the allowlist here; HIGH-risk
confirmation is enforced by the route via ``src.policy``. Transport is REST in
this phase; a WebSocket state stream can slot behind the same client later
(decided: REST first, then WebSocket).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from core.database import SessionLocal
from core.proactive_models import HomeAssistantConfig
from services.homeassistant.allowlist import is_allowed

logger = logging.getLogger(__name__)


def _config_dict(c: HomeAssistantConfig, *, include_token: bool = False) -> Dict[str, Any]:
    d = {
        "base_url": c.base_url,
        "enabled": c.enabled,
        "allowlist": c.allowlist or [],
        "token_set": bool(c.token),
    }
    if include_token:
        d["token"] = c.token
    return d


class HomeAssistantConfigStore:
    """Owner-scoped CRUD for the single HA config row per user."""

    def get(self, owner: Optional[str], *, include_token: bool = False) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            c = db.query(HomeAssistantConfig).filter(HomeAssistantConfig.owner == owner).first()
            return _config_dict(c, include_token=include_token) if c else None
        finally:
            db.close()

    def set(self, owner: Optional[str], *, base_url: Optional[str] = None,
            token: Optional[str] = None, enabled: Optional[bool] = None,
            allowlist: Optional[List[str]] = None) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            c = db.query(HomeAssistantConfig).filter(HomeAssistantConfig.owner == owner).first()
            if c is None:
                c = HomeAssistantConfig(id=str(uuid.uuid4()), owner=owner, enabled=False, allowlist=[])
                db.add(c)
            if base_url is not None:
                c.base_url = base_url.rstrip("/")
            if token is not None:
                c.token = token            # EncryptedText handles encryption at rest
            if enabled is not None:
                c.enabled = enabled
            if allowlist is not None:
                c.allowlist = allowlist
            db.commit()
            db.refresh(c)
            return _config_dict(c)
        finally:
            db.close()

    def _raw(self, owner: Optional[str]) -> Optional[HomeAssistantConfig]:
        db = SessionLocal()
        try:
            return db.query(HomeAssistantConfig).filter(HomeAssistantConfig.owner == owner).first()
        finally:
            db.close()


class HomeAssistantError(Exception):
    pass


class HomeAssistantClient:
    """Thin async REST client over the owner's configured HA instance."""

    def __init__(self, store: Optional[HomeAssistantConfigStore] = None):
        self._store = store or HomeAssistantConfigStore()

    def _conn(self, owner: Optional[str]):
        c = self._store._raw(owner)
        if not c or not c.enabled or not c.base_url or not c.token:
            raise HomeAssistantError("Home Assistant is not configured/enabled for this user")
        return c.base_url, c.token, (c.allowlist or [])

    def _headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def get_states(self, owner: Optional[str]) -> List[Dict[str, Any]]:
        import httpx
        base, token, allow = self._conn(owner)
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{base}/api/states", headers=self._headers(token))
            r.raise_for_status()
            states = r.json()
        # Only surface entities the user has allowlisted (privacy + scope).
        return [s for s in states if is_allowed(s.get("entity_id", ""), allow)]

    async def call_service(self, owner: Optional[str], domain: str, service: str,
                           entity_id: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import httpx
        base, token, allow = self._conn(owner)
        if not is_allowed(entity_id, allow):
            raise HomeAssistantError(f"Entity '{entity_id}' is not in the allowlist")
        payload = {"entity_id": entity_id, **(data or {})}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{base}/api/services/{domain}/{service}",
                                  headers=self._headers(token), json=payload)
            r.raise_for_status()
            return {"ok": True, "domain": domain, "service": service, "entity_id": entity_id}
