"""AZ2 (#841) — Update-proxy: one-click updater panel via the engine.

The daily-loop's self-update button is served by the a0 shell, but the Applicant
engine is internal-only (``api:8000``). This handler forwards the panel's calls
to the engine's ``/api/update`` API, keeping the engine the single source of
truth for updater status, state, and trigger requests (never client-derived).
Two actions dispatched by ``action``: ``status``, ``trigger``. Default action is
``status`` when none is given (mirroring onboarding.py's default convention).

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
    """Route an incoming action to the corresponding engine API call.

    Default action is ``status`` (no action given) — mirroring onboarding.py's
    default convention so the panel fetches status on load without extra boilerplate.
    """
    action = str((input or {}).get("action") or "status").strip().lower()

    if action == "status":
        return _forward("GET", "/api/update")

    if action == "trigger":
        return _forward("POST", "/api/update/trigger")

    return {"ok": False, "status": 400, "error": f"unknown update action {action!r}"}


class UpdatePanel(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
