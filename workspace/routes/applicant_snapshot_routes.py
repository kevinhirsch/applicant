# routes/applicant_snapshot_routes.py
"""Pre-submit submission-snapshot proxy (surfacing-only, OWNER-scoped).

At the final-submit stop-boundary the engine records an **immutable** per-application
submission snapshot (#372) — the exact answers/field values, the material versions,
the posting, and a timestamp — the durable record of *what was actually sent*. Today
that record is reachable only through the ADMIN-gated Activity/Debug surface
(``applicant_admin_routes.submission_snapshot`` → engine
``GET /api/outcomes/applications/{id}/snapshot``); a regular owner has no first-class
window onto it, and no way to review it *before* they authorize the irreversible
submit.

This proxy SURFACES that same snapshot in the front-door as a NON-admin,
owner-scoped read so the live-remote surface can show "review exactly what will be
sent" *before* the owner authorizes the assistant to finish. It adds no engine logic
and creates no new engine state — it is a thin, auth-protected proxy over
:class:`src.applicant_engine.ApplicantEngineClient` (the browser never reaches the
engine directly), modelled exactly on the sibling ``applicant_activity_routes.py``:

* the ENGINE OWNER is authenticated by the front-door (``require_engine_owner``,
  H3 hardening: the snapshot is the owner's literal filled application, so a
  second workspace account is denied); this remains a deliberate admin→owner
  downgrade of a READ (mirrors ``applicant_results_routes``), NOT a weakening of
  the submit gates — the terminal authorize/submit controls keep their
  ``can_use_documents`` privilege in ``applicant_remote_routes``;
* every engine failure degrades soft — an unreachable engine returns
  ``engine_available: false`` with a well-formed empty body, a setup gate returns
  ``gated: true`` with the engine's own message, and (crucially) **no snapshot yet**
  — the pre-submit 404 — returns ``has_snapshot: false`` with an empty, well-formed
  body so the preview renders its honest "not recorded yet" state instead of
  throwing or fabricating what will be sent.

Pre-submit (H3, full-fidelity review): the engine now records a provisional
``stage: "reviewed"`` snapshot AT the stop-boundary — the literal filled payload —
and promotes it byte-identical to ``stage: "submitted"`` on the terminal submit, so
what the owner reviews here is exactly what is sent. A 404 still means "nothing
recorded yet" (e.g. the application never reached the boundary) and renders as the
honest empty state, never a fabrication.

Endpoint (one prefix, ``/api/applicant/snapshot``):

* ``GET /api/applicant/snapshot/{application_id}`` — the immutable submission
  snapshot (answers / material versions / materials / posting / timestamp) for one
  application the owner is reviewing.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from src.applicant_engine import ApplicantEngineClient, EngineError, soft_degrade
from src.auth_helpers import require_engine_owner

logger = logging.getLogger(__name__)


# --- helpers ----------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Require the engine OWNER (H3): the snapshot is the owner's literal filled
    application — answers, documents, posting. The engine is single-tenant, so
    ``require_user`` alone would let a second workspace account read the owner's
    data; ``require_engine_owner`` passes the lone owner and denies others."""
    return require_engine_owner(request)


def _empty(application_id: str) -> dict:
    """The well-formed empty snapshot body every soft-degrade path returns."""
    return {
        "application_id": application_id,
        "has_snapshot": False,
        "answers": {},
        "material_versions": {},
        "materials": [],
        "posting_url": "",
        "timestamp": None,
        "stage": "",
    }


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return [v for v in value if v] if isinstance(value, list) else []


def setup_applicant_snapshot_routes() -> APIRouter:
    router = APIRouter(prefix="/api/applicant/snapshot", tags=["applicant-snapshot"])

    @router.get("/{application_id}")
    async def submission_snapshot(application_id: str, request: Request) -> dict:
        """The immutable submission snapshot for one application (#372).

        Proxies the engine's durable record of what was (or will be) submitted —
        the exact ``answers``, the ``material_versions``/``materials`` used, the
        ``posting_url``, and the ``timestamp``. Degrades soft:

        * an unreachable engine → ``engine_available: false``;
        * a setup/permission gate → ``gated: true`` with the engine's own message;
        * **no snapshot recorded yet** (the pre-submit 404) → ``has_snapshot:
          false`` with a well-formed empty body — the preview shows its honest
          "nothing recorded to send yet" state rather than fabricating.
        """
        _require_user(request)
        empty = _empty(application_id)
        async with ApplicantEngineClient() as engine:
            try:
                data = await engine.submission_snapshot(application_id)
            except EngineError as exc:
                # A 404 is the EXPECTED pre-submit state (no snapshot recorded yet),
                # not "engine offline": the engine is reachable, there is simply
                # nothing to show. Surface it as an honest empty snapshot.
                if exc.status == 404:
                    logger.debug("snapshot: none recorded yet for %s", application_id)
                    return {**empty, "engine_available": True}
                logger.debug(
                    "snapshot: fetch failed for %s (status=%s): %s",
                    application_id, exc.status, exc,
                )
                # Gate (409/403/…) → gated:true + message; transport → offline.
                return soft_degrade(exc, empty)

        payload = _as_dict(data)
        answers = _as_dict(payload.get("answers"))
        material_versions = _as_dict(payload.get("material_versions"))
        materials = _as_list(payload.get("materials"))
        posting_url = payload.get("posting_url") or ""
        timestamp = payload.get("timestamp")
        has_snapshot = bool(
            answers or material_versions or materials or posting_url or timestamp
        )
        return {
            "engine_available": True,
            "has_snapshot": has_snapshot,
            "application_id": payload.get("application_id") or application_id,
            "answers": answers,
            "material_versions": material_versions,
            "materials": materials,
            "posting_url": posting_url,
            "timestamp": timestamp,
            # H3: where the snapshot was captured — "reviewed" (the pre-submit
            # stop-boundary: exactly what WILL be sent) or "submitted" (the
            # terminal record: exactly what WAS sent). Empty when unknown.
            "stage": str(payload.get("stage") or ""),
        }

    return router
