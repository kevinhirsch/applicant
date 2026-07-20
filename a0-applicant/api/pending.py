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


def dispatch(input: dict) -> dict:
    cid = str((input or {}).get("campaign_id") or "__system__").strip() or "__system__"
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
