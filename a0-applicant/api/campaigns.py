"""AZ2 (#833-#838) — Campaigns proxy: list/create/update/clone/guardrails via the engine.

The Campaigns UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/campaigns``
API, keeping the engine the single source of truth for campaign state. Multiple actions
dispatched by ``action``: ``list``, ``create``, ``update``, ``clone``, ``guardrails``.

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
    cid = str((input or {}).get("campaign_id") or "").strip()
    action = str((input or {}).get("action") or "").strip().lower()

    # Default action is "list" when action is empty or missing
    if not action:
        return _forward("GET", "/api/campaigns")

    if action == "list":
        return _forward("GET", "/api/campaigns")

    if action == "create":
        body = {"name": input.get("name")}
        return _forward("POST", "/api/campaigns", body)

    if action == "update":
        if not cid:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        # Build body from only the keys that are present in input
        body = {}
        for key in ("name", "run_mode", "throughput_target", "exploration_budget", "active"):
            if key in input:
                body[key] = input[key]
        return _forward("PATCH", f"/api/campaigns/{cid}", body)

    if action == "clone":
        if not cid:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        body = {}
        name = input.get("name")
        if name is not None:
            body["name"] = name
        return _forward("POST", f"/api/campaigns/{cid}/clone", body if body else None)

    if action == "guardrails":
        if not cid:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        return _forward("GET", f"/api/campaigns/{cid}/guardrails")

    return {"ok": False, "status": 400, "error": f"unknown campaigns action {action!r}"}


class Campaigns(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
