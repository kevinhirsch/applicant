"""AdminLogs proxy — live/paginated engine log tail for the Debug panel.

The Debug panel polls this on a fast (~2s) cadence for a live-tailing log view, separate
from the Ops console's slower, aggregate admin calls (history/detections/tools). Forwards to
the engine's already-redacted, ring-buffered "/api/admin/logs" (FR-LOG-3 / FR-OBS-2). One
action dispatched by "action": "tail" (GET, params: limit, since_seq).

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward" logic
is module-level so it is unit-testable without the framework.
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
    action = str((input or {}).get("action") or "tail").strip().lower()

    if action == "tail":
        limit = int((input or {}).get("limit") or 200)
        since_seq = (input or {}).get("since_seq")
        qs = f"?limit={limit}"
        if since_seq is not None:
            qs += f"&since_seq={int(since_seq)}"
        return _forward("GET", f"/api/admin/logs{qs}")

    return {"ok": False, "status": 400, "error": f"unknown adminlogs action {action!r}"}


class AdminLogs(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
