"""AZ2 (#836) — Live-takeover proxy: list sessions, view-url, takeover, resume walls, final approval.

The Takeover UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/remote/..."
API, keeping the engine the single source of truth for remote session state.
Eight actions dispatched by "action": "sessions" (GET), "view_url" (GET),
"takeover" (POST), "resume_2fa" (POST), "resume_account" (POST),
"resume_detection" (POST), "handoff" (GET), "final_approval" (POST).

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
    action = str((input or {}).get("action") or "sessions").strip().lower()

    if action == "sessions":
        return _forward("GET", "/api/remote/sessions")

    if action == "view_url":
        session_id = (input or {}).get("session_id")
        if not session_id:
            return {"ok": False, "status": 400, "error": "session_id required"}
        return _forward("GET", f"/api/remote/sessions/{session_id}/view-url")

    if action == "takeover":
        session_id = (input or {}).get("session_id")
        if not session_id:
            return {"ok": False, "status": 400, "error": "session_id required"}
        return _forward("POST", f"/api/remote/sessions/{session_id}/takeover")

    if action == "resume_2fa":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("POST", f"/api/remote/applications/{application_id}/continue-two-factor")

    if action == "resume_account":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("POST", f"/api/remote/applications/{application_id}/resume-account-step")

    if action == "resume_detection":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("POST", f"/api/remote/applications/{application_id}/resume-detection-step")

    if action == "handoff":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("GET", f"/api/remote/applications/{application_id}/emergency-handoff")

    if action == "final_approval":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("POST", f"/api/remote/applications/{application_id}/request-final-approval")

    return {"ok": False, "status": 400, "error": f"unknown takeover action {action!r}"}


class Takeover(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
