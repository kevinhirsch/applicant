"""AZ2 (#833-#838) — Agent-Runs (Daily-Loop) proxy: status/intent/list/run/pause/resume via the engine.

The Daily-Loop/Activity panel needs live agent status (running/paused), scheduler
heartbeat, today's run count, latest intent, and the ability to trigger/pause/resume
runs. This handler forwards the UI's calls to the engine's ``/api/agent-runs``
API, keeping the engine the single source of truth for agent-run state. Multiple
actions dispatched by ``action``: ``status``, ``intent``, ``list``, ``run``,
``pause``, ``resume``.

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
    cid = str((input or {}).get("campaign_id") or "__system__").strip() or "__system__"
    action = str((input or {}).get("action") or "").strip().lower()

    # Default action is "status" when action is empty or missing
    if not action:
        return _forward("GET", f"/api/agent-runs/{cid}/status")

    if action == "status":
        return _forward("GET", f"/api/agent-runs/{cid}/status")

    if action == "intent":
        return _forward("GET", f"/api/agent-runs/{cid}/intent")

    if action == "list":
        return _forward("GET", f"/api/agent-runs/{cid}")

    if action == "run":
        return _forward("POST", f"/api/agent-runs/{cid}/run")

    if action == "pause":
        return _forward("POST", f"/api/agent-runs/{cid}/pause")

    if action == "resume":
        return _forward("POST", f"/api/agent-runs/{cid}/resume")

    return {"ok": False, "status": 400, "error": f"unknown agent-runs action {action!r}"}


class AgentRuns(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
