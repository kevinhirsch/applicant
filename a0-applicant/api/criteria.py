"""AZ3 (#840) — Criteria proxy: view/edit/get signature/apply learned adjustments per campaign.

The Criteria UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/criteria/{cid}"
API, keeping the engine the single source of truth for criteria state.
Actions dispatched by "action": "view" (GET), "update"/"edit" (PUT, direct user edit of
titles/locations/work_modes/keywords/salary_floor), "signature" (GET), "apply_learned"
(POST), "alignment" (GET, posting-vs-past-wins explainability), "set_exploration_budget"
(PUT).

"update"/"edit" only forwards fields present in ``input`` (so an edit form can send a
partial diff), plus the ``confirm``/``clear_learned`` flags. The engine's confirmation
gate (FR-FB-3) 409s when an integral field (titles/locations/salary_floor) changes
without ``confirm: true`` — the caller is expected to re-ask the user and retry with
``confirm`` set, same as the attributes proxy's integral-field flow.

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
    cid = _resolve_campaign_id((input or {}).get("campaign_id"))
    action = str((input or {}).get("action") or "view").strip().lower()

    if action == "view":
        return _forward("GET", f"/api/criteria/{cid}")

    if action in ("update", "edit"):
        # Build body from only the keys present in input, so a partial edit (e.g. just
        # keywords) doesn't accidentally re-send unrelated fields the user didn't touch.
        body: dict = {}
        for key in ("titles", "locations", "work_modes", "keywords", "salary_floor", "human_readable"):
            if key in input:
                body[key] = input[key]
        if input.get("confirm"):
            body["confirm"] = True
        if input.get("clear_learned"):
            body["clear_learned"] = True
        return _forward("PUT", f"/api/criteria/{cid}", body)

    if action == "signature":
        return _forward("GET", f"/api/criteria/{cid}/signature")

    if action == "apply_learned":
        body = {
            "adjustment": input.get("adjustment"),
            "rationale": input.get("rationale"),
        }
        return _forward("POST", f"/api/criteria/{cid}/learned", body)

    if action == "alignment":
        posting_id = str((input or {}).get("posting_id") or "").strip()
        if not posting_id:
            return {"ok": False, "status": 400, "error": "posting_id required"}
        return _forward("GET", f"/api/criteria/{cid}/alignment/{posting_id}")

    if action == "set_exploration_budget":
        budget = (input or {}).get("exploration_budget")
        if budget is None:
            return {"ok": False, "status": 400, "error": "exploration_budget required"}
        return _forward(
            "PUT", f"/api/criteria/{cid}/exploration-budget", {"exploration_budget": budget}
        )

    return {"ok": False, "status": 400, "error": f"unknown criteria action {action!r}"}


class Criteria(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
