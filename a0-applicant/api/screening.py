"""AZ2 (#842) — Screening proxy: library/generate via the engine.

The Screening UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/documents``
API, keeping the engine the single source of truth for screening-answer state. Two actions
dispatched by ``action``: ``library``, ``generate``.

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
    cid = str((input or {}).get("campaign_id") or "").strip()

    # Default action is "library" when action is empty or missing
    if not action:
        action = "library"

    if action == "library":
        cid = cid or "__system__"
        return _forward("GET", f"/api/documents/screening-answer-library/{cid}")

    if action == "generate":
        body = {}
        for key in ("campaign_id", "application_id", "question", "true_source", "essay", "explicit_answer"):
            if key in input:
                body[key] = input[key]
        return _forward("POST", "/api/documents/screening-answer", body)

    return {"ok": False, "status": 400, "error": f"unknown screening action {action!r}"}


class Screening(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
