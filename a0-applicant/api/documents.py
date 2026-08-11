"""AZ2 (#835) — Documents proxy: list, approve, decline, redline documents and view outcomes per application.

The Documents UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/documents/..." and
"/api/outcomes/..." APIs, keeping the engine the single source of truth for document state.
Actions dispatched by "action": "list" (GET), "list_applications" (GET), "provenance"
(GET), "approve" (POST), "decline" (POST), "redline" (POST), "snapshot" (GET), "variants"
(GET), "approve_variant" (POST), "promote_variant" (POST), "cover_letter" (POST),
"flagged_facts" (GET), "jd_match" (GET), "set_aggressiveness" (POST), "screening_library"
(GET), "screening_reuse" (POST).

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
    action = str((input or {}).get("action") or "list").strip().lower()

    if action == "list":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("GET", f"/api/documents/applications/{application_id}")

    # Bug fix: the Documents panel's application picker was wrongly reusing the
    # "tracker"/"board" proxy action (post-submission-only, excludes DIGESTED
    # drafts awaiting review) -- see engine route docstring for the root cause.
    # This action lists every application the panel should be able to browse.
    if action == "list_applications":
        campaign_id = (input or {}).get("campaign_id")
        if not campaign_id:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        return _forward("GET", f"/api/documents/applications/campaign/{campaign_id}")

    if action == "provenance":
        document_id = (input or {}).get("document_id")
        if not document_id:
            return {"ok": False, "status": 400, "error": "document_id required"}
        return _forward("GET", f"/api/documents/{document_id}/provenance")

    if action == "approve":
        document_id = (input or {}).get("document_id")
        if not document_id:
            return {"ok": False, "status": 400, "error": "document_id required"}
        # P0 fix (0/581 docs ever approved in prod): MaterialService.approve() 409s
        # unless a revision session is already OPEN for this document -- the "approve
        # only after viewing" gate, enforced server-side in the engine. The
        # Documents-panel "Approve" / "Apply Redline" buttons (approveRedlineViaDoc
        # calls approveDocument -> this same action) never opened one first, so every
        # approve from this panel 409'd. Mirror EXACTLY how the Review & Refine
        # "Continue" path does it (review.py continue_review: open_revision then
        # approve): open the review session first -- idempotent, a no-op if a session
        # is already open -- THEN approve. A failure opening the session is returned
        # as-is rather than masked behind a confusing approve 409.
        opened = _forward("POST", f"/api/documents/{document_id}/review")
        if not opened.get("ok"):
            return opened
        return _forward("POST", f"/api/documents/{document_id}/approve")

    if action == "decline":
        document_id = (input or {}).get("document_id")
        if not document_id:
            return {"ok": False, "status": 400, "error": "document_id required"}
        return _forward("POST", f"/api/documents/{document_id}/decline")

    if action == "redline":
        body = {
            "variant_id": (input or {}).get("variant_id"),
            "base_source": (input or {}).get("base_source"),
            "new_source": (input or {}).get("new_source"),
            "aggressiveness": (input or {}).get("aggressiveness"),
        }
        return _forward("POST", "/api/documents/redline", body)

    if action == "snapshot":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("GET", f"/api/outcomes/applications/{application_id}/snapshot")

    # Tech-debt fix (Drafting & Materials, P0 UNEXPOSED): the résumé-variant
    # library + its approve/promote gate had a working engine route but zero
    # proxy action, so a GENERATED variant routed to review was unreachable
    # from the plugin UI.
    if action == "variants":
        campaign_id = (input or {}).get("campaign_id")
        if not campaign_id:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        return _forward("GET", f"/api/documents/variants/{campaign_id}")

    if action == "approve_variant":
        variant_id = (input or {}).get("variant_id")
        if not variant_id:
            return {"ok": False, "status": 400, "error": "variant_id required"}
        return _forward("POST", f"/api/documents/variants/{variant_id}/approve")

    if action == "promote_variant":
        variant_id = (input or {}).get("variant_id")
        if not variant_id:
            return {"ok": False, "status": 400, "error": "variant_id required"}
        return _forward("POST", f"/api/documents/variants/{variant_id}/promote")

    # Tech-debt fix (Drafting & Materials, P0 pipeline-visibility gap): cover
    # letter generation, flagged-facts, and JD-match had working engine routes
    # but no proxy action, so the review UI could not surface them.
    if action == "cover_letter":
        body = {
            "campaign_id": (input or {}).get("campaign_id"),
            "application_id": (input or {}).get("application_id"),
            "true_source": (input or {}).get("true_source") or "",
            "jd_terms": (input or {}).get("jd_terms") or [],
            "campaign_default": bool((input or {}).get("campaign_default") or False),
            "role_requires": (input or {}).get("role_requires"),
        }
        return _forward("POST", "/api/documents/cover-letter", body)

    if action == "flagged_facts":
        document_id = (input or {}).get("document_id")
        if not document_id:
            return {"ok": False, "status": 400, "error": "document_id required"}
        return _forward("GET", f"/api/documents/{document_id}/flagged-facts")

    if action == "jd_match":
        application_id = (input or {}).get("application_id")
        if not application_id:
            return {"ok": False, "status": 400, "error": "application_id required"}
        return _forward("GET", f"/api/documents/jd-match/{application_id}")

    # Tech-debt fix (Drafting & Materials, P1 UNEXPOSED): the truthful-framing
    # aggressiveness dial (FR-RESUME-9) has been live on the engine since #187
    # but had no proxy action to set it.
    if action == "set_aggressiveness":
        body = {"aggressiveness": (input or {}).get("aggressiveness")}
        return _forward("POST", "/api/documents/aggressiveness", body)

    # Tech-debt fix (Drafting & Materials, P1 UNEXPOSED): reuse of a previously
    # generated screening-answer library entry (product-gaps #20) had working
    # engine routes but no proxy action.
    if action == "screening_library":
        campaign_id = (input or {}).get("campaign_id")
        if not campaign_id:
            return {"ok": False, "status": 400, "error": "campaign_id required"}
        return _forward("GET", f"/api/documents/screening-answer-library/{campaign_id}")

    if action == "screening_reuse":
        body = {
            "campaign_id": (input or {}).get("campaign_id"),
            "application_id": (input or {}).get("application_id"),
            "question": (input or {}).get("question"),
        }
        return _forward("POST", "/api/documents/screening-answer-library/reuse", body)

    return {"ok": False, "status": 400, "error": f"unknown documents action {action!r}"}


class Documents(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
