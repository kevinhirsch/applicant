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

from applicant.app.deps import get_chat_service, get_container, get_setup_service
from applicant.core.ids import CampaignId
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
    """Settings > Automation body (dark-engine audit items
    82/83/84/85/86/87/88/89/90/91/92/93/94/95/96/97/98/99/100/101/102/103/104/105/106/107).

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
    #: How many days a pending final-approval waits before timing out (item 90).
    approval_timeout_days: int | None = None
    #: Fine-grained override for the approval wait, in seconds; takes precedence
    #: over ``approval_timeout_days`` when set (item 90).
    approval_wait_seconds: float | None = None
    #: How often (in seconds) the 24/7 loop ticks (item 86).
    scheduler_interval_seconds: float | None = None
    #: Item 91: minimum fields-filled ratio below which an application is
    #: flagged for review instead of offered for submit (0.0-1.0).
    ats_match_rate_floor: float | None = None
    #: Item 97: whether postings are filtered on work-authorization /
    #: sponsorship / clearance requirements before the pipeline starts.
    presubmit_eligibility_enabled: bool | None = None
    #: Item 98: blocks postings older than this many days.
    presubmit_max_listing_age_days: int | None = None
    #: Item 99: auto-apply vs staged memory/skills writes (memory MAY be
    #: relaxed; skills/identity conceptually always warrant review).
    memory_write_approval: bool | None = None
    skills_write_approval: bool | None = None
    #: Item 99: curated-memory prompt-budget caps (characters).
    memory_max_chars: int | None = None
    user_max_chars: int | None = None
    #: Item 102: whether the smart LLM router's tier ladder prefers a local
    #: endpoint when one is online (the master on/off switch + read-only
    #: routing status are item 74, already surfaced; this is just the policy).
    llm_smart_routing_prefer_local: bool | None = None
    #: Item 105: token budget above which older turns are compressed; 0 disables.
    context_compress_threshold: int | None = None
    #: Item 106: consecutive tick failures before a stall alert fires.
    loop_failure_alert_threshold: int | None = None
    #: Item 107: switches pre-fill to the experimental plan-as-data planner.
    prefill_use_planner: bool | None = None
    #: Item 92: which sandbox the engine automates in ("local"/"proxmox-windows")
    #: and the browser-fingerprint persona ("linux"/"native"/"" to auto-derive).
    sandbox_backend: str | None = None
    stealth_persona: str | None = None
    #: Item 93: the browser ALL outbound automation routes through
    #: ("camoufox"/"chromium") and, for the chromium engine, its channel
    #: ("chrome"/"chromium").
    browser_engine: str | None = None
    browser_channel: str | None = None
    #: Item 94: assistant/loop tool-autonomy master switches ("off"/"auto").
    chat_tools: str | None = None
    loop_tools: str | None = None
    #: Item 95: fold capped company research into cover-letter generation.
    material_research_enabled: bool | None = None
    #: Item 96: desktop-assist backend ("noop"/"cua"), capture mode
    #: ("som"/"ax"), and approval posture ("manual"/"session").
    computer_use_backend: str | None = None
    computer_use_mode: str | None = None
    computer_use_approvals: str | None = None
    #: Item 100: proactive-cadence knobs ("off"/"daily") for the memory-curation
    #: nudge, the periodic campaign status push, and the "still blocked" reminder.
    curation_schedule: str | None = None
    status_update_schedule: str | None = None
    essentials_nudge_schedule: str | None = None
    #: Item 101: comma-separated proxy list the discovery crawler routes through.
    discovery_proxies: str | None = None
    #: Item 80 (dark-engine audit B7): comma-separated custom job-board RSS feed
    #: URL list, validated + merged the same way ``discovery_proxies`` is.
    discovery_rss_feeds: str | None = None
    #: Item 103: live-takeover desktop environment + remote-view technology.
    takeover_desktop: str | None = None
    remote_view_backend: str | None = None
    #: Item 104: resume render fidelity ("auto"/"on"/"off").
    resume_render: str | None = None
    #: Item 83: captcha-handling strategy ("human"/"avoid"/"service") + the
    #: third-party solving service ("capsolver"/"2captcha"/"anticaptcha") used
    #: by "service". ``captcha_api_key`` is the SECRET solver API key: sealed
    #: in the credential vault, never echoed back by GET (only a boolean
    #: ``captcha_api_key_configured`` is), and a blank/omitted value leaves any
    #: already-vaulted key untouched.
    captcha_strategy: str | None = None
    captcha_service: str | None = None
    captcha_api_key: str | None = None
    #: Item 89: residential-egress mode ("direct"/"residential-proxy"), the
    #: operator's explicit attestation that the configured proxy is a genuine
    #: residential exit, and the proxy URL itself (SSRF-validated; may embed
    #: proxy credentials -- plain-stored like ``discovery_proxies``, not
    #: vaulted, matching that field's own precedent).
    egress_mode: str | None = None
    egress_residential: bool | None = None
    egress_proxy_url: str | None = None


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


class ChannelTestIn(BaseModel):
    """Optional single-channel selector for the test ping (P1-4).

    Empty (or no body at all — the historical shape) keeps the fan-out-to-every-
    configured-channel behavior. Naming one channel (``discord`` / ``email`` /
    ``ntfy`` / ``in_app``) tests just that channel, and a live delivery failure
    is reported as an error instead of being swallowed by the ladder's
    per-channel isolation — a watched test button must tell the truth.
    """

    channel: str = ""


@router.post("/channels/test")
def test_channels(
    body: ChannelTestIn | None = None, container=Depends(get_container)
) -> dict:
    """Send a test notification across configured channels (FR-NOTIF-1).

    Hermetic by default (the notifier captures offline); a live deployment sends
    for real. Returns the channels the test would fire on. With a ``channel`` in
    the body, tests only that channel (per-channel Send test, P1-4).
    """
    from applicant.adapters.notification.apprise_notifier import (
        NotificationDeliveryError,
    )
    from applicant.ports.driven.notification import Notification, NotificationUrgency

    notification = container.notification
    live = notification.is_live() if hasattr(notification, "is_live") else True
    requested = (body.channel if body is not None else "").strip()
    if requested and hasattr(notification, "send_test"):
        try:
            notification.send_test(requested)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except NotificationDeliveryError as exc:
            # Honesty: a live send that failed is a failure, not a success with a
            # log line. 502 — the upstream channel (webhook/SMTP/ntfy) rejected it.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"The test could not be delivered on the {requested} channel — "
                    "double-check its settings and try again."
                ),
            ) from exc
        result = {"sent": True, "live": live, "channels": [requested]}
        if not live:
            result["note"] = "dry run — set NOTIFICATIONS_LIVE=true to deliver"
        return result
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
    """Settings > Automation (dark-engine audit items
    82/83/84/85/86/87/88/89/90/91/92/93/94/95/96/97/98/99/100/101/102/103/104/105/106/107).

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
        "approval_timeout_days": stored.get(
            "approval_timeout_days", settings.approval_timeout_days
        ),
        "approval_wait_seconds": stored.get(
            "approval_wait_seconds", settings.approval_wait_seconds
        ),
        "scheduler_interval_seconds": stored.get(
            "scheduler_interval_seconds", settings.scheduler_interval_seconds
        ),
        "ats_match_rate_floor": stored.get(
            "ats_match_rate_floor", settings.ats_match_rate_floor
        ),
        "presubmit_eligibility_enabled": stored.get(
            "presubmit_eligibility_enabled", settings.presubmit_eligibility_enabled
        ),
        "presubmit_max_listing_age_days": stored.get(
            "presubmit_max_listing_age_days", settings.presubmit_max_listing_age_days
        ),
        "memory_write_approval": stored.get(
            "memory_write_approval", settings.memory_write_approval
        ),
        "skills_write_approval": stored.get(
            "skills_write_approval", settings.skills_write_approval
        ),
        "memory_max_chars": stored.get("memory_max_chars", settings.memory_max_chars),
        "user_max_chars": stored.get("user_max_chars", settings.user_max_chars),
        "llm_smart_routing_prefer_local": stored.get(
            "llm_smart_routing_prefer_local", settings.llm_smart_routing_prefer_local
        ),
        "context_compress_threshold": stored.get(
            "context_compress_threshold", settings.context_compress_threshold
        ),
        "loop_failure_alert_threshold": stored.get(
            "loop_failure_alert_threshold", settings.loop_failure_alert_threshold
        ),
        "prefill_use_planner": stored.get(
            "prefill_use_planner", settings.prefill_use_planner
        ),
        "sandbox_backend": stored.get("sandbox_backend", settings.sandbox_backend),
        "stealth_persona": stored.get("stealth_persona", settings.stealth_persona),
        "browser_engine": stored.get("browser_engine", settings.browser_engine),
        "browser_channel": stored.get("browser_channel", settings.browser_channel),
        "chat_tools": stored.get("chat_tools", settings.chat_tools),
        "loop_tools": stored.get("loop_tools", settings.loop_tools),
        "material_research_enabled": stored.get(
            "material_research_enabled", settings.material_research_enabled
        ),
        "computer_use_backend": stored.get(
            "computer_use_backend", settings.computer_use_backend
        ),
        "computer_use_mode": stored.get(
            "computer_use_mode", settings.computer_use_mode
        ),
        "computer_use_approvals": stored.get(
            "computer_use_approvals", settings.computer_use_approvals
        ),
        "curation_schedule": stored.get(
            "curation_schedule", settings.curation_schedule
        ),
        "status_update_schedule": stored.get(
            "status_update_schedule", settings.status_update_schedule
        ),
        "essentials_nudge_schedule": stored.get(
            "essentials_nudge_schedule", settings.essentials_nudge_schedule
        ),
        "discovery_proxies": stored.get(
            "discovery_proxies", settings.discovery_proxies
        ),
        "discovery_rss_feeds": stored.get(
            "discovery_rss_feeds", settings.discovery_rss_feeds
        ),
        "takeover_desktop": stored.get(
            "takeover_desktop", settings.takeover_desktop
        ),
        "remote_view_backend": stored.get(
            "remote_view_backend", settings.remote_view_backend
        ),
        "resume_render": stored.get("resume_render", settings.resume_render),
        "captcha_strategy": stored.get("captcha_strategy", settings.captcha_strategy),
        "captcha_service": stored.get("captcha_service", settings.captcha_service),
        # SECRET (item 83, FR-VAULT-3): the raw key is NEVER returned here -- only
        # whether one has been saved. ``stored`` already comes from the FILTERED
        # ``get_automation_prefs()``, which computes this same boolean; read it
        # straight through rather than re-deriving it here.
        "captcha_api_key_configured": stored.get("captcha_api_key_configured", False),
        "egress_mode": stored.get("egress_mode", settings.egress_mode),
        "egress_residential": stored.get("egress_residential", settings.egress_residential),
        # NOT a secret by this codebase's own precedent (matches discovery_proxies,
        # item 101, which has the identical embedded-credential shape and is
        # plain-stored/returned raw, not vaulted) -- item 89.
        "egress_proxy_url": stored.get("egress_proxy_url", settings.egress_proxy_url),
    }


