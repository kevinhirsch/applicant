# routes/applicant_compare_routes.py
"""Workspace-side Compare proxy for the Applicant engine's cross-entity diffs.

The engine (``src/applicant/app/routers/compare.py``, #297) compares two or more
applications (or postings) side-by-side and returns a dimension table — a list of
``{key, label, values, diff}`` rows plus a plain-language ``summary`` — optionally
scoped to one campaign so a caller cannot compare across campaigns.

This module is the **front-door** half of the Compare surface (#184/#486): a thin,
auth-protected proxy over :class:`src.applicant_engine.ApplicantEngineClient`,
mounted under the ``/api/applicant/compare`` prefix. It deliberately does NOT reuse
the vendored app's own ``routes/compare_routes.py`` (``/api/compare`` — the model
arena) — that is an unrelated surface; the convention for engine-backed lanes is
``/api/applicant/*``.

Every handler is read-through to the engine: a configured-but-offline or
not-yet-configured engine degrades to a clean JSON error (502/503/504/4xx) via
:func:`_engine_call`, never a raw 500 or a leaked ``httpx`` exception. The engine
route is itself gated by ``require_llm_configured`` (it returns a 4xx when no model
is connected); we forward that verbatim so the UI can prompt the user to finish
setup. The section only lights up in the front-door once the engine reports a model
is configured (handled by the feature-activation layer — this file does not fight
it).

Auth: these routes sit behind the workspace's global auth middleware (they are
**not** in the auth-exempt list), and each handler additionally calls
:func:`require_user` so an unauthenticated request is rejected before any engine
call is made.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request bodies (1:1 with the engine's compare router).
# ---------------------------------------------------------------------------


class CompareIn(BaseModel):
    # The engine needs >=2 ids to produce a comparison; a shorter list still
    # returns a 200 with a "Need at least 2 ..." summary (a degraded result, not
    # an error), so we forward as-is and let the engine decide.
    ids: list[str] = []
    campaign_id: str | None = None


# ---------------------------------------------------------------------------
# Engine plumbing (mirrors routes/applicant_email_routes.py).
# ---------------------------------------------------------------------------


def _engine_client() -> ApplicantEngineClient:
    """Construct the engine client.

    Single construction point so hermetic tests can monkeypatch it to inject an
    ``httpx.MockTransport`` (see ``tests/test_applicant_compare_routes.py``)
    without any network.
    """
    return ApplicantEngineClient()


def _engine_error_to_http(exc: EngineError) -> HTTPException:
    """Map a typed :class:`EngineError` to a clean HTTP error for the UI.

    Transport failures (timeout / connection refused) become 504/503 so the
    front end can show "Applicant is offline" rather than a generic 500. An HTTP
    error *response* from the engine is forwarded with a faithful status: a 4xx
    (e.g. the ``require_llm_configured`` gate, or a 422 on a malformed body) is
    passed through so the UI can re-prompt; 5xx / unknown are normalised to 502.
    """
    if exc.is_timeout:
        return HTTPException(status_code=504, detail="The Applicant engine timed out. Try again shortly.")
    if exc.status is None:
        return HTTPException(status_code=503, detail="The Applicant engine is not reachable right now.")
    detail = exc.detail if exc.detail not in (None, "") else exc.message
    if 400 <= exc.status < 500:
        return HTTPException(status_code=exc.status, detail=detail)
    return HTTPException(status_code=502, detail="The Applicant engine returned an error.")


async def _engine_call(coro_factory):
    """Run one engine coroutine, closing the client and normalising failures."""
    engine = _engine_client()
    try:
        return await coro_factory(engine)
    except EngineError as exc:
        logger.info("applicant compare engine call failed: %s", exc)
        raise _engine_error_to_http(exc) from exc
    finally:
        await engine.aclose()


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


def setup_applicant_compare_routes() -> APIRouter:
    """Build the Applicant Compare (cross-entity diff) proxy router."""
    router = APIRouter(prefix="/api/applicant/compare", tags=["applicant-compare"])

    @router.get("/campaigns")
    async def list_campaigns(request: Request) -> dict:
        """Campaigns the Compare picker can scope a comparison to.

        Read-only convenience so the Compare UI can offer a campaign chooser
        without coupling to another surface; backed by the engine's existing
        campaigns list. Returns ``{"campaigns": [...]}``.
        """
        require_user(request)
        data = await _engine_call(lambda e: e.list_campaigns())
        return {"campaigns": data if isinstance(data, list) else []}

    @router.post("/applications")
    async def compare_applications(request: Request, body: CompareIn) -> dict:
        """Compare two or more applications side-by-side.

        Returns the engine's dimension table (``entity_ids`` / ``entity_labels`` /
        ``dimensions[].values+diff`` / ``summary``). Campaign-scoped when
        ``campaign_id`` is given (cross-campaign ids are excluded engine-side).
        """
        require_user(request)
        return await _engine_call(
            lambda e: e.compare_applications(body.ids, body.campaign_id)
        )

    @router.post("/postings")
    async def compare_postings(request: Request, body: CompareIn) -> dict:
        """Compare two or more job postings side-by-side.

        Returns the engine's dimension table (title / company / location diffs +
        ``summary``). Campaign-scoped when ``campaign_id`` is given.
        """
        require_user(request)
        return await _engine_call(
            lambda e: e.compare_postings(body.ids, body.campaign_id)
        )

    return router
