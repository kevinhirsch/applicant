"""Model-endpoint proxy — list/add/test/remove endpoints and list models via the engine.

The model-endpoints UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/model-endpoints``
API, keeping the engine the single source of truth for endpoint configuration. Five actions
dispatched by ``action``: ``list``, ``add``, ``test``, ``remove``, ``models``.

SECURITY: secret fields (api_key) are passed straight through in the request body and never
logged, printed, or echoed.

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

    if action == "list":
        return _forward("GET", "/api/model-endpoints")

    if action == "add":
        body = {}
        for key in ("base_url", "api_key", "name", "model_type", "skip_probe"):
            if key in input:
                body[key] = input[key]
        return _forward("POST", "/api/model-endpoints", body)

    if action == "test":
        body = {}
        for key in ("base_url", "api_key"):
            if key in input:
                body[key] = input[key]
        return _forward("POST", "/api/model-endpoints/test", body)

    if action == "remove":
        eid = str((input or {}).get("endpoint_id") or "").strip()
        if not eid:
            return {"ok": False, "status": 400, "error": "endpoint_id required for remove action"}
        return _forward("DELETE", f"/api/model-endpoints/{eid}")

    if action == "models":
        eid = str((input or {}).get("endpoint_id") or "").strip()
        if not eid:
            return {"ok": False, "status": 400, "error": "endpoint_id required for models action"}
        return _forward("GET", f"/api/model-endpoints/{eid}/models")

    return {"ok": False, "status": 400, "error": f"unknown model_endpoints action {action!r}"}


class ModelEndpoints(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
