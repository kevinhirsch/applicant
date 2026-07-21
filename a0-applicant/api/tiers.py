"""AZ3 (#839) — Tiers ladder proxy: get/set the model escalation ladder.

The tiers panel is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/setup/llm/tiers"
API, keeping the engine the single source of truth for the tier ladder.
Two actions dispatched by "action": "get" (GET /api/setup/llm/tiers), "set" (PUT /api/setup/llm/tiers).

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
    action = str((input or {}).get("action") or "get").strip().lower()

    if action == "get":
        return _forward("GET", "/api/setup/llm/tiers")

    if action == "set":
        inp = input or {}
        body = {}
        if "tiers" in inp:
            body["tiers"] = inp["tiers"]
        return _forward("PUT", "/api/setup/llm/tiers", body)

    return {"ok": False, "status": 400, "error": f"unknown tiers action {action!r}"}


class Tiers(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
