"""AZ2 (#835) — Documents proxy: list, approve, decline, redline documents and view outcomes per application.

The Documents UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/documents/..." and
"/api/outcomes/..." APIs, keeping the engine the single source of truth for document state.
Six actions dispatched by "action": "list" (GET), "provenance" (GET), "approve" (POST),
"decline" (POST), "redline" (POST), "snapshot" (GET).

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward"
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
    action = str((input or {}).get("action") or "list").strip().lower()

    if action == "list":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("GET", f"/api/documents/applications/{application_id}")

    if action == "provenance":
        document_id = (input or {}).get("document_id")
        if not document_id:
            return {"ok": False, "status": 400, "error": "document_id required"}
        return _forward("GET", f"/api/documents/{document_id}/provenance")

    if action == "approve":
        document_id = (input or {}).get("document_id")
        if not document_id:
            return {"ok": False, "status": 400, "error": "document_id required"}
        return _forward("POST", f"/api/documents/{document_id}/approve")

    if action == "decline":
        document_id = (input or {}).get("document_id")
        if not document_id:
            return {"ok": False, "status": 400, "error": "document_id required"}
        return _forward("POST", f"/api/documents/{document_id}/decline")

    if action == "redline":
        body = {
            "variant_id": (input or {}).get("variant_id"),
            "base_source": (input or {}).get("base_source"),
            "new_source": (input or {}).get("new_source"),
            "aggressiveness": (input or {}).get("aggressiveness"),
        }
        return _forward("POST", "/api/documents/redline", body)

    if action == "snapshot":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("GET", f"/api/outcomes/applications/{application_id}/snapshot")

    return {"ok": False, "status": 400, "error": f"unknown documents action {action!r}"}


class Documents(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
