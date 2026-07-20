"""AZ3 (#842) — Research proxy: run company/role research, view cached results + budget.

The Research UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/research/{cid}"
API, keeping the engine the single source of truth for research state.
Three actions dispatched by "action": "cached" (GET), "budget" (GET), "run" (POST).

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward"
logic is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
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
    action = str((input or {}).get("action") or "cached").strip().lower()

    if action == "cached":
        path = f"/api/research/{cid}/cached"
        query_param = (input or {}).get("query")
        if query_param:
            path += f"?query={urllib.parse.quote(str(query_param))}"
        return _forward("GET", path)

    if action == "budget":
        return _forward("GET", f"/api/research/{cid}/budget")

    if action == "run":
        body = {
            "query": (input or {}).get("query"),
            "company": (input or {}).get("company"),
            "role": (input or {}).get("role"),
            "context": (input or {}).get("context"),
            "max_time": (input or {}).get("max_time"),
            "force": (input or {}).get("force", False),
        }
        return _forward("POST", f"/api/research/{cid}/run", body)

    return {"ok": False, "status": 400, "error": f"unknown research action {action!r}"}


class Research(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
