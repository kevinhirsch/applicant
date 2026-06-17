# routes/applicant_email_routes.py
"""Workspace-side Email proxy for the Applicant engine's digests + feedback.

This is the Stage-2 "Email" lane route file. The workspace already has its own
full IMAP/SMTP mail experience (``routes/email_routes.py``, ``/api/email/*``);
this module is **additive** and lives under a separate ``/api/applicant/email``
prefix so the native mailbox is never touched.

What it surfaces, all backed 1:1 by the engine client
(``src/applicant_engine.py``) and the engine's ``digest`` + ``feedback``
routers:

* the daily **digest** for a campaign (one row per viable role + empty-day note),
* the **digest email** render (the engine's own email template payload),
* **deliver** the digest and report web **presence** (so the in-app view can
  pre-empt the chat/Discord push),
* **approve / decline** a digested role straight from the in-app view (decline
  carries mandatory feedback that feeds learning), and
* free-text / guided-survey **feedback** at any time.

Every handler is read-through to the engine: a configured-but-offline or
not-yet-configured engine degrades to a clean JSON error (502/503/504/4xx) via
:func:`_engine_call`, never a raw 500 or a leaked ``httpx`` exception. The
section only lights up in the UI once the engine reports ``channels_configured``
+ the ``digest_in_app`` surface live (handled by the existing feature-activation
layer — this file does not fight it).

Auth: these routes sit behind the workspace's global auth middleware (they are
**not** in the auth-exempt list), and each handler additionally calls
:func:`require_user` so an unauthenticated request is rejected before any engine
call is made.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.applicant_engine import (
    ApplicantEngineClient,
    EngineError,
    engine_base_url,
)
from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request bodies (1:1 with the engine's digest/feedback routers).
# ---------------------------------------------------------------------------


class PresenceIn(BaseModel):
    present: bool = True


class DeclineIn(BaseModel):
    # Engine requires non-blank feedback on the decline path (FR-FB-1); we let
    # the engine enforce that and surface its 422 verbatim so the UI can prompt.
    feedback_text: str = ""
    criteria_delta: dict = {}


class FreeTextIn(BaseModel):
    campaign_id: str
    text: str
    criteria_delta: dict = {}


class SurveyIn(BaseModel):
    campaign_id: str
    answers: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Engine plumbing.
# ---------------------------------------------------------------------------


def _engine_client() -> ApplicantEngineClient:
    """Construct the engine client.

    Factored out as the single construction point so hermetic tests can
    monkeypatch it to inject an ``httpx.MockTransport`` (see
    ``tests/test_applicant_email_routes.py``) without any network.
    """
    return ApplicantEngineClient()


def _engine_error_to_http(exc: EngineError) -> HTTPException:
    """Map a typed :class:`EngineError` to a clean HTTP error for the UI.

    Transport failures (timeout / connection refused) become 504/503 so the
    front end can show "Applicant is offline" rather than a generic 500. An HTTP
    error *response* from the engine is forwarded with a faithful status:

    * ``422`` (e.g. mandatory decline feedback was blank) is passed through so
      the UI can re-prompt with the engine's message.
    * other ``4xx`` are passed through (client-correctable).
    * ``5xx`` / unknown are normalised to ``502 Bad Gateway`` (the engine, not
      the workspace, failed).
    """
    if exc.is_timeout:
        return HTTPException(status_code=504, detail="The Applicant engine timed out. Try again shortly.")
    if exc.status is None:
        # Connection refused / DNS / pool error — engine unreachable.
        return HTTPException(status_code=503, detail="The Applicant engine is not reachable right now.")
    detail = exc.detail if exc.detail not in (None, "") else exc.message
    if exc.status == 422 or 400 <= exc.status < 500:
        return HTTPException(status_code=exc.status, detail=detail)
    # 5xx and anything unexpected: the upstream engine failed.
    return HTTPException(status_code=502, detail="The Applicant engine returned an error.")


async def _engine_call(coro_factory):
    """Run one engine coroutine, closing the client and normalising failures.

    ``coro_factory`` is a callable taking the live client and returning the
    awaitable to run, e.g. ``lambda e: e.digest(campaign_id)``. We open the
    client per request (cheap, in-network) and always close it.
    """
    engine = _engine_client()
    try:
        return await coro_factory(engine)
    except EngineError as exc:
        logger.info("applicant email engine call failed: %s", exc)
        raise _engine_error_to_http(exc) from exc
    finally:
        await engine.aclose()


#: Transport seam for the presence POST (the engine ``POST /api/digest/presence``
#: has no dedicated client method and the shared engine client is append-only for
#: other lanes / off-limits here, so this single write goes direct over httpx
#: while reusing the same typed-error degradation). Tests set this to a
#: ``httpx.MockTransport`` to stay hermetic; ``None`` = real network.
_PRESENCE_TRANSPORT: httpx.AsyncBaseTransport | None = None


async def _post_presence(present: bool) -> None:
    """POST the web-presence signal to the engine, degrading like the client.

    Uses ``httpx`` directly (already a dependency — no new deps) rather than
    adding a method to the shared, off-limits engine client. Every failure is
    normalised to :class:`EngineError` so the caller's mapping is identical to
    every other engine call.
    """
    base = engine_base_url()
    try:
        async with httpx.AsyncClient(
            base_url=base,
            timeout=httpx.Timeout(connect=3.0, read=30.0, write=10.0, pool=3.0),
            transport=_PRESENCE_TRANSPORT,
        ) as client:
            resp = await client.post("/api/digest/presence", json={"present": present})
    except httpx.TimeoutException as exc:
        raise EngineError("Engine request timed out: POST /api/digest/presence", is_timeout=True) from exc
    except httpx.HTTPError as exc:
        raise EngineError(f"Engine request failed: POST /api/digest/presence: {exc}") from exc
    if resp.status_code >= 400:
        raise EngineError(
            f"Engine returned HTTP {resp.status_code} for POST /api/digest/presence",
            status=resp.status_code,
        )


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


def setup_applicant_email_routes() -> APIRouter:
    """Build the Applicant Email (digest/notifications/feedback) proxy router."""
    router = APIRouter(prefix="/api/applicant/email", tags=["applicant-email"])

    @router.get("/campaigns")
    async def list_campaigns(request: Request) -> dict:
        """Campaigns the in-app updates view can pick a digest for.

        Read-only convenience so the Email UI can offer a campaign chooser
        without coupling to another surface; backed by the engine's existing
        campaigns list. Returns ``{"campaigns": [...]}``.
        """
        require_user(request)
        data = await _engine_call(lambda e: e.list_campaigns())
        return {"campaigns": data if isinstance(data, list) else []}

    @router.get("/digest/{campaign_id}")
    async def get_digest(request: Request, campaign_id: str) -> dict:
        """Daily digest for a campaign: viable-role rows + empty-day note.

        Backs the in-app "Applicant updates" view. Read-only.
        """
        require_user(request)
        return await _engine_call(lambda e: e.digest(campaign_id))

    @router.get("/digest/{campaign_id}/email")
    async def get_digest_email(request: Request, campaign_id: str) -> dict:
        """The engine's rendered digest *email* payload (subject + body).

        Lets the in-app view show exactly what was (or would be) emailed.
        """
        require_user(request)
        return await _engine_call(lambda e: e.digest_email(campaign_id))

    @router.post("/digest/{campaign_id}/deliver")
    async def deliver_digest(request: Request, campaign_id: str) -> dict:
        """Re-send / deliver the digest across configured channels.

        Returns the engine's delivery summary (row count, channels, subject).
        """
        require_user(request)
        return await _engine_call(lambda e: e.deliver_digest(campaign_id))

    @router.post("/presence")
    async def set_presence(request: Request, body: PresenceIn) -> dict:
        """Tell the engine the user is reading updates in the workspace now.

        Lets the engine pre-empt the chat/Discord push for the same digest.
        The engine returns 204 (no body); we answer with a small JSON ack so the
        front end gets a consistent shape.
        """
        require_user(request)
        try:
            await _post_presence(body.present)
        except EngineError as exc:
            logger.info("applicant email presence call failed: %s", exc)
            raise _engine_error_to_http(exc) from exc
        return {"ok": True, "present": body.present}

    @router.post("/applications/{application_id}/approve")
    async def approve_application(request: Request, application_id: str) -> dict:
        """Approve a role straight from the in-app updates view."""
        require_user(request)
        return await _engine_call(lambda e: e.approve_digest_application(application_id))

    @router.post("/applications/{application_id}/decline")
    async def decline_application(
        request: Request, application_id: str, body: DeclineIn
    ) -> dict:
        """Decline a role with feedback (feeds learning + next-run criteria).

        Feedback is mandatory on the engine side; a blank note comes back as a
        422 which we forward so the UI can re-prompt.
        """
        require_user(request)
        payload = {"feedback_text": body.feedback_text, "criteria_delta": body.criteria_delta}
        return await _engine_call(
            lambda e: e.decline_digest_application(application_id, payload)
        )

    @router.post("/feedback/freetext")
    async def feedback_freetext(request: Request, body: FreeTextIn) -> dict:
        """Send free-text feedback for a campaign at any time."""
        require_user(request)
        payload = {
            "campaign_id": body.campaign_id,
            "text": body.text,
            "criteria_delta": body.criteria_delta,
        }
        return await _engine_call(lambda e: e.feedback_freetext(payload))

    @router.post("/feedback/survey")
    async def feedback_survey(request: Request, body: SurveyIn) -> dict:
        """Submit guided-survey feedback for a campaign."""
        require_user(request)
        payload = {"campaign_id": body.campaign_id, "answers": body.answers}
        return await _engine_call(lambda e: e.feedback_survey(payload))

    return router
