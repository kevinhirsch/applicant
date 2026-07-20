"""AZ2 — Attributes proxy: list/add/delete attributes via the engine.

The Attributes UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/attributes``
API, keeping the engine the single source of truth for attribute state. Actions
dispatched by ``action``: ``list``, ``add``, ``delete``.

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
    cid = str((input or {}).get("campaign_id") or "__system__").strip()
    action = str((input or {}).get("action") or "").strip().lower()

    # Default action is "list" when action is empty or missing
    if not action:
        return _forward("GET", f"/api/attributes/{cid}")

    if action == "list":
        return _forward("GET", f"/api/attributes/{cid}")

    if action == "add":
        body = {
            "campaign_id": cid,
            "name": input.get("name"),
            "value": input.get("value"),
            "is_sensitive": bool(input.get("is_sensitive")),
        }
        return _forward("POST", "/api/attributes", body)

    if action == "delete":
        attribute_id = input.get("attribute_id")
        if not attribute_id:
            return {"ok": False, "status": 400, "error": "attribute_id required"}
        return _forward("DELETE", f"/api/attributes/{cid}/{attribute_id}")

    return {"ok": False, "status": 400, "error": f"unknown attributes action {action!r}"}


class Attributes(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
