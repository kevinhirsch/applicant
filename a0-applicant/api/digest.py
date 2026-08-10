"""AZ2 — Digest proxy: get/recap/approve/decline via the engine.

The Digest UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/digest``
API, keeping the engine the single source of truth for digest state. Multiple actions
dispatched by ``action``: ``get``, ``recap``, ``approve``, ``decline``, ``deliver``,
``email``, ``presence``.

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
    action = str((input or {}).get("action") or "").strip().lower()
    cid = _resolve_campaign_id(input.get("campaign_id"))

    # Default action is "get" when action is empty or missing
    if not action:
        action = "get"

    if action == "get":
        return _forward("GET", f"/api/digest/{cid}")

    if action == "recap":
        return _forward("GET", f"/api/digest/{cid}/weekly-recap")

    if action == "approve":
        application_id = str((input or {}).get("application_id") or "").strip()
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("POST", f"/api/digest/applications/{application_id}/approve", None)

    if action == "decline":
        application_id = str((input or {}).get("application_id") or "").strip()
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("POST", f"/api/digest/applications/{application_id}/decline", {"feedback_text": input.get("reason")})

    if action == "deliver":
        return _forward("POST", f"/api/digest/{cid}/deliver", None)

    if action == "email":
        return _forward("GET", f"/api/digest/{cid}/email")

    if action == "presence":
        present = bool((input or {}).get("present", True))
        return _forward("POST", "/api/digest/presence", {"present": present})

    return {"ok": False, "status": 400, "error": f"unknown digest action {action!r}"}


class Digest(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
