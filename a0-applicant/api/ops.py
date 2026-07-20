"""AZ3 (#842) — Ops proxy: tool toggles + observability (history/detections/logs) per campaign.

The Ops console UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/auth/tools",
"/api/auth/history/{cid}", "/api/auth/detections/{cid}", and "/api/auth/logs" APIs,
keeping the engine the single source of truth for ops state.
Five actions dispatched by "action": "tools" (GET), "set_tool" (POST),
"history" (GET), "detections" (GET), "logs" (GET).

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward"
logic is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

from helpers.api import ApiHandler
from flask import Request


ENGINE_PREFIX = "/api/auth"


def _engine() -> str:
    return os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")


def _forward(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    """Call the engine; return a normalized ``{ok, status, data|error}`` envelope (never raises)."""
    import json
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
    action = str((input or {}).get("action") or "tools").strip().lower()

    if action == "tools":
        return _forward("GET", f"{ENGINE_PREFIX}/tools")

    if action == "set_tool":
        tool_key = (input or {}).get("tool_key")
        if not tool_key:
            return {"ok": False, "status": 400, "error": "tool_key required"}
        enabled = bool((input or {}).get("enabled", True))
        return _forward("POST", f"{ENGINE_PREFIX}/tools/{tool_key}?enabled={str(enabled).lower()}")

    if action == "history":
        return _forward("GET", f"{ENGINE_PREFIX}/history/{cid}")

    if action == "detections":
        return _forward("GET", f"{ENGINE_PREFIX}/detections/{cid}")

    if action == "logs":
        return _forward("GET", f"{ENGINE_PREFIX}/logs")

    return {"ok": False, "status": 400, "error": f"unknown ops action {action!r}"}


class Ops(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
