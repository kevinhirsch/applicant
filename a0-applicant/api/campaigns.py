"""AZ2 (#833-#838) — Campaigns proxy: list/create/update/clone/guardrails via the engine.

The Campaigns UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/campaigns``
API, keeping the engine the single source of truth for campaign state. Multiple actions
dispatched by ``action``: ``list``, ``create``, ``update``, ``clone``, ``guardrails``,
``pipeline_summary``, ``delete``.

Self-contained (plugin sibling-imports are unreliable); the pure ``dispatch``/``_forward``
logic is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import json
import os
import time
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


def _normalize_list(res: dict) -> dict:
    """The engine returns a bare campaign array; UI panels expect ``data.campaigns``.
    Normalize so ``r.data.campaigns`` is always the list."""
    if res.get("ok") and isinstance(res.get("data"), list):
        res["data"] = {"campaigns": res["data"]}
    return res


_ACTIVE_CAMPAIGN_CACHE: dict = {"id": None, "ts": 0.0}
_ACTIVE_CAMPAIGN_TTL_S = 30


def _resolve_campaign_id(raw: str | None) -> str:
    """Map missing/'__system__' campaign_id to the single active campaign (MVP is
    single-campaign), mirroring the same helper in the digest/pending/tracker
    proxies. Explicit non-system ids pass through unchanged. Fails CLOSED to the
    raw value on ANY problem so callers that already resolved an id are unaffected."""
    cid = str(raw or "__system__").strip() or "__system__"
    if cid != "__system__":
        return cid
    now = time.time()
    if _ACTIVE_CAMPAIGN_CACHE["id"] and (now - _ACTIVE_CAMPAIGN_CACHE["ts"]) < _ACTIVE_CAMPAIGN_TTL_S:
        return _ACTIVE_CAMPAIGN_CACHE["id"]
    result = _forward("GET", "/api/campaigns")
    campaigns = result.get("data") if result.get("ok") else None
    if isinstance(campaigns, list) and campaigns:
        active = next((c for c in campaigns if isinstance(c, dict) and c.get("active")), campaigns[0])
        resolved = active.get("id") if isinstance(active, dict) else None
        if resolved:
            _ACTIVE_CAMPAIGN_CACHE["id"] = resolved
            _ACTIVE_CAMPAIGN_CACHE["ts"] = now
            return resolved
    return cid


def dispatch(input: dict) -> dict:
    cid = str((input or {}).get("campaign_id") or "").strip()
    action = str((input or {}).get("action") or "").strip().lower()

    # Default action is "list" when action is empty or missing
    if not action:
        return _normalize_list(_forward("GET", "/api/campaigns"))

    if action == "list":
        return _normalize_list(_forward("GET", "/api/campaigns"))

    if action == "create":
        body = {"name": input.get("name")}
        return _forward("POST", "/api/campaigns", body)

    if action == "update":
        if not cid:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        # Build body from only the keys that are present in input
        body = {}
        for key in ("name", "run_mode", "throughput_target", "exploration_budget", "active"):
            if key in input:
                body[key] = input[key]
        return _forward("PATCH", f"/api/campaigns/{cid}", body)

    if action == "clone":
        if not cid:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        body = {}
        name = input.get("name")
        if name is not None:
            body["name"] = name
        return _forward("POST", f"/api/campaigns/{cid}/clone", body if body else None)

    if action == "guardrails":
        if not cid:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        return _forward("GET", f"/api/campaigns/{cid}/guardrails")

    if action == "pipeline_summary":
        resolved = _resolve_campaign_id(cid)
        return _forward("GET", f"/api/campaigns/{resolved}/pipeline-summary")

    if action == "delete":
        if not cid:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        return _forward("DELETE", f"/api/campaigns/{cid}")

    return {"ok": False, "status": 400, "error": f"unknown campaigns action {action!r}"}


class Campaigns(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
