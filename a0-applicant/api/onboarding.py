"""AZ1-2 (#830) — OOBE onboarding proxy: forward the a0 shell's wizard to the engine.

The OOBE wizard is served by the a0 shell, but the Applicant engine is internal-only
(``api:8000``). This handler forwards the wizard's calls to the engine's
``/api/onboarding`` API, keeping the engine the single source of truth for section
state and apply-readiness (never client-derived, H1). One endpoint, dispatched by
``action``: ``state`` (resumable — sections_complete + first-incomplete), ``section``
(persist one section, validated engine-side), ``complete`` (apply_ready / apply_missing).

redesign-conversational-onboarding.md adds the conversational gather/refine actions
the ``onboarding_next``/``onboarding_answer`` agent tools and the first-run banner
extension dispatch through: ``shown`` (record the wizard was displayed once),
``next`` (what to ask about next), ``save_field`` (one freeform chat answer,
read-merge-write — never clobbers section siblings), ``omit`` (explicit decline,
field- or section-level).

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
    except Exception as e:  # engine down / network — honest surface, no crash
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}


_ACTIVE_CAMPAIGN_CACHE: dict = {"id": None, "ts": 0.0}
_ACTIVE_CAMPAIGN_TTL_S = 30


def _resolve_campaign_id(raw: str | None) -> str:
    """Map missing/'__system__' campaign_id to the single active campaign (MVP is
    single-campaign). Explicit non-system ids pass through. Fails CLOSED to the raw
    value on ANY problem (no campaign yet / engine down / pre-onboarding gate) so the
    pre-onboarding __system__ flow is unaffected."""
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
    cid = _resolve_campaign_id((input or {}).get("campaign_id"))
    action = str((input or {}).get("action") or "state").strip().lower()
    if action == "state":
        return _forward("GET", f"/api/onboarding/{cid}")
    if action == "section":
        body = {"section": (input or {}).get("section"), "data": (input or {}).get("data") or {}}
        return _forward("POST", f"/api/onboarding/{cid}/section", body)
    if action == "complete":
        return _forward("POST", f"/api/onboarding/{cid}/complete", {})
    if action == "shown":
        return _forward("POST", f"/api/onboarding/{cid}/shown", {})
    if action == "next":
        return _forward("GET", f"/api/onboarding/{cid}/next")
    if action == "save_field":
        body = {
            "section": (input or {}).get("section"),
            "field": (input or {}).get("field"),
            "value": (input or {}).get("value"),
        }
        return _forward("POST", f"/api/onboarding/{cid}/field", body)
    if action == "omit":
        body = {
            "section": (input or {}).get("section"),
            "field": (input or {}).get("field"),
            "note": (input or {}).get("note") or "",
        }
        return _forward("POST", f"/api/onboarding/{cid}/omit", body)
    return {"ok": False, "status": 400, "error": f"unknown onboarding action {action!r}"}


class Onboarding(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
