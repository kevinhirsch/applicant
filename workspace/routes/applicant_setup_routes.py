# routes/applicant_setup_routes.py
"""Applicant SETUP / ONBOARDING proxy — the workspace-side endpoints the first-run
setup wizard calls to drive the engine's out-of-box configuration.

This backs the front-door setup wizard (``static/js/applicantOnboarding.js``): a
blocking, resumable overlay that runs right after the user logs in and walks them
through (1) connecting an LLM, (2) notification channels, (3) fonts, and (4) the
Workday-ready onboarding intake + base-resume upload with a LaTeX-conversion
accept/reject gate. On completion the engine's gate opens and the feature layer
(`/api/applicant/features`) flips the job sections active.

Like the other Stage-2 lanes this is a thin, auth-protected proxy in front of the
engine. Every handler delegates to :class:`src.applicant_engine.ApplicantEngineClient`
so URLs + error handling live in exactly one place, and the engine's own gating
(``require_llm_configured`` / ``require_automated_work``) is reused unchanged — the
wizard only DRIVES the user to completion, it never re-implements the gate.

Design notes:

* **No business logic here.** Each route maps 1:1 to an engine endpoint and hands
  back the engine's JSON unchanged so the wizard renders the same shapes.
* **Graceful degradation.** The engine client raises the typed
  :class:`EngineError` for timeouts / connection failures / HTTP 4xx-5xx; we
  translate those to a clean JSON error with a sensible status (502 when the
  engine is unreachable, or the engine's own status when it answered) instead of
  leaking a 500 + traceback.
* **Auth + owner scope.** Mounted on the normal authenticated surface. Reads
  require a logged-in user; the mutating/configuration operations additionally
  require the ``can_configure`` privilege so a restricted account can't drive the
  owner's setup. Multipart uploads (fonts / base resume) are bounded by the
  engine's own size caps.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.applicant_engine import ApplicantEngineClient, EngineError
from src.auth_helpers import require_privilege, require_user

logger = logging.getLogger(__name__)

#: Privilege required to mutate setup/config (owner-scoped). Unknown privileges
#: fail open in ``require_privilege`` (the owner/admin always passes), matching
#: the other lanes; a restricted sub-user can't reconfigure the engine.
_CONFIG_PRIV = "can_configure"

#: Maximum file size for setup uploads (fonts, resume). Mirrors the engine caps.
MAX_APPLICANT_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _engine_error_response(exc: EngineError) -> JSONResponse:
    """Translate a typed :class:`EngineError` into a clean JSON error response.

    * timeout / connection failure (``status is None``) -> 502 Bad Gateway.
    * 4xx: passed through (client-correctable: 400 bad LLM settings, 409
      onboarding incomplete) so the wizard can react.
    * 5xx: scrubbed — raw detail may contain internal stack traces or state;
      logged server-side and a generic message returned to the browser.
    """
    if exc.status is None:
        message = (
            "The application engine timed out."
            if exc.is_timeout
            else "The application engine is unavailable."
        )
        return JSONResponse(
            status_code=502,
            content={"error": "engine_error", "message": message, "engine_status": None},
        )
    if exc.status >= 500:
        logger.warning("engine 5xx (setup): status=%s detail=%s", exc.status, exc.detail or exc.message)
        return JSONResponse(
            status_code=502,
            content={"error": "engine_error", "message": "The application engine reported an error.", "engine_status": exc.status},
        )
    # 4xx: pass the engine's detail through so the wizard can react precisely
    # (e.g. 400 bad LLM settings, 409 onboarding incomplete with section list).
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": "engine_error",
            "message": "The application engine reported an error.",
            "engine_status": exc.status,
            "detail": exc.detail,
        },
    )


# --- request bodies ---------------------------------------------------------


class LLMIn(BaseModel):
    provider: str
    base_url: str = ""
    api_key: str = ""
    model: str
    context_window: int = 8192


class LLMFromEndpointIn(BaseModel):
    endpoint_id: str
    model: str


class TierItemIn(BaseModel):
    provider: str
    base_url: str = ""
    model: str
    api_key: str = ""
    api_key_ref: str = ""  # carried back to keep an existing key across edit/reorder
    context_window: int = 8192


class LadderIn(BaseModel):
    tiers: list[TierItemIn]


class ChannelsIn(BaseModel):
    """Thin proxy body mirroring the engine's own ``ChannelsIn`` (setup.py).

    Fields are ``Optional`` (default ``None``) rather than defaulting to ``""``
    so we can tell "field entirely absent from the request" (leave the saved
    value alone) apart from "field explicitly sent as an empty string" (the
    caller is asking to clear it) — see ``configure_channels`` below, which
    only forwards the fields the caller actually set (``exclude_unset``)
    instead of always sending all four keys. NOTE: the engine's own
    ``configure_channels`` (src/applicant/application/services/setup_service.py)
    currently treats ANY falsy value — explicit "" included — as "leave
    unchanged" (``if discord_webhook_url: ...``), so there is today no engine
    contract for actually clearing a previously-configured channel; this proxy
    forwards the caller's intent faithfully but cannot manufacture support the
    engine doesn't have.
    """

    discord_webhook_url: str | None = None
    apprise_urls: str | None = None
    #: ntfy push topic URL(s), comma-separated (e.g. ntfy://ntfy.sh/my-topic).
    ntfy_url: str | None = None
    #: UI-configurable email-escalation delay in minutes (FR-NOTIF-2).
    email_timeout_minutes: int | None = None


class QuietHoursIn(BaseModel):
    """Quiet-hours window for approvals/digests (FR-NOTIF-5).

    ``enabled=False`` is 24/7 mode (always notify). Errors always surface
    immediately, any hour — quiet hours only defer approval/digest push channels.
    Times are HH:MM in ``tz`` (UTC when blank). Thin proxy mirroring the engine.
    """

    enabled: bool = False
    start: str = "22:00"
    end: str = "07:00"
    tz: str = ""
    #: Per-channel quiet preference (#302): ``True`` = the channel respects quiet
    #: hours; ``False`` = it still delivers overnight. ``None`` leaves the saved
    #: value. Mirrors the engine's own ``QuietHoursIn`` (setup.py) — must stay
    #: declared here too, or pydantic silently strips these before forwarding.
    discord_respects_quiet: bool | None = None
    email_respects_quiet: bool | None = None


class SectionIn(BaseModel):
    section: str
    data: dict = {}


class ConfirmConflictIn(BaseModel):
    attribute: str
    value: str


class CreateCampaignIn(BaseModel):
    name: str


class ConversionPreviewIn(BaseModel):
    source: str = ""


class AutomationPrefsIn(BaseModel):
    """Settings > Automation body (dark-engine audit items 82/84/85/87/88).

    Thin proxy body mirroring the engine's own ``AutomationPrefsIn`` (setup.py):
    all fields ``Optional`` (default ``None``) so a save from one control never
    clobbers the others (``None`` = leave the persisted value alone).
    """

    egress_timezone: str | None = None
    egress_locale: str | None = None
    allow_automated_accounts: bool | None = None
    presubmit_max_apps_per_company_per_day: int | None = None
    pii_retention_days: int | None = None
    presubmit_duplicate_cooldown_days: int | None = None


class SandboxConnectionIn(BaseModel):
    """Native Windows automation-sandbox connection (Proxmox VM) + login.

    Secrets (``proxmox_token_secret`` + ``rdp_password``) are sealed in the
    engine's credential vault and never returned/logged; non-secrets persist to
    app-config. This is a thin proxy body mirroring the engine's contract.
    """

    proxmox_api_url: str
    proxmox_node: str
    proxmox_token_id: str
    proxmox_token_secret: str = ""
    template_vmid: int
    clone_mode: str = "snapshot-revert"
    cdp_host: str = ""
    cdp_port: int = 9222
    rdp_username: str = ""
    rdp_password: str = ""
    takeover_method: str = "rdp"
    takeover_url_template: str = ""


def setup_applicant_setup_routes() -> APIRouter:
    """Build the Applicant setup/onboarding proxy router (mounted in ``app.py``)."""
    router = APIRouter(prefix="/api/applicant/setup", tags=["applicant-setup"])

    # ── wizard status / gate ────────────────────────────────────────────

    @router.get("/status")
    async def status(request: Request) -> JSONResponse:
        """Engine wizard/gate status: which steps are complete + gate flags."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_status()
        except EngineError as exc:
            logger.info("applicant setup status unavailable: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/advance/{step}")
    async def advance(step: str, request: Request) -> JSONResponse:
        """Mark a wizard step complete and return the new status."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_advance(step)
        except EngineError as exc:
            logger.info("applicant setup advance failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── step 1: LLM ─────────────────────────────────────────────────────

    @router.post("/llm")
    async def configure_llm(body: LLMIn, request: Request) -> JSONResponse:
        """Save the LLM provider/model/key (opens the engine gate)."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                await engine.setup_configure_llm(body.model_dump())
        except EngineError as exc:
            logger.info("applicant configure llm failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content={"ok": True})

    @router.post("/llm/from-endpoint")
    async def configure_llm_from_endpoint(
        body: LLMFromEndpointIn, request: Request
    ) -> JSONResponse:
        """Set the chat model from a saved endpoint + chosen model."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                await engine.setup_configure_llm_from_endpoint(body.model_dump())
        except EngineError as exc:
            logger.info("applicant configure llm from-endpoint failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content={"ok": True})

    @router.get("/llm/tiers")
    async def get_llm_tiers(request: Request) -> JSONResponse:
        """The model escalation ladder (Level 1 → N), secrets omitted (FR-LLM-3)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_get_tiers()
        except EngineError as exc:
            logger.debug("get llm tiers: engine unavailable: %s", exc)
            return JSONResponse(content={"tiers": [], "engine_available": False})
        out = data if isinstance(data, dict) else {"tiers": data or []}
        out.setdefault("tiers", [])
        out["engine_available"] = True
        return JSONResponse(content=out)

    @router.put("/llm/tiers")
    async def set_llm_tiers(body: LadderIn, request: Request) -> JSONResponse:
        """Reorder / add / remove model tiers (1–N; position = escalation level)."""
        require_privilege(request, _CONFIG_PRIV)
        if not body.tiers:
            raise HTTPException(status_code=400, detail="Add at least one model tier.")
        try:
            async with ApplicantEngineClient() as engine:
                await engine.setup_set_tiers(body.model_dump())
        except EngineError as exc:
            logger.info("applicant set llm tiers failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content={"ok": True})

    # model endpoints (paste a base URL -> auto-list its models)
    @router.get("/model-endpoints")
    async def list_model_endpoints(request: Request, refresh: bool = False) -> JSONResponse:
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.list_model_endpoints(refresh=refresh)
        except EngineError as exc:
            logger.info("applicant list model endpoints failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/model-endpoints")
    async def add_model_endpoint(
        request: Request,
        base_url: str = Form(""),
        api_key: str = Form(""),
        name: str = Form(""),
        model_type: str = Form("llm"),
    ) -> JSONResponse:
        """Add a model source and live-list its models (provider catalog / tags)."""
        require_privilege(request, _CONFIG_PRIV)
        payload = {
            "base_url": base_url,
            "api_key": api_key,
            "name": name,
            "model_type": model_type,
        }
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.add_model_endpoint(payload)
        except EngineError as exc:
            logger.info("applicant add model endpoint failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/model-endpoints/test")
    async def test_model_endpoint(
        request: Request,
        base_url: str = Form(""),
        api_key: str = Form(""),
    ) -> JSONResponse:
        """Probe a model source without saving it (the 'Test' button)."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.test_model_endpoint(
                    {"base_url": base_url, "api_key": api_key}
                )
        except EngineError as exc:
            logger.info("applicant test model endpoint failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.get("/model-endpoints/{endpoint_id}/models")
    async def model_endpoint_models(
        endpoint_id: str, request: Request, refresh: bool = False
    ) -> JSONResponse:
        """Live model list for one saved endpoint (populates the model dropdown)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.model_endpoint_models(endpoint_id, refresh=refresh)
        except EngineError as exc:
            logger.info("applicant model endpoint models failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── step 2: notification channels (gating) ──────────────────────────

    @router.get("/channels")
    async def get_channels(request: Request) -> JSONResponse:
        """Channel config status (no secrets)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_get_channels()
        except EngineError as exc:
            logger.info("applicant get channels failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/channels")
    async def configure_channels(body: ChannelsIn, request: Request) -> JSONResponse:
        """Save Discord and/or email notification channels.

        Only fields the caller actually included in the request body are
        forwarded (``exclude_unset``) — a field left out entirely means "leave
        the saved value alone", while an explicit ``""`` is a caller intent to
        clear the channel and is forwarded as such rather than silently
        dropped or coerced into "leave unchanged". Whether the engine actually
        honors an explicit clear for a given field is up to its own contract
        (see the ``ChannelsIn`` docstring above) — this proxy does not swallow
        or reject the attempt either way.
        """
        require_privilege(request, _CONFIG_PRIV)
        payload = body.model_dump(exclude_unset=True)
        try:
            async with ApplicantEngineClient() as engine:
                await engine.setup_configure_channels(payload)
        except EngineError as exc:
            logger.info("applicant configure channels failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content={"ok": True})

    @router.post("/channels/test")
    async def test_channels(request: Request) -> JSONResponse:
        """Send a test notification across configured channels."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_test_channels()
        except EngineError as exc:
            logger.info("applicant test channels failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── quiet hours (FR-NOTIF-5): defer approvals/digests, errors always go ──

    @router.get("/channels/quiet-hours")
    async def get_quiet_hours(request: Request) -> JSONResponse:
        """Current quiet-hours window (enabled/start/end/tz)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_get_quiet_hours()
        except EngineError as exc:
            logger.info("applicant get quiet hours failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/channels/quiet-hours")
    async def configure_quiet_hours(body: QuietHoursIn, request: Request) -> JSONResponse:
        """Save the quiet-hours window (or 24/7 mode when disabled)."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                await engine.setup_configure_quiet_hours(body.model_dump())
        except EngineError as exc:
            logger.info("applicant configure quiet hours failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content={"ok": True})

    # ── automation sandbox backend (FR-SANDBOX-1) ──────────────────────

    @router.get("/sandbox-connection")
    async def get_sandbox_connection(request: Request) -> JSONResponse:
        """Persisted Windows automation-sandbox connection (no secrets) + readiness."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_get_sandbox_connection()
        except EngineError as exc:
            logger.info("applicant get sandbox connection failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/sandbox-connection")
    async def configure_sandbox_connection(
        body: SandboxConnectionIn, request: Request
    ) -> JSONResponse:
        """Save the native Windows VM connection/login (secrets vaulted by engine)."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                await engine.setup_configure_sandbox_connection(body.model_dump())
        except EngineError as exc:
            logger.info("applicant configure sandbox connection failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content={"ok": True})

    # ── Settings > Automation (dark-engine audit items 82/84/85) ───────

    @router.get("/automation")
    async def get_automation_prefs(request: Request) -> JSONResponse:
        """Browser fingerprint timezone/locale, the automated-account-creation
        opt-in, and the per-company daily application cap -- merged onto the
        engine's env defaults so this always reflects a real, effective value."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_get_automation_prefs()
        except EngineError as exc:
            logger.info("applicant get automation prefs failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.put("/automation")
    async def set_automation_prefs(body: AutomationPrefsIn, request: Request) -> JSONResponse:
        """Save Settings > Automation overrides (owner-scoped config change)."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                await engine.setup_set_automation_prefs(
                    body.model_dump(exclude_unset=True)
                )
        except EngineError as exc:
            logger.info("applicant set automation prefs failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content={"ok": True})

    # ── step 3: fonts ───────────────────────────────────────────────────

    @router.get("/fonts")
    async def list_fonts(request: Request) -> JSONResponse:
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.list_fonts()
        except EngineError as exc:
            logger.info("applicant list fonts failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/fonts/detect")
    async def detect_fonts(request: Request, file: UploadFile = File(...)) -> JSONResponse:
        """Detect required/missing fonts for an uploaded resume."""
        require_privilege(request, _CONFIG_PRIV)
        content = await file.read()
        if len(content) > MAX_APPLICANT_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload too large: max {MAX_APPLICANT_UPLOAD_BYTES} bytes."
            )
        files = {"file": (file.filename or "resume", content, file.content_type)}
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.detect_fonts(files)
        except EngineError as exc:
            logger.info("applicant detect fonts failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/fonts/install")
    async def install_font(
        request: Request, name: str = Form(...), file: UploadFile = File(...)
    ) -> JSONResponse:
        """Install an uploaded missing font file."""
        require_privilege(request, _CONFIG_PRIV)
        content = await file.read()
        if len(content) > MAX_APPLICANT_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload too large: max {MAX_APPLICANT_UPLOAD_BYTES} bytes."
            )
        files = {"file": (file.filename or f"{name}.ttf", content, file.content_type)}
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.install_font(files, {"name": name})
        except EngineError as exc:
            logger.info("applicant install font failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── campaigns (the intake attaches to a campaign) ───────────────────

    @router.get("/campaigns")
    async def list_campaigns(request: Request) -> JSONResponse:
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.list_campaigns()
        except EngineError as exc:
            logger.info("applicant list campaigns failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/campaigns")
    async def create_campaign(body: CreateCampaignIn, request: Request) -> JSONResponse:
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.create_campaign(body.name)
        except EngineError as exc:
            logger.info("applicant create campaign failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── step 4: onboarding intake (resumable) ───────────────────────────

    @router.get("/onboarding/{campaign_id}")
    async def onboarding_state(campaign_id: str, request: Request) -> JSONResponse:
        """Get / resume the intake state (which sections are done + saved data)."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.onboarding_state(campaign_id)
        except EngineError as exc:
            logger.info("applicant onboarding state failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.get("/gaps/{campaign_id}")
    async def profile_gaps(campaign_id: str, request: Request) -> JSONResponse:
        """A completeness checklist: which core profile attributes (name/email/
        phone/title) and search criteria are still missing (dark-engine audit item
        51). The assistant chat already computes this internally as hidden
        context; this exposes the same gap list as a plain read."""
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.setup_get_gaps(campaign_id)
        except EngineError as exc:
            logger.info("applicant profile gaps failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/onboarding/{campaign_id}/section")
    async def onboarding_section(
        campaign_id: str, body: SectionIn, request: Request
    ) -> JSONResponse:
        """Persist one intake section's partial state (resumable)."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.onboarding_section(campaign_id, body.model_dump())
        except EngineError as exc:
            logger.info("applicant onboarding section failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/onboarding/{campaign_id}/base-resume")
    async def onboarding_base_resume(
        campaign_id: str, request: Request, file: UploadFile = File(...)
    ) -> JSONResponse:
        """Upload the base resume; engine parses + reconciles the attribute cloud."""
        require_privilege(request, _CONFIG_PRIV)
        content = await file.read()
        if len(content) > MAX_APPLICANT_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Upload too large: max {MAX_APPLICANT_UPLOAD_BYTES} bytes."
            )
        files = {"file": (file.filename or "resume.txt", content, file.content_type)}
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.onboarding_base_resume(campaign_id, files)
        except EngineError as exc:
            logger.info("applicant base resume upload failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/onboarding/{campaign_id}/confirm-conflict")
    async def onboarding_confirm_conflict(
        campaign_id: str, body: ConfirmConflictIn, request: Request
    ) -> JSONResponse:
        """Apply a flagged integral change after explicit confirmation."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.onboarding_confirm_conflict(
                    campaign_id, body.model_dump()
                )
        except EngineError as exc:
            logger.info("applicant confirm conflict failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/onboarding/{campaign_id}/complete")
    async def onboarding_complete(campaign_id: str, request: Request) -> JSONResponse:
        """Set the completion flag iff every required section is present."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.onboarding_complete(campaign_id)
        except EngineError as exc:
            logger.info("applicant onboarding complete failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    # ── LaTeX conversion preview + accept/reject (FR-RESUME-3a) ─────────

    @router.get("/conversion/{campaign_id}/engine")
    async def conversion_engine(campaign_id: str, request: Request) -> JSONResponse:
        require_user(request)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.conversion_engine(campaign_id)
        except EngineError as exc:
            logger.info("applicant conversion engine failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/conversion/{campaign_id}/preview")
    async def conversion_preview(
        campaign_id: str, body: ConversionPreviewIn, request: Request
    ) -> JSONResponse:
        """Compile the LaTeX conversion of the base resume for accept/reject."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.conversion_preview(campaign_id, body.source)
        except EngineError as exc:
            logger.info("applicant conversion preview failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/conversion/{campaign_id}/accept")
    async def conversion_accept(campaign_id: str, request: Request) -> JSONResponse:
        """ACCEPT -> the LaTeX conversion becomes the campaign's primary engine."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.conversion_accept(campaign_id)
        except EngineError as exc:
            logger.info("applicant conversion accept failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    @router.post("/conversion/{campaign_id}/reject")
    async def conversion_reject(campaign_id: str, request: Request) -> JSONResponse:
        """REJECT -> fall back to the original document engine."""
        require_privilege(request, _CONFIG_PRIV)
        try:
            async with ApplicantEngineClient() as engine:
                data = await engine.conversion_reject(campaign_id)
        except EngineError as exc:
            logger.info("applicant conversion reject failed: %s", exc)
            return _engine_error_response(exc)
        return JSONResponse(content=data)

    return router
