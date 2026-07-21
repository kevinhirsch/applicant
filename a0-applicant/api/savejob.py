"""AZ3 (#842) — Save-a-Job proxy: paste a job URL -> intake pipeline."""
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
    action = str((input or {}).get("action") or "save").strip().lower()

    if action == "save":
        inp = input or {}
        campaign_id = str(inp.get("campaign_id", "__system__") or "__system__").strip()
        url = inp.get("url", "").strip()
        if not url:
            return {"ok": False, "status": 400, "error": "url is required"}
        return _forward("POST", f"/api/intake/{campaign_id}/url", {"url": url})

    return {"ok": False, "status": 400, "error": f"unknown savejob action {action!r}"}


class SaveJob(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
