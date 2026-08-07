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
import time
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


_ACTIVE_CAMPAIGN_CACHE: dict = {"id": None, "ts": 0.0}
_ACTIVE_CAMPAIGN_TTL_S = 30


def _resolve_campaign_id(raw: str | None) -> str:
    """Map missing/'__system__' campaign_id to the single active campaign (MVP is
    single-campaign). Explicit non-system ids pass through. Fails CLOSED to the raw
    value on ANY problem (no campaign yet / engine down / pre-onboarding gate) so the
    pre-onboarding __system__ flow is unaffected."""
    cid = str(raw or "__system__").strip() or "__system__"
    if cid != "__system__":
        return cid
    now = time.time()
    if _ACTIVE_CAMPAIGN_CACHE["id"] and (now - _ACTIVE_CAMPAIGN_CACHE["ts"]) < _ACTIVE_CAMPAIGN_TTL_S:
        return _ACTIVE_CAMPAIGN_CACHE["id"]
    result = _forward("GET", "/api/campaigns")
    campaigns = result.get("data") if result.get("ok") else None
    if isinstance(campaigns, list) and campaigns:
        active = next((c for c in campaigns if isinstance(c, dict) and c.get("active")), campaigns[0])
        resolved = active.get("id") if isinstance(active, dict) else None
        if resolved:
            _ACTIVE_CAMPAIGN_CACHE["id"] = resolved
            _ACTIVE_CAMPAIGN_CACHE["ts"] = now
            return resolved
    return cid


def dispatch(input: dict) -> dict:
    cid = _resolve_campaign_id((input or {}).get("campaign_id"))
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
