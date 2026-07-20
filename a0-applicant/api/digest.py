"""AZ2 — Digest proxy: get/recap/approve/decline via the engine.

The Digest UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/digest``
API, keeping the engine the single source of truth for digest state. Multiple actions
dispatched by ``action``: ``get``, ``recap``, ``approve``, ``decline``.

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
    action = str((input or {}).get("action") or "").strip().lower()
    cid = str(input.get("campaign_id") or "__system__").strip() or "__system__"

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

    return {"ok": False, "status": 400, "error": f"unknown digest action {action!r}"}


class Digest(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
