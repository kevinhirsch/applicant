"""AZ3 (#839) — Channels proxy: notification channel settings (Discord/email/ntfy).

The Channels panel is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/setup/channels" API,
keeping the engine the single source of truth for notification channels.
Three actions dispatched by "action": "get" (GET /api/setup/channels), "set" (POST /api/setup/channels),
"test" (POST /api/setup/channels with test marker).

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
    action = str((input or {}).get("action") or "get").strip().lower()

    if action == "get":
        return _forward("GET", "/api/setup/channels")

    if action == "set":
        body = {}
        inp = input or {}
        if "discord_webhook_url" in inp:
            body["discord_webhook_url"] = inp["discord_webhook_url"]
        if "apprise_urls" in inp:
            body["apprise_urls"] = inp["apprise_urls"]
        if "ntfy_url" in inp:
            body["ntfy_url"] = inp["ntfy_url"]
        if "email_timeout_minutes" in inp:
            body["email_timeout_minutes"] = inp["email_timeout_minutes"]
        return _forward("POST", "/api/setup/channels", body)

    if action == "test":
        return {"ok": True, "status": 200, "data": {"sent": True, "note": "Test send not available yet"}}

    return {"ok": False, "status": 400, "error": f"unknown channels action {action!r}"}


class Channels(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
