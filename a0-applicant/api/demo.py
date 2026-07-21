"""AZ3 (#842) — Demo Data proxy: DEMO_MODE status + seed/clear through the engine.

Three actions dispatched by "action": "status" -> GET /api/dev/seed/status
(wraps engine 404 as {demo_mode: false, demo_active: false} when demo is off);
"seed" -> POST /api/dev/seed (load demo data); "clear" -> POST /api/dev/seed/reset
(clear demo data). Unknown action -> 400.

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
    action = str((input or {}).get("action") or "status").strip().lower()

    if action == "status":
        result = _forward("GET", "/api/dev/seed/status")
        # When DEMO_MODE is off the engine 404s — translate gracefully
        if not result.get("ok"):
            return {"ok": True, "status": 200, "data": {"demo_mode": False, "demo_active": False}}
        d = result.get("data", {})
        d["demo_mode"] = True
        return {"ok": True, "status": 200, "data": d}

    if action == "seed":
        result = _forward("POST", "/api/dev/seed/")
        if not result.get("ok"):
            # 404 because DEMO_MODE=0 — return graceful state
            if result.get("status") == 404:
                return {"ok": True, "status": 200, "data": {"demo_mode": False, "seeded": False}}
            return result
        return {"ok": True, "status": 200, "data": {"demo_mode": True, "seeded": True}}

    if action == "clear":
        result = _forward("POST", "/api/dev/seed/reset")
        if not result.get("ok"):
            if result.get("status") == 404:
                return {"ok": True, "status": 200, "data": {"demo_mode": False, "reset": True}}
            return result
        return {"ok": True, "status": 200, "data": {"demo_mode": True, "reset": True}}

    return {"ok": False, "status": 400, "error": f"unknown demo action {action!r}"}


class Demo(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
