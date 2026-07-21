"""AZ3-6 (#844) — Connections proxy: email/calendar lane credentials via the companion.

The Connections panel is served by the a0 shell, but the Applicant companion is internal-only
("companion:7000"). This handler forwards the UI's calls to the companion's email and calendar
APIs, keeping the companion the single source of truth for email/calendar credentials.

Actions dispatched by ``action``:
  get_email_accounts   -> GET  /api/email/accounts
  add_email_account    -> POST /api/email/accounts      (forward only present keys)
  update_email_account -> PUT  /api/email/accounts/{id}  (requires account_id)
  delete_email_account -> DELETE /api/email/accounts/{id}
  test_email_account   -> POST /api/email/accounts/test  (account_id or inline creds)
  get_calendar_config  -> GET  /api/calendar/config
  set_calendar_config  -> POST /api/calendar/config
  test_calendar_config -> POST /api/calendar/test

SECURITY: secrets pass straight through; NEVER log or print them (NFR-PRIV-1).

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


def _companion() -> str:
    return os.getenv("COMPANION_URL", "http://companion:7000").rstrip("/")


def _forward(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    """Call the companion; return a normalized ``{ok, status, data|error}`` envelope (never raises)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(f"{_companion()}{path}", data=data, headers=headers, method=method)
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
    inp = input or {}

    if action == "get_email_accounts":
        return _forward("GET", "/api/email/accounts")

    if action == "add_email_account":
        body = {}
        for key in ("name", "is_default", "enabled", "imap_host", "imap_port", "imap_user",
                    "imap_password", "imap_starttls", "smtp_host", "smtp_port", "smtp_user",
                    "smtp_password", "from_address"):
            if key in inp:
                body[key] = inp[key]
        return _forward("POST", "/api/email/accounts", body)

    if action == "update_email_account":
        account_id = str(inp.get("account_id", "")).strip()
        if not account_id:
            return {"ok": False, "status": 400, "error": "account_id is required for update_email_account"}
        body = {}
        for key in ("name", "is_default", "enabled", "imap_host", "imap_port", "imap_user",
                    "imap_password", "imap_starttls", "smtp_host", "smtp_port", "smtp_user",
                    "smtp_password", "from_address"):
            if key in inp:
                body[key] = inp[key]
        return _forward("PUT", f"/api/email/accounts/{account_id}", body)

    if action == "delete_email_account":
        account_id = str(inp.get("account_id", "")).strip()
        if not account_id:
            return {"ok": False, "status": 400, "error": "account_id is required for delete_email_account"}
        return _forward("DELETE", f"/api/email/accounts/{account_id}")

    if action == "test_email_account":
        body = {}
        if "account_id" in inp:
            body["account_id"] = inp["account_id"]
        for key in ("imap_host", "imap_port", "imap_user", "imap_password", "imap_starttls",
                    "smtp_host", "smtp_port", "smtp_user", "smtp_password"):
            if key in inp:
                body[key] = inp[key]
        return _forward("POST", "/api/email/accounts/test", body)

    if action == "get_calendar_config":
        return _forward("GET", "/api/calendar/config")

    if action == "set_calendar_config":
        body = {}
        for key in ("url", "username", "password"):
            if key in inp:
                body[key] = inp[key]
        return _forward("POST", "/api/calendar/config", body)

    if action == "test_calendar_config":
        body = {}
        for key in ("url", "username", "password"):
            if key in inp:
                body[key] = inp[key]
        return _forward("POST", "/api/calendar/test", body)

    return {"ok": False, "status": 400, "error": f"unknown connections action {action!r}"}


class Connections(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