@router.put("/automation", status_code=status.HTTP_204_NO_CONTENT)
def set_automation_prefs(body: AutomationPrefsIn, svc=Depends(get_setup_service)) -> None:
    """Save Settings > Automation overrides (dark-engine audit items
    82/83/84/85/86/87/88/89/90/91/92/93/94/95/96/97/98/99/100/101/102/103/104/105/106/107)."""
    try:
        svc.set_automation_prefs(
            egress_timezone=body.egress_timezone,
            egress_locale=body.egress_locale,
            allow_automated_accounts=body.allow_automated_accounts,
            presubmit_max_apps_per_company_per_day=body.presubmit_max_apps_per_company_per_day,
            pii_retention_days=body.pii_retention_days,
            presubmit_duplicate_cooldown_days=body.presubmit_duplicate_cooldown_days,
            approval_timeout_days=body.approval_timeout_days,
            approval_wait_seconds=body.approval_wait_seconds,
            scheduler_interval_seconds=body.scheduler_interval_seconds,
            ats_match_rate_floor=body.ats_match_rate_floor,
            presubmit_eligibility_enabled=body.presubmit_eligibility_enabled,
            presubmit_max_listing_age_days=body.presubmit_max_listing_age_days,
            memory_write_approval=body.memory_write_approval,
            skills_write_approval=body.skills_write_approval,
            memory_max_chars=body.memory_max_chars,
            user_max_chars=body.user_max_chars,
            llm_smart_routing_prefer_local=body.llm_smart_routing_prefer_local,
            context_compress_threshold=body.context_compress_threshold,
            loop_failure_alert_threshold=body.loop_failure_alert_threshold,
            prefill_use_planner=body.prefill_use_planner,
            sandbox_backend=body.sandbox_backend,
            stealth_persona=body.stealth_persona,
            browser_engine=body.browser_engine,
            browser_channel=body.browser_channel,
            chat_tools=body.chat_tools,
            loop_tools=body.loop_tools,
            material_research_enabled=body.material_research_enabled,
            computer_use_backend=body.computer_use_backend,
            computer_use_mode=body.computer_use_mode,
            computer_use_approvals=body.computer_use_approvals,
            curation_schedule=body.curation_schedule,
            status_update_schedule=body.status_update_schedule,
            essentials_nudge_schedule=body.essentials_nudge_schedule,
            discovery_proxies=body.discovery_proxies,
            discovery_rss_feeds=body.discovery_rss_feeds,
            takeover_desktop=body.takeover_desktop,
            remote_view_backend=body.remote_view_backend,
            resume_render=body.resume_render,
            captcha_strategy=body.captcha_strategy,
            captcha_service=body.captcha_service,
            captcha_api_key=body.captcha_api_key,
            egress_mode=body.egress_mode,
            egress_residential=body.egress_residential,
            egress_proxy_url=body.egress_proxy_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{campaign_id}/gaps")
def get_profile_gaps(campaign_id: str, chat=Depends(get_chat_service)) -> dict:
    """A visible completeness checklist for one campaign (dark-engine audit item 51).

    ``ChatService.identify_gaps`` already computes which core profile attributes
    (name/email/phone/title) and search criteria are still missing — today it is
    read only as hidden context inside a chat turn. This surfaces the SAME
    gap list (no separate computation, no fabricated data) as a plain read so the
    front door can show it as a checklist without requiring a chat message first.
    """
    gaps = chat.identify_gaps(CampaignId(campaign_id))
    return {"campaign_id": campaign_id, "gaps": gaps, "complete": not gaps}


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
