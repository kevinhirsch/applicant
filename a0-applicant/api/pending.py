"""AZ2 (#833-#838) — Pending-actions proxy: daily-review panel via the engine.

The today/daily-review panel is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the panel's calls to the engine's
``/api/pending-actions`` API, keeping the engine the single source of truth for item state,
priority, aging, urgency, and snooze (never client-derived, H1). Multiple actions dispatched by
``action``: ``list``, ``count``, ``resolve``, ``snooze``, ``resolve_bulk``.

Self-contained (plugin sibling-imports are unreliable); the pure ``dispatch``/``_forward``
logic is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from helpers.api import ApiHandler
from flask import Request


def _engine() -> str:
    return os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")

def _forward(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    """Call the engine; return a normalized ``{ok, status, data|error}`` envelope (never raises)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(f"{_engine()}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
            return {"ok": True, "status": r.status, "data": json.loads(raw) if raw.strip() else {}}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode()[:300]}
    except Exception as e:
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}


_ACTIVE_CAMPAIGN_CACHE: dict = {"id": None, "ts": 0.0}
_ACTIVE_CAMPAIGN_TTL_S = 30


def _resolve_campaign_id(raw: str | None) -> str:
    """Map missing/'__system__' campaign_id to the single active campaign (MVP is
    single-campaign). Explicit non-system ids pass through. Fails CLOSED to the raw
    value on ANY problem (no campaign yet / engine down / pre-onboarding gate) so the
    pre-onboarding __system__ flow is unaffected."""
    cid = str(raw or "__system__").strip() or "__system__"
    if cid != "__system__":
        return cid
    now = time.time()
    if _ACTIVE_CAMPAIGN_CACHE["id"] and (now - _ACTIVE_CAMPAIGN_CACHE["ts"]) < _ACTIVE_CAMPAIGN_TTL_S:
        return _ACTIVE_CAMPAIGN_CACHE["id"]
    result = _forward("GET", "/api/campaigns")
    campaigns = result.get("data") if result.get("ok") else None
    if isinstance(campaigns, list) and campaigns:
        active = next((c for c in campaigns if isinstance(c, dict) and c.get("active")), campaigns[0])
        resolved = active.get("id") if isinstance(active, dict) else None
        if resolved:
            _ACTIVE_CAMPAIGN_CACHE["id"] = resolved
            _ACTIVE_CAMPAIGN_CACHE["ts"] = now
            return resolved
    return cid


def dispatch(input: dict) -> dict:
    cid = _resolve_campaign_id((input or {}).get("campaign_id"))
    action = str((input or {}).get("action") or "").strip().lower()
    
    if action == "list":
        include_snoozed = "true" if input.get("include_snoozed") else "false"
        return _forward("GET", f"/api/pending-actions/{cid}?include_snoozed={include_snoozed}")
    
    if action == "count":
        return _forward("GET", f"/api/pending-actions/{cid}/count")
    
    if action == "resolve":
        aid = input.get("action_id")
        body = {}
        if input.get("apply") is not None:
            body["apply"] = bool(input["apply"])
        return _forward("POST", f"/api/pending-actions/{aid}/resolve", body if body else None)
    
    if action == "snooze":
        aid = input.get("action_id")
        body = {}
        if input.get("hours") is not None:
            body["hours"] = input["hours"]
        if input.get("until") is not None:
            body["until"] = str(input["until"])
        return _forward("POST", f"/api/pending-actions/{aid}/snooze", body if body else None)
    
    if action == "resolve_bulk":
        action_ids = input.get("action_ids") or []
        return _forward("POST", f"/api/pending-actions/{cid}/resolve-bulk", {"action_ids": action_ids})
    
    return {"ok": False, "status": 400, "error": f"unknown pending action {action!r}"}


class Pending(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
