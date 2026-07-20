"""WT (#w1) — Dormant surfaces proxy: list registered dormant surfaces.

Dispatches "list" -> GET /api/dormant-surfaces, unknown action -> 400,
default action -> "list". The engine's dormant-surfaces route returns a
list of {key, name, requirement_ids, live_phase, status} entries.

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward"
logic is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

from helpers.api import ApiHandler
from flask import Request


ENGINE_PREFIX = "/api"


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
    action = str((input or {}).get("action") or "list").strip().lower()

    if action == "list":
        return _forward("GET", f"{ENGINE_PREFIX}/dormant-surfaces")

    return {"ok": False, "status": 400, "error": f"unknown dormant action {action!r}"}


class Dormant(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
