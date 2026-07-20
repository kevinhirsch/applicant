"""AZ3 (#841) — Mind proxy: what the assistant remembers / saved playbooks / curation approvals.

The Mind UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/agent-memory``
API, keeping the engine the single source of truth for memory/skills/curation state.
Multiple actions dispatched by ``action``: ``memory``, ``skills``, ``curation``,
``approve``, ``forget``.

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
    action = str((input or {}).get("action") or "").strip().lower()

    # Default action is "memory" when action is empty or missing
    if not action:
        action = "memory"

    if action == "memory":
        return _forward("GET", "/api/agent-memory")

    if action == "skills":
        return _forward("GET", "/api/agent-memory/skills")

    if action == "curation":
        return _forward("GET", "/api/agent-memory/curation")

    if action == "approve":
        proposal_id = (input or {}).get("proposal_id") or ""
        if not proposal_id:
            return {"ok": False, "status": 400, "error": "proposal_id required"}
        return _forward("POST", f"/api/agent-memory/curation/{proposal_id}/approve")

    if action == "forget":
        # Mirror the engine's ForgetRequest model:
        #   ref: str | None = None
        #   text: str | None = None
        #   scope: str | None = None
        #   campaign_id: str | None = None
        body = {}
        for key in ("ref", "text", "scope", "campaign_id"):
            if key in input:
                body[key] = input[key]
        return _forward("POST", "/api/agent-memory/forget", body)

    return {"ok": False, "status": 400, "error": f"unknown mind action {action!r}"}


class Mind(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
