"""AZ2 — Explain proxy: GET the weighted greens/reds score breakdown via the engine.

Mirrors ``a0-applicant/api/digest.py``: the panel is served by the a0 shell, but
the Applicant engine is internal-only (``api:8000``). This handler forwards
``callJsonApi("explain", {action, posting_id})`` to the engine's
``GET /api/explain/{posting_id}``. Backend-only this round — no dedicated panel
yet (a later wave); auto-discovered by basename like every sibling proxy.

Self-contained (plugin sibling-imports are unreliable); the pure ``dispatch``/
``_forward`` logic is module-level so it is unit-testable without the framework.
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
    inp = input or {}
    action = str(inp.get("action") or "").strip().lower() or "get"
    posting_id = str(inp.get("posting_id") or "").strip()

    if action == "get":
        if not posting_id:
            return {"ok": False, "status": 400, "error": "posting_id required"}
        return _forward("GET", f"/api/explain/{posting_id}")

    return {"ok": False, "status": 400, "error": f"unknown explain action {action!r}"}


class Explain(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
