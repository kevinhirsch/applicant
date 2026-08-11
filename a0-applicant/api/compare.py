"""AZ3 (#840) — Compare proxy: cross-entity comparison for applications and postings.

The Compare UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/compare/*"
API, keeping the engine the single source of truth for comparison state.
Two actions dispatched by "action": "applications" (POST) and "postings" (POST).

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward"
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


def _forward(method: str, path: str, body: dict | list | None = None, timeout: int = 10) -> dict:
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
    action = str((input or {}).get("action") or "applications").strip().lower()
    campaign_id = (input or {}).get("campaign_id") or ""

    if action == "applications":
        ids = (input or {}).get("ids") or (input or {}).get("application_ids") or []
        if not ids:
            return {"ok": False, "status": 400, "error": "ids required"}
        path = "/api/compare/applications"
        if campaign_id:
            path += f"?campaign_id={campaign_id}"
        return _forward("POST", path, ids)

    if action == "postings":
        ids = (input or {}).get("ids") or (input or {}).get("posting_ids") or []
        if not ids:
            return {"ok": False, "status": 400, "error": "ids required"}
        path = "/api/compare/postings"
        if campaign_id:
            path += f"?campaign_id={campaign_id}"
        return _forward("POST", path, ids)

    return {"ok": False, "status": 400, "error": f"unknown compare action {action!r}"}


class Compare(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
