"""Setup / OOBE router — LLM-settings gate + tier ladder + wizard (FR-OOBE, FR-UI-5).

The FIRST UI deliverable: settings endpoints plus the gate. Posting valid LLM
settings opens the gate; gated routers depend on ``require_llm_configured``. All
setup is zero-CLI (NFR-ZEROCLI-1): provider/model/endpoint/key + the reorderable
tier ladder (FR-LLM-2/3) and per-step wizard advance (FR-OOBE-2) are all here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from applicant.app.deps import get_container, get_setup_service
from applicant.ports.driving.setup_wizard import (
    LLMSettings,
    SandboxConnectionSettings,
    TierSettings,
    WizardStatus,
    WizardStep,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


class LLMSettingsIn(BaseModel):
    provider: str
    base_url: str = ""
    api_key: str = ""
    model: str
    context_window: int = 8192


class TierIn(BaseModel):
    provider: str
    base_url: str = ""
    model: str
    api_key: str = ""
    # The non-secret marker the UI got back from GET /llm/tiers. Sent back (with a
    # blank api_key) to keep an already-sealed key across an edit/reorder (FR-LLM-3).
    api_key_ref: str = ""
    context_window: int = 8192


class LadderIn(BaseModel):
    tiers: list[TierIn] = Field(min_length=1)


class ChannelsIn(BaseModel):
    discord_webhook_url: str = ""
    apprise_urls: str = ""  # email/SMTP/other Apprise URLs (comma-separated)
    #: ntfy push topic URL(s), comma-separated (e.g. ``ntfy://ntfy.sh/my-topic``).
    #: Opt-in mobile push for urgent action alerts (FR-NOTIF-1); empty leaves the
    #: persisted value (and the NTFY_URL boot default) untouched.
    ntfy_url: str = ""
    #: UI-configurable email-escalation delay in minutes (FR-NOTIF-2); None = leave
    #: the persisted value (default 15) untouched.
    email_timeout_minutes: int | None = None


class QuietHoursIn(BaseModel):
    """Quiet-hours window for approvals/digests (FR-NOTIF-5).

    ``enabled=False`` is 24/7 mode (always notify). When enabled, approval/digest
    push channels (Discord/email) are held until the window ends; in-app always
    surfaces and ERRORS are never deferred. Times are HH:MM in ``tz`` (UTC when blank).
    """

    enabled: bool = False
    start: str = "22:00"
    end: str = "07:00"
    tz: str = ""
    #: Per-channel quiet preference (#302): ``True`` = the channel respects quiet
    #: hours; ``False`` = it still delivers overnight. ``None`` leaves the saved value.
    discord_respects_quiet: bool | None = None
    email_respects_quiet: bool | None = None


class SandboxConnectionIn(BaseModel):
    """Native Proxmox Windows VM connection + login data (FR-OOBE, zero-CLI).

    Secrets (``proxmox_token_secret``, ``rdp_password``) are sealed in the credential
    vault and NEVER returned/logged (FR-VAULT-3). Non-secrets persist to app-config.
    """

    proxmox_api_url: str
    proxmox_node: str
    proxmox_token_id: str
    proxmox_token_secret: str  # SECRET -> vault
    template_vmid: int
    clone_mode: str = "snapshot-revert"
    cdp_host: str = ""
    cdp_port: int = 9222
    rdp_username: str = ""
    rdp_password: str = ""  # SECRET -> vault
    takeover_method: str = "rdp"
    takeover_url_template: str = ""


class EndpointModelIn(BaseModel):
    endpoint_id: str
    model: str


class AutomationPrefsIn(BaseModel):
    """Settings > Automation body (dark-engine audit items 82/84/85/87/88).

    All fields optional / ``None`` = leave the persisted value untouched
    (mirrors ``QuietHoursIn``'s partial-update convention), so the browser can
    PUT just the one control the operator changed.
    """

    egress_timezone: str | None = None
    egress_locale: str | None = None
    allow_automated_accounts: bool | None = None
    presubmit_max_apps_per_company_per_day: int | None = None
    #: Item 87: how many days parsed PII/EEO/intake data is kept; 0 = forever.
    pii_retention_days: int | None = None
    #: Item 88: how many days before re-applying to the same company/role.
    presubmit_duplicate_cooldown_days: int | None = None


def _status_dict(svc) -> dict:
    s: WizardStatus = svc.status()
    out = {
        "llm_configured": s.llm_configured,
        "channels_configured": s.channels_configured,
        "fonts_ready": s.fonts_ready,
        "onboarding_complete": s.onboarding_complete,
        "current_step": s.current_step,
        "steps_complete": s.steps_complete,
        "gate_open": svc.is_setup_gate_open(),
        "automated_work_allowed": svc.is_automated_work_allowed(),
        # Engine-proposed attributes awaiting operator approval (#273). Always present
        # (empty by default) so the front-door "suggested attribute" card has a stable
        # data source it can reveal when suggestions exist.
        "suggested_attributes": svc.suggested_attributes(),
    }
    # Surface WHY applying is still blocked: the required-to-apply essentials that are
    # still missing + a plain reason, computed from real campaign data. Lets the front
    # door + chat show "I can't start applying until I know: ..." with progress.
    readiness = svc.apply_readiness()
    if readiness is not None:
        out["apply_ready"] = readiness.ready
        out["apply_missing"] = list(readiness.missing)
        out["apply_blocked_reason"] = "" if readiness.ready else readiness.reason
    return out


@router.get("/status")
def get_status(svc=Depends(get_setup_service)) -> dict:
    return _status_dict(svc)


@router.post("/llm", status_code=status.HTTP_204_NO_CONTENT)
def configure_llm(body: LLMSettingsIn, svc=Depends(get_setup_service)) -> None:
    try:
        svc.configure_llm(
            LLMSettings(
                provider=body.provider,
                base_url=body.base_url,
                api_key=body.api_key,
                model=body.model,
                context_window=body.context_window,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/llm/from-endpoint", status_code=status.HTTP_204_NO_CONTENT)
def configure_llm_from_endpoint(
    body: EndpointModelIn, container=Depends(get_container)
) -> None:
    """Set the chat model from a saved endpoint + chosen model (setup AI section).

    The browser sends only the endpoint id + model name; the server resolves the
    sealed API key for that endpoint and wires it into the LLM ladder, so the model
    the user picks on the setup page is the one the app actually uses.
    """
    svc = container.setup_service
    ep_svc = container.model_endpoint_service

    def _resolve() -> dict | None:
        rec = ep_svc.get_endpoint(body.endpoint_id)
        if rec is None:
            return None
        return {
            "base_url": rec.get("base_url", ""),
            "api_key": ep_svc._resolve_key(rec),
            "name": rec.get("name", ""),
        }

    try:
        svc.configure_llm_from_endpoint(endpoint_resolver=_resolve, model=body.model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _routing_status(container) -> dict:
    """Real-time smart-router state for the model-ladder UI (dark-engine audit item 74).

    The router silently reorders the walked tier order every resolve, so the ladder
    editor alone can't tell a user which endpoint is actually serving requests. This
    reads the SAME router instance the live LLM adapter uses (``container.llm_router``)
    — never a fabricated/guessed value — so what's shown always matches reality.
    ``enabled=False`` covers both "smart routing is off" (the ladder runs in its
    configured order unchanged) and "no router is wired" (no smart-routing endpoints
    configured yet).
    """
    settings = container.settings
    out: dict[str, Any] = {
        "enabled": bool(settings.llm_smart_routing),
        "prefer_local": bool(settings.llm_smart_routing_prefer_local),
        "active_endpoint": None,
        "reordered": False,
        "health": None,
    }
    router = container.llm_router
    if not out["enabled"] or router is None:
        return out
    from applicant.ports.driven.llm_router import CostTier, TaskType

    try:
        out["health"] = router.health()
    except Exception:  # pragma: no cover - defensive, mirrors order_ladder_by_router
        out["health"] = None
    try:
        cost_tier = CostTier.LOWEST if out["prefer_local"] else CostTier.BALANCED
        selected = router.select_endpoint(
            TaskType.CHAT, cost_tier=cost_tier, prefer_local=out["prefer_local"]
        )
    except Exception:  # pragma: no cover - defensive, mirrors order_ladder_by_router
        selected = None
    if not selected:
        return out
    out["active_endpoint"] = {
        "name": selected.get("name", ""),
        "base_url": selected.get("base_url", ""),
    }
    tiers = container.setup_service.get_tiers()
    first_base = _norm_base(tiers[0].get("base_url", "")) if tiers else ""
    if first_base:
        out["reordered"] = _norm_base(selected.get("base_url", "")) != first_base
    return out


def _norm_base(url: str) -> str:
    return (url or "").strip().lower().rstrip("/")


@router.get("/llm/tiers")
def get_tiers(svc=Depends(get_setup_service), container=Depends(get_container)) -> dict:
    """Return the persisted tier ladder (secrets omitted) plus live routing status.

    ``routing`` reports which endpoint the smart router actually picked and whether
    that reorders the configured Level-1 tier (dark-engine audit item 74) — see
    ``_routing_status``.
    """
    return {"tiers": svc.get_tiers(), "routing": _routing_status(container)}


@router.put("/llm/tiers", status_code=status.HTTP_204_NO_CONTENT)
def set_tiers(body: LadderIn, svc=Depends(get_setup_service)) -> None:
    """Reorder / add / remove tiers (1-N, default 3 in the UI) (FR-LLM-3)."""
    try:
        svc.set_tiers(
            [
                TierSettings(
                    provider=t.provider,
                    base_url=t.base_url,
                    model=t.model,
                    api_key=t.api_key,
                    api_key_ref=t.api_key_ref,
                    context_window=t.context_window,
                )
                for t in body.tiers
            ]
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/channels")
def get_channels(svc=Depends(get_setup_service)) -> dict:
    """Return channel config status (no secrets) for the wizard (FR-OOBE-2).

    Also returns the current quiet-hours window (FR-NOTIF-5) so the Notifications
    panel can render the same control in both the wizard and Settings.
    """
    chan = svc.get_channels()
    return {
        "discord_configured": bool(chan.get("discord_webhook_url")),
        "email_configured": bool(chan.get("apprise_urls")),
        "ntfy_configured": bool(chan.get("ntfy_url")),
        "channels_configured": svc.channels_configured(),
        "quiet_hours": svc.get_quiet_hours(),
        "email_timeout_minutes": svc.get_email_timeout_minutes(),
    }


@router.post("/channels", status_code=status.HTTP_204_NO_CONTENT)
def configure_channels(body: ChannelsIn, container=Depends(get_container)) -> None:
    """Set notification channels (Discord/email via Apprise) (FR-NOTIF-1, FR-OOBE-2/3).

    Configuring Discord + email marks the channel gate complete and, combined with
    LLM + onboarding, ungates automated work (FR-OOBE-3). The live notifier is
    reconfigured in place so no restart is needed (zero-CLI).
    """
    if not (
        body.discord_webhook_url
        or body.apprise_urls
        or body.ntfy_url
        or body.email_timeout_minutes is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add a Discord webhook and/or an email address so notifications can reach you.",
        )
    container.setup_service.configure_channels(
        discord_webhook_url=body.discord_webhook_url,
        apprise_urls=body.apprise_urls,
        ntfy_url=body.ntfy_url,
        email_timeout_minutes=body.email_timeout_minutes,
    )
    if hasattr(container.notification, "configure"):
        # Reconfigure the live notifier in place (zero-CLI). Use the persisted,
        # clamped email-timeout so the running ladder matches what was saved.
        container.notification.configure(
            discord_webhook_url=body.discord_webhook_url or None,
            apprise_urls=body.apprise_urls or None,
            ntfy_url=body.ntfy_url or None,
            email_timeout_seconds=container.setup_service.get_email_timeout_minutes() * 60,
        )


@router.get("/channels/quiet-hours")
def get_quiet_hours(svc=Depends(get_setup_service)) -> dict:
    """Return the persisted quiet-hours window for the UI (FR-NOTIF-5)."""
    return svc.get_quiet_hours()


@router.post("/channels/quiet-hours", status_code=status.HTTP_204_NO_CONTENT)
def configure_quiet_hours(body: QuietHoursIn, container=Depends(get_container)) -> None:
    """Set the quiet-hours window for approvals/digests (FR-NOTIF-5).

    Errors always surface immediately, any hour — quiet hours only defer NORMAL
    approval/digest push channels (in-app always surfaces). ``enabled=False`` is
    24/7 mode. Persists the window and reconfigures the live notifier in place so no
    restart is needed (zero-CLI).
    """
    try:
        container.setup_service.set_quiet_hours(
            enabled=body.enabled,
            start=body.start,
            end=body.end,
            tz=body.tz,
            discord_respects=body.discord_respects_quiet,
            email_respects=body.email_respects_quiet,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if hasattr(container.notification, "configure"):
        qh = container.setup_service.get_quiet_hours()
        container.notification.configure(
            quiet_hours=(qh["start"], qh["end"]) if qh["enabled"] else None,
            quiet_tz=qh["tz"],
            # #302: push the per-channel quiet preference to the live notifier so
            # "hold Discord overnight, let email through" takes effect with no restart.
            quiet_hours_channels=container.setup_service.get_quiet_hours_channels(),
            always_on=not qh["enabled"],
        )


@router.post("/channels/test")
def test_channels(container=Depends(get_container)) -> dict:
    """Send a test notification across configured channels (FR-NOTIF-1).

    Hermetic by default (the notifier captures offline); a live deployment sends
    for real. Returns the channels the test would fire on.
    """
    from applicant.ports.driven.notification import Notification, NotificationUrgency

    notification = container.notification
    handle = notification.notify(
        Notification(
            title="Applicant test notification",
            body="Channels are configured and working.",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="channels-test",
        )
    )
    channels = (
        notification.configured_channels()
        if hasattr(notification, "configured_channels")
        else []
    )
    # UX honesty: the default lane captures the test in memory and sends NOTHING over
    # the wire. Surface that so "Send a test" doesn't claim delivery it didn't make —
    # only NOTIFICATIONS_LIVE actually delivers (FR-NOTIF-1).
    live = notification.is_live() if hasattr(notification, "is_live") else True
    result = {"sent": True, "live": live, "handle": handle, "channels": channels}
    if not live:
        result["note"] = "dry run — set NOTIFICATIONS_LIVE=true to deliver"
    return result


@router.get("/sandbox-connection")
def get_sandbox_connection(svc=Depends(get_setup_service)) -> dict:
    """Return the persisted Proxmox Windows connection (NO secrets) for the UI (FR-OOBE)."""
    return {
        "backend": svc.sandbox_backend,
        "connection": svc.get_sandbox_connection(),
        "configured": svc.sandbox_connection_configured(),
        "backend_ready": svc.is_sandbox_backend_ready(),
    }


@router.post("/sandbox-connection", status_code=status.HTTP_204_NO_CONTENT)
def configure_sandbox_connection(
    body: SandboxConnectionIn, svc=Depends(get_setup_service)
) -> None:
    """Collect + persist the native Proxmox Windows VM connection/login data (FR-OOBE).

    Secrets (Proxmox API token secret + RDP password) are sealed in the credential
    vault; non-secrets persist to app-config. Completing this step ungates the
    proxmox-windows backend (FR-SANDBOX-1). Zero-CLI (NFR-ZEROCLI-1).
    """
    try:
        svc.configure_sandbox_connection(
            SandboxConnectionSettings(
                proxmox_api_url=body.proxmox_api_url,
                proxmox_node=body.proxmox_node,
                proxmox_token_id=body.proxmox_token_id,
                proxmox_token_secret=body.proxmox_token_secret,
                template_vmid=body.template_vmid,
                clone_mode=body.clone_mode,
                cdp_host=body.cdp_host,
                cdp_port=body.cdp_port,
                rdp_username=body.rdp_username,
                rdp_password=body.rdp_password,
                takeover_method=body.takeover_method,
                takeover_url_template=body.takeover_url_template,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/automation")
def get_automation_prefs(
    svc=Depends(get_setup_service), container=Depends(get_container)
) -> dict:
    """Settings > Automation (dark-engine audit items 82/84/85/87/88).

    Merges the persisted overrides onto the env-sourced ``Settings`` defaults so
    the UI always shows the value the running engine actually uses today, even
    before an operator has ever saved anything here.
    """
    settings = container.settings
    stored = svc.get_automation_prefs()
    return {
        "egress_timezone": stored.get("egress_timezone", settings.egress_timezone),
        "egress_locale": stored.get("egress_locale", settings.egress_locale),
        "allow_automated_accounts": stored.get(
            "allow_automated_accounts", settings.allow_automated_accounts
        ),
        "presubmit_max_apps_per_company_per_day": stored.get(
            "presubmit_max_apps_per_company_per_day",
            settings.presubmit_max_apps_per_company_per_day,
        ),
        "pii_retention_days": stored.get(
            "pii_retention_days", settings.pii_retention_days
        ),
        "presubmit_duplicate_cooldown_days": stored.get(
            "presubmit_duplicate_cooldown_days",
            settings.presubmit_duplicate_cooldown_days,
        ),
    }


@router.put("/automation", status_code=status.HTTP_204_NO_CONTENT)
def set_automation_prefs(body: AutomationPrefsIn, svc=Depends(get_setup_service)) -> None:
    """Save Settings > Automation overrides (dark-engine audit items 82/84/85/87/88)."""
    try:
        svc.set_automation_prefs(
            egress_timezone=body.egress_timezone,
            egress_locale=body.egress_locale,
            allow_automated_accounts=body.allow_automated_accounts,
            presubmit_max_apps_per_company_per_day=body.presubmit_max_apps_per_company_per_day,
            pii_retention_days=body.pii_retention_days,
            presubmit_duplicate_cooldown_days=body.presubmit_duplicate_cooldown_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/advance/{step}")
def advance_step(step: str, svc=Depends(get_setup_service)) -> dict:
    """Mark a wizard step complete and return the new status (FR-OOBE-2)."""
    try:
        wizard_step = WizardStep(step)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown step: {step}"
        ) from exc
    try:
        svc.advance_step(wizard_step)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _status_dict(svc)
