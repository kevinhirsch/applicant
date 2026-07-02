# routes/applicant_vault_routes.py
"""Applicant CREDENTIAL VAULT proxy — the workspace-side endpoints the vault UI
calls to bank per-tenant site credentials and to offer auto-capture of
credentials a user typed during a human takeover / account-creation.

This fronts the ENGINE's applicant vault (``routers/credentials.py``,
FR-VAULT-2). It is intentionally SEPARATE from the workspace's own Bitwarden
surface (``routes/vault_routes.py``) — that file is untouched.

Security:

* **Owner-scoped + auth-gated.** Every route requires an authenticated session;
  the mutating banking/capture routes additionally require ``can_use_documents``
  (the privilege that gates driving the owner's real application materials).
  Master-key rotation is the heaviest mutation this vault offers (it touches
  every stored secret at once), so it MIRRORS that same ``can_use_documents``
  gate rather than inventing a separate one.
* **Never logs secrets.** Handlers never log the request body. The engine seals
  secrets with libsodium at rest and NEVER returns plaintext from the list
  endpoint — only tenant keys are surfaced — so this proxy passes through a
  safe-by-construction shape.

Like the other Applicant proxies, a typed :class:`EngineError` becomes a clean
JSON error (502 when the engine is unreachable, otherwise the engine's status).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_privilege, require_user

logger = logging.getLogger(__name__)


class CredentialIn(BaseModel):
    """One per-tenant credential set to bank manually.

    ``tenant_key`` identifies the site/ATS tenant (e.g. a Workday tenant);
    ``secret`` is the password / token — never logged, sealed by the engine.
    """

    campaign_id: str
    tenant_key: str
    username: str
    secret: str


class CaptureIn(BaseModel):
    """Credentials the user typed during a live account-creation, offered to be
    saved (the auto-capture hook). Same shape as a manual entry."""

    campaign_id: str
    tenant_key: str
    username: str
    secret: str


class AccountCredentialIn(BaseModel):
    """A GLOBAL account sign-in set once in Settings and reused across every job
    search: ``kind`` is the well-known account-credential key (the user's Google
    sign-in or the default set for creating new accounts); ``secret`` is the
    password — never logged, sealed by the engine under the SYSTEM campaign."""

    kind: str
    username: str
    secret: str


def _engine_error_response(exc: EngineError) -> JSONResponse:
    """Translate a typed :class:`EngineError` into a clean JSON error response.

    Transport failure -> 502. 4xx forwarded (client-correctable). 5xx scrubbed
    — raw detail may contain internal stack traces; logged server-side only.
    """
    if exc.status is None:
        message = (
            "The credential vault timed out."
            if exc.is_timeout
            else "The credential vault is unavailable."
        )
        return JSONResponse(
            status_code=502,
            content={"error": "engine_error", "message": message, "engine_status": None},
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (vault): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return JSONResponse(
            status_code=502,
            content={"error": "engine_error", "message": "The credential vault reported an error.", "engine_status": exc.status},
        )
    return JSONResponse(
        status_code=exc.status,
        content={"error": "engine_error", "message": "The credential vault reported an error.", "engine_status": exc.status},
    )


def setup_applicant_vault_routes() -> APIRouter:
    """Build the Applicant credential-vault proxy router (mounted in ``app.py``)."""
    router = APIRouter(prefix="/api/applicant/vault", tags=["applicant-vault"])

    @router.get("/{campaign_id}/tenants")
    async def list_tenants(campaign_id: str, request: Request) -> JSONResponse:
        """Tenant keys that have stored credentials — NO secrets returned
        (engine ``GET /api/credentials/{campaign}/tenants``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.vault_list_tenants(campaign_id)
        except EngineError as exc:
            logger.info("applicant vault list unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data or {"campaign_id": campaign_id, "tenants": []})

    @router.post("/credentials")
    async def store_credential(body: CredentialIn, request: Request) -> JSONResponse:
        """Manually bank a per-tenant credential set
        (engine ``POST /api/credentials``). Secret is never logged."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.vault_store_credential(body.model_dump())
        except EngineError as exc:
            # exc carries no secret; body is intentionally not logged.
            logger.info("applicant vault store failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    @router.post("/capture")
    async def capture_credential(body: CaptureIn, request: Request) -> JSONResponse:
        """Save credentials the user entered during a live account-creation —
        the auto-capture hook (engine ``POST /api/credentials/capture``)."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.vault_capture_credential(body.model_dump())
        except EngineError as exc:
            logger.info("applicant vault capture failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    @router.get("/account")
    async def account_status(request: Request) -> JSONResponse:
        """Which GLOBAL account sign-ins are set — no secrets returned
        (engine ``GET /api/credentials/account``)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.vault_account_status()
        except EngineError as exc:
            logger.info("applicant vault account status unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data or {"google": False, "predefined_account": False})

    @router.post("/account")
    async def store_account_credential(
        body: AccountCredentialIn, request: Request
    ) -> JSONResponse:
        """Bank a GLOBAL account sign-in (Google / default new-account set), reused
        across every job search (engine ``POST /api/credentials/account``). Secret is
        never logged."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.vault_store_account_credential(body.model_dump())
        except EngineError as exc:
            # exc carries no secret; body is intentionally not logged.
            logger.info("applicant vault account store failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data, status_code=201)

    @router.post("/rotate-key")
    async def rotate_key(request: Request) -> JSONResponse:
        """Rotate the vault's master encryption key, re-sealing every stored
        credential under a fresh one (engine ``POST /api/credentials/rotate-key``).
        Vault-hygiene action — gated the same as the other mutating vault routes
        (``can_use_documents``); no secrets are returned, only the re-sealed count."""
        require_privilege(request, "can_use_documents")
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.vault_rotate_key()
        except EngineError as exc:
            logger.info("applicant vault key rotation failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    return router
