"""EPIC REVIEW-UX — Review proxy: decide / refine a queued application via the engine.

The Review modal lives inside ``documents.html`` (reuse-first — no dedicated panel),
but the Applicant engine is internal-only (``api:8000``). This handler forwards the
UI's ``callJsonApi("review", {action, ...})`` calls to the engine's ``/api/review``
router, keeping the engine the single source of truth for the review workflow.

The panel speaks a friendly action vocabulary; this proxy TRANSLATES each action to
the engine's REST endpoints (the same pattern ``a0-applicant/api/digest.py`` uses):

  * ``get`` / ``snapshot``     -> GET  /api/review/{application_id}/source   (RUX-1)
  * ``decide`` (continue)      -> POST /api/review/{application_id}/continue (RUX-2)
  * ``decide`` (save_for_later)-> POST /api/review/{application_id}/save-for-later
  * ``decide`` (discard)       -> POST /api/review/{application_id}/discard
  * ``saved``                  -> GET  /api/review/{campaign_id}/saved
  * ``regenerate_section``     -> POST /api/review/{application_id}/apply-instruction (RUX-3)
  * ``apply_feedback``         -> POST /api/review/{application_id}/apply-instruction
  * ``regenerate_all``         -> POST /api/review/{application_id}/apply-instruction
  * ``profile_feedback``       -> POST /api/feedback/freetext  (folds into learning)

``edit_section`` (a literal manual content replacement) and ``revert_feedback`` (undo a
profile adjustment) have NO engine endpoint yet, so they return an honest, graceful
``{ok: False, status: 501}`` envelope the panel surfaces as a per-action message rather
than a broken route. See the module ``NOTE`` below — those two need engine endpoints.

Self-contained (plugin sibling-imports are unreliable); the pure ``dispatch`` /
``_forward`` / ``_resolve_campaign_id`` logic is module-level so it is unit-testable
without the a0 framework. Mirrors ``a0-applicant/api/digest.py``.
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


def _forward(method: str, path: str, body: dict | None = None, timeout: int = 30) -> dict:
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
    pre-onboarding __system__ flow is unaffected. Identical to api/digest.py."""
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


def _need(value: str | None, label: str) -> tuple[str | None, dict | None]:
    """Return ``(value, None)`` when present, else ``(None, error_envelope)``."""
    v = str(value or "").strip()
    if not v:
        return None, {"ok": False, "status": 400, "error": f"{label} required"}
    return v, None


def dispatch(input: dict) -> dict:
    inp = input or {}
    action = str(inp.get("action") or "").strip().lower() or "index"
    cid = _resolve_campaign_id(inp.get("campaign_id"))
    aid = str(inp.get("application_id") or "").strip()

    if action == "index":
        return _forward("GET", "/api/review")

    # --- RUX-1: source posting + cached snapshot ---------------------------
    if action in ("get", "snapshot"):
        aid, err = _need(aid, "application_id")
        if err:
            return err
        return _forward("GET", f"/api/review/{aid}/source")

    # --- RUX-2: three-way decision — Continue / Save-for-later / Discard ---
    if action == "decide":
        aid, err = _need(aid, "application_id")
        if err:
            return err
        decision = str(inp.get("decision") or "").strip().lower()
        posting_id = str(inp.get("posting_id") or "").strip() or None
        if decision in ("continue", "proceed"):
            return _forward("POST", f"/api/review/{aid}/continue")
        if decision in ("save_for_later", "save", "later", "save-for-later"):
            body = {"campaign_id": cid, "posting_id": posting_id}
            title = str(inp.get("title") or "").strip()
            if title:
                body["title"] = title
            remind = inp.get("remind_in_hours")
            if remind is not None:
                body["remind_in_hours"] = remind
            return _forward("POST", f"/api/review/{aid}/save-for-later", body)
        if decision == "discard":
            reason = str(inp.get("reason") or "").strip()
            if not reason:
                return {"ok": False, "status": 400, "error": "a discard reason is required"}
            return _forward(
                "POST",
                f"/api/review/{aid}/discard",
                {"campaign_id": cid, "reason": reason, "posting_id": posting_id},
            )
        return {"ok": False, "status": 400, "error": f"unknown decision {decision!r}"}

    # --- Saved / To submit bucket (RUX-2) ---------------------------------
    if action == "saved":
        return _forward("GET", f"/api/review/{cid}/saved")

    # --- RUX-3: refine — per-section / cross-section / whole-app -----------
    # The panel's refinement actions all send a plain-language ``feedback`` string,
    # which is exactly the engine's instruction-based revision loop (apply-instruction
    # over the app's generated documents). Empty ``document_ids`` fans across ALL
    # sections (cross-section / whole-app); a single id is a targeted section edit.
    # Every revision stays review-gated (a turn never approves) — nothing is submitted.
    if action in ("regenerate_section", "apply_feedback", "regenerate_all"):
        aid, err = _need(aid, "application_id")
        if err:
            return err
        instruction = str(inp.get("feedback") or inp.get("instruction") or "").strip()
        if not instruction:
            return {"ok": False, "status": 400, "error": "feedback is required to refine"}
        if action == "regenerate_section":
            section_id = str(inp.get("section_id") or "").strip()
            document_ids = [section_id] if section_id else []
        else:  # apply_feedback / regenerate_all
            document_ids = [
                str(s).strip()
                for s in (inp.get("section_ids") or [])
                if str(s).strip()
            ]
        return _forward(
            "POST",
            f"/api/review/{aid}/apply-instruction",
            {
                "campaign_id": cid,
                "instruction": instruction,
                "kind": "free_text",
                "document_ids": document_ids,
            },
        )

    # --- profile feedback: fold the note into the campaign's learning model ---
    if action == "profile_feedback":
        text = str(inp.get("feedback") or "").strip()
        if not text:
            return {"ok": False, "status": 400, "error": "feedback text is required"}
        return _forward(
            "POST", "/api/feedback/freetext", {"campaign_id": cid, "text": text}
        )

    # NOTE (engine gap): ``edit_section`` (a literal manual content replacement) and
    # ``revert_feedback`` (undo a profile adjustment) have no /api/review endpoint yet.
    # The engine's revision model is instruction-based (apply_turn), not direct-content
    # set, and there is no adjustment-ledger revert. Return an honest 501 so the panel
    # shows a per-action message instead of a broken route. These need engine endpoints
    # (a REVIEW-UX backend follow-up), not a proxy workaround.
    if action == "edit_section":
        return {
            "ok": False,
            "status": 501,
            "error": "Saving a manual section edit isn't supported by the engine yet.",
        }
    if action == "revert_feedback":
        return {
            "ok": False,
            "status": 501,
            "error": "Reverting a profile adjustment isn't supported by the engine yet.",
        }

    return {"ok": False, "status": 400, "error": f"unknown review action {action!r}"}


class Review(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
