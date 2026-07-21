"""AZ3 (#839) — Privacy proxy: telemetry + sandbox-connection settings.

Forwards the UI's Privacy panel calls to the engine's /api/setup/telemetry and
/api/setup/sandbox-connection endpoints, keeping the engine the single source of
truth for telemetry preferences and sandbox connection configuration.

Actions dispatched by "action":
  - "get" → GET /api/setup/telemetry + GET /api/setup/sandbox-connection (combined)
  - "set_telemetry" → POST /api/setup/telemetry
  - "set_sandbox" → POST /api/setup/sandbox-connection

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
        telemetry = _forward("GET", "/api/setup/telemetry")
        sandbox = _forward("GET", "/api/setup/sandbox-connection")
        ok = telemetry["ok"] and sandbox["ok"]
        status = max(telemetry["status"], sandbox["status"])
        return {
            "ok": ok,
            "status": status,
            "data": {
                "telemetry": telemetry.get("data", {}),
                "sandbox_connection": sandbox.get("data", {}),
            },
        }

    if action == "set_telemetry":
        inp = input or {}
        body: dict = {}
        if "enabled" in inp:
            body["enabled"] = inp["enabled"]
        if "endpoint" in inp:
            body["endpoint"] = inp["endpoint"]
        return _forward("POST", "/api/setup/telemetry", body)

    if action == "set_sandbox":
        inp = input or {}
        body: dict = {}
        for key in (
            "proxmox_api_url", "proxmox_node", "proxmox_token_id",
            "proxmox_token_secret", "template_vmid", "clone_mode",
            "cdp_host", "cdp_port", "rdp_username", "rdp_password",
            "takeover_method", "takeover_url_template",
        ):
            if key in inp:
                body[key] = inp[key]
        return _forward("POST", "/api/setup/sandbox-connection", body)

    return {"ok": False, "status": 400, "error": f"unknown privacy action {action!r}"}


class Privacy(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
