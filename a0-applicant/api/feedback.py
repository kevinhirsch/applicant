"""AZ3 (#840) — Feedback proxy: feedback history, free-text, and survey per campaign.

The Feedback UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/feedback/"
API, keeping the engine the single source of truth for feedback state.
Three actions dispatched by "action": "history" (GET), "freetext" (POST), "survey" (POST).

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
    action = str((input or {}).get("action") or "history").strip().lower()

    if action == "history":
        return _forward("GET", f"/api/feedback/{cid}")

    if action == "freetext":
        body = {
            "campaign_id": cid,
            "text": input.get("text"),
            "criteria_delta": input.get("criteria_delta", {}),
        }
        return _forward("POST", "/api/feedback/freetext", body)

    if action == "survey":
        body = {
            "campaign_id": cid,
            "answers": input.get("answers", {}),
        }
        return _forward("POST", "/api/feedback/survey", body)

    return {"ok": False, "status": 400, "error": f"unknown feedback action {action!r}"}


class Feedback(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
