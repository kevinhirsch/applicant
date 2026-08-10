"""AZ3 (#840) — Tracker proxy: board + attention per campaign.

The Tracker UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/post-submission/*"
API, keeping the engine the single source of truth. Actions dispatched by "action":
"board" (GET), "attention" (GET), "record_outcome" (POST .../outcome — the tracker's
"record what happened" affordance: rejected/interview_invited/ghosted/offer), "archive"
(POST .../archive), "scan_email" (POST .../scan-email), "approve_followup" (POST
.../follow-up/approve). The last four were previously live on the engine with zero
proxy consumer, leaving post-submission outcome tracking unreachable from the UI.

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward"
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
    input = input or {}
    action = str(input.get("action") or "board").strip().lower()

    if action == "board":
        cid = _resolve_campaign_id(input.get("campaign_id"))
        return _forward("GET", f"/api/post-submission/{cid}")

    if action == "attention":
        cid = _resolve_campaign_id(input.get("campaign_id"))
        return _forward("GET", f"/api/post-submission/{cid}/attention")

    if action == "record_outcome":
        application_id = str(input.get("application_id") or "").strip()
        outcome_type = str(input.get("outcome_type") or "").strip()
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        if not outcome_type:
            return {"ok": False, "status": 400, "error": "outcome_type required"}
        body = {"outcome_type": outcome_type, "reason": input.get("reason")}
        return _forward("POST", f"/api/post-submission/applications/{application_id}/outcome", body)

    if action == "archive":
        application_id = str(input.get("application_id") or "").strip()
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("POST", f"/api/post-submission/applications/{application_id}/archive", None)

    if action == "scan_email":
        application_id = str(input.get("application_id") or "").strip()
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        body = {"subject": input.get("subject") or "", "body": input.get("body") or ""}
        return _forward("POST", f"/api/post-submission/applications/{application_id}/scan-email", body)

    if action == "approve_followup":
        application_id = str(input.get("application_id") or "").strip()
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        body = {}
        if input.get("subject") is not None:
            body["subject"] = input.get("subject")
        if input.get("body") is not None:
            body["body"] = input.get("body")
        if input.get("delay_hours") is not None:
            body["delay_hours"] = input.get("delay_hours")
        return _forward(
            "POST",
            f"/api/post-submission/applications/{application_id}/follow-up/approve",
            body,
        )

    return {"ok": False, "status": 400, "error": f"unknown tracker action {action!r}"}


class Tracker(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
