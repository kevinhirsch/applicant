"""AZ2 — Notifications proxy: list/seen/deliver-now via the engine.

The Notifications UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/notifications``
API, keeping the engine the single source of truth for notification state. Multiple actions
dispatched by ``action``: ``list``, ``seen``, ``deliver_now``, ``presence``.

Self-contained (plugin sibling-imports are unreliable); the pure ``dispatch``/``_forward``
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
    action = str((input or {}).get("action") or "").strip().lower()

    # Default action is "list" when action is empty or missing
    if not action:
        action = "list"

    if action == "list":
        include_seen = "true" if input.get("include_seen") else "false"
        qs = f"include_seen={include_seen}"
        # since/limit are opt-in incremental-poll params (forwarded only when the
        # caller supplies them) so the historical no-arg query string is unchanged.
        since = str((input or {}).get("since") or "").strip()
        if since:
            qs += f"&since={urllib.parse.quote(since)}"
        limit = (input or {}).get("limit")
        if limit is not None:
            try:
                qs += f"&limit={int(limit)}"
            except (TypeError, ValueError):
                pass
        return _forward("GET", f"/api/notifications?{qs}")

    if action == "seen":
        notification_id = str((input or {}).get("notification_id") or "").strip()
        if not notification_id:
            return {"ok": False, "status": 400, "error": "notification_id required"}
        return _forward("POST", f"/api/notifications/{notification_id}/seen")

    if action == "deliver_now":
        return _forward("POST", "/api/notifications/deliver-now")

    if action == "presence":
        # Web-presence heartbeat (FR-NOTIF-2): lets the in-app surface pre-empt the
        # Discord escalation while the user is verifiably looking at the Notifications
        # panel. Forwards to the same engine endpoint the digest front door uses.
        present = bool((input or {}).get("present", True))
        return _forward("POST", "/api/digest/presence", {"present": present})

    return {"ok": False, "status": 400, "error": f"unknown notifications action {action!r}"}


class Notifications(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
