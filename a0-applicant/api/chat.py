"""AZ2 (#837) — Chat proxy: send messages, confirm attribute/criteria changes per campaign.

The Chat UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/chat"
API, keeping the engine the single source of truth for conversation state.
Three actions dispatched by "action": "send" (POST), "confirm" (POST), "confirm_criteria" (POST).

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
    cid = str((input or {}).get("campaign_id") or "__system__").strip() or "__system__"
    action = str((input or {}).get("action") or "send").strip().lower()

    if action == "send":
        message = (input or {}).get("message") or ""
        if not message.strip():
            return {"ok": False, "status": 400, "error": "message required"}
        body = {
            "campaign_id": cid,
            "message": message,
        }
        return _forward("POST", "/api/chat", body)

    if action == "confirm":
        body = {
            "campaign_id": cid,
            "name": input.get("name"),
            "value": input.get("value"),
        }
        return _forward("POST", "/api/chat/confirm", body)

    if action == "confirm_criteria":
        body = {
            "campaign_id": cid,
            "changes": input.get("changes", {}),
        }
        return _forward("POST", "/api/chat/confirm-criteria", body)

    return {"ok": False, "status": 400, "error": f"unknown chat action {action!r}"}


class Chat(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
