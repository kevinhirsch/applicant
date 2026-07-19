"""AZ1-2 (#830) — OOBE onboarding proxy: forward the a0 shell's wizard to the engine.

The OOBE wizard is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the wizard's calls to the engine's
``/api/onboarding`` API, keeping the engine the single source of truth for section
state and apply-readiness (never client-derived, H1). One endpoint, dispatched by
``action``: ``state`` (resumable — sections_complete + first-incomplete), ``section``
(persist one section, validated engine-side), ``complete`` (apply_ready / apply_missing).

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
    except Exception as e:  # engine down / network — honest surface, no crash
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}


def dispatch(input: dict) -> dict:
    cid = str((input or {}).get("campaign_id") or "__system__").strip() or "__system__"
    action = str((input or {}).get("action") or "state").strip().lower()
    if action == "state":
        return _forward("GET", f"/api/onboarding/{cid}")
    if action == "section":
        body = {"section": (input or {}).get("section"), "data": (input or {}).get("data") or {}}
        return _forward("POST", f"/api/onboarding/{cid}/section", body)
    if action == "complete":
        return _forward("POST", f"/api/onboarding/{cid}/complete", {})
    return {"ok": False, "status": 400, "error": f"unknown onboarding action {action!r}"}


class Onboarding(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
