"""AZ3 (#841) — Mind proxy: what the assistant remembers / saved playbooks / curation approvals.

The Mind UI is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the UI's calls to the engine's ``/api/agent-memory``
API, keeping the engine the single source of truth for memory/skills/curation state.
Multiple actions dispatched by ``action``: ``memory``, ``skills``, ``curation``,
``approve``, ``deny``, ``forget``, ``playbook_get``, ``playbook_apply_deltas``
(the last two cover the distinct, per-ATS ACE playbook — FR-MIND-9/dark-engine
audit item 46 — not the free-text "saved playbooks" above).

Self-contained (plugin sibling-imports are unreliable); the pure ``dispatch``/``_forward``
logic is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import json
import os
import time
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


_ACTIVE_CAMPAIGN_CACHE: dict = {"id": None, "ts": 0.0}
_ACTIVE_CAMPAIGN_TTL_S = 30


def _resolve_campaign_id(raw: str | None) -> str:
    """Map missing/'__system__' campaign_id to the single active campaign (MVP is
    single-campaign; mirrors the same helper in api/research.py). Explicit non-system
    ids pass through. Fails CLOSED to the raw value on ANY problem (no campaign yet /
    engine down / pre-onboarding gate) so the pre-onboarding __system__ flow is
    unaffected."""
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
    action = str((input or {}).get("action") or "").strip().lower()

    # Default action is "memory" when action is empty or missing
    if not action:
        action = "memory"

    if action == "memory":
        return _forward("GET", "/api/agent-memory")

    if action == "skills":
        return _forward("GET", "/api/agent-memory/skills")

    if action == "curation":
        return _forward("GET", "/api/agent-memory/curation")

    if action == "approve":
        proposal_id = (input or {}).get("proposal_id") or ""
        if not proposal_id:
            return {"ok": False, "status": 400, "error": "proposal_id required"}
        return _forward("POST", f"/api/agent-memory/curation/{proposal_id}/approve")

    if action == "deny":
        proposal_id = (input or {}).get("proposal_id") or ""
        if not proposal_id:
            return {"ok": False, "status": 400, "error": "proposal_id required"}
        return _forward("POST", f"/api/agent-memory/curation/{proposal_id}/deny")

    if action == "playbook_get":
        ats = str((input or {}).get("ats") or "").strip()
        if not ats:
            return {"ok": False, "status": 400, "error": "ats required"}
        cid = _resolve_campaign_id((input or {}).get("campaign_id"))
        path = f"/api/agent-memory/playbooks/{urllib.parse.quote(ats)}?campaign_id={urllib.parse.quote(cid)}"
        return _forward("GET", path)

    if action == "playbook_apply_deltas":
        ats = str((input or {}).get("ats") or "").strip()
        if not ats:
            return {"ok": False, "status": 400, "error": "ats required"}
        cid = _resolve_campaign_id((input or {}).get("campaign_id"))
        deltas = (input or {}).get("deltas") or []
        body = {"campaign_id": cid, "deltas": deltas}
        path = f"/api/agent-memory/playbooks/{urllib.parse.quote(ats)}/apply-deltas"
        return _forward("POST", path, body)

    if action == "forget":
        # Mirror the engine's ForgetRequest model:
        #   ref: str | None = None
        #   text: str | None = None
        #   scope: str | None = None
        #   campaign_id: str | None = None
        body = {}
        for key in ("ref", "text", "scope", "campaign_id"):
            if key in input:
                body[key] = input[key]
        return _forward("POST", "/api/agent-memory/forget", body)

    return {"ok": False, "status": 400, "error": f"unknown mind action {action!r}"}


class Mind(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
