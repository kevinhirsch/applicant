"""SetupService — OOBE resumable wizard + LLM gate (FR-OOBE, FR-LLM-2/3, FR-UI-5).

A real, resumable wizard: it persists the LLM tier ladder and per-step completion
to an :class:`AppConfigStore` so the wizard survives restarts (FR-OOBE-1). The
LLM-settings gate stays first and blocks downstream routes (409) until satisfied
(FR-UI-5). Channel setup is modeled as a gating step (FR-OOBE-3) even though the
channel backends arrive in Phase 1.

Secrets (api keys) are routed through the encrypted credential store; only a
non-secret marker is persisted in app-config, so keys never reach the logs or the
plaintext config table (FR-VAULT-3, NFR-PRIV-1).
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from applicant.adapters.storage.app_config_store import (
    AppConfigStore,
    InMemoryAppConfigStore,
)
from applicant.core.errors import InvalidInput
from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import TierConfig, TierLadder
from applicant.ports.driving.setup_wizard import (
    STEP_ORDER,
    LLMSettings,
    SandboxConnectionSettings,
    TierSettings,
    WizardStatus,
    WizardStep,
)

log = get_logger(__name__)

#: The cloud-instance metadata address (AWS/GCP/Azure link-local). An operator URL
#: pointed here would let a request exfiltrate instance credentials — block it (item 12).
_METADATA_ADDR = "169.254.169.254"


def validate_operator_url(url: str, *, field: str = "url") -> str:
    """SSRF guard for an OPERATOR-supplied URL (item 12, SECURITY).

    Rejects:
      * non-``http``/``https`` schemes (no ``file:``/``gopher:``/``ftp:`` etc.), and
      * the cloud-metadata link-local address ``169.254.169.254``.

    Intentionally ALLOWS localhost + private ranges: a local Ollama (``http://
    localhost:11434``) and an internal SearXNG/Discord webhook are legitimate. Empty
    URLs pass through (the field is simply unset). Returns the (stripped) URL.
    """
    u = (url or "").strip()
    if not u:
        return u
    parts = urlsplit(u)
    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidInput(
            f"{field} must be an http(s) URL (got scheme {parts.scheme!r})."
        )
    host = (parts.hostname or "").strip()
    if not host:
        raise InvalidInput(f"{field} must include a host.")
    if host == _METADATA_ADDR:
        raise InvalidInput(
            f"{field} may not target the cloud metadata address {_METADATA_ADDR}."
        )
    # Also block the metadata address when given as a packed/alternate IP form.
    # An IPv6-mapped IPv4 literal (e.g. ``::ffff:169.254.169.254`` or its packed
    # ``::ffff:a9fe:a9fe`` form) parses as an IPv6Address that does NOT ``==`` the
    # plain IPv4 metadata address, so normalize it back to IPv4 first — otherwise
    # the metadata block is trivially bypassed via the mapped form (SSRF).
    try:
        ip = ipaddress.ip_address(host)
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        if ip == ipaddress.ip_address(_METADATA_ADDR):
            raise InvalidInput(
                f"{field} may not target the cloud metadata address {_METADATA_ADDR}."
            )
    except ValueError:
        pass  # not an IP literal (a hostname) — localhost/private hostnames are allowed
    return u


def validate_operator_urls(value: str, *, field: str = "url") -> str:
    """Validate a comma-separated list of operator URLs (e.g. APPRISE_URLS).

    Each comma-separated entry is SSRF-checked. Non-URL Apprise schemes (e.g.
    ``mailto://``/``discord://``) are left untouched — only ``http(s)`` entries and
    the metadata-address block apply. Returns the original string unchanged on success.
    """
    for raw in (value or "").split(","):
        entry = raw.strip()
        if not entry:
            continue
        scheme = urlsplit(entry).scheme.lower()
        if scheme in ("http", "https"):
            validate_operator_url(entry, field=field)
        elif scheme in ("", "file", "gopher", "ftp"):
            # An entry that LOOKS like a URL but is a dangerous/local-file scheme.
            if "://" in entry and scheme != "":
                raise InvalidInput(
                    f"{field} entry {entry!r} uses a disallowed scheme {scheme!r}."
                )
    return value


def validate_hhmm(value: str, *, field: str = "time") -> str:
    """Validate + normalize an ``HH:MM`` 24-hour clock time (FR-NOTIF-5).

    Returns the zero-padded ``HH:MM`` form (e.g. ``"9:5"`` -> ``"09:05"``). An empty
    string passes through unchanged (the field is simply unset). Anything that is not
    a valid 00:00-23:59 time raises ``ValueError`` so the setup router maps it to a
    clean 400 (matching ``configure_llm``) and a malformed window is never persisted.
    """
    text = (value or "").strip()
    if not text:
        return text
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"{field} must be in HH:MM 24-hour format (e.g. 22:00).")
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(
            f"{field} must be in HH:MM 24-hour format (e.g. 22:00)."
        ) from exc
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"{field} must be a time between 00:00 and 23:59.")
    return f"{hh:02d}:{mm:02d}"


_LADDER_KEY = "llm.tier_ladder"
_STEPS_KEY = "wizard.steps_complete"
_CHANNELS_KEY = "notify.channels"
_SANDBOX_CONN_KEY = "sandbox.proxmox_windows"
#: Settings > Automation overrides (dark-engine audit items 82/84/85): the
#: browser-fingerprint timezone/locale, whether the engine may create ATS
#: accounts from vaulted credentials, and the per-company daily application
#: cap. Stored as an OVERRIDE record (only keys the operator actually saved
#: are present) exactly like ``_CHANNELS_KEY`` -- callers merge this onto the
#: env-sourced ``Settings`` defaults, so an unconfigured knob still shows the
#: value the running engine actually uses today.
_AUTOMATION_KEY = "automation.prefs"
#: Defaults duplicated here (NOT imported from ``applicant.app.config.Settings``)
#: so this module has zero import-time dependency on the pydantic settings
#: layer -- the same reason ``get_quiet_hours`` hardcodes "22:00"/"07:00"
#: rather than importing them. Keep in sync with ``config.py``'s field
#: defaults (egress_timezone/egress_locale/allow_automated_accounts/
#: presubmit_max_apps_per_company_per_day).
AUTOMATION_PREFS_DEFAULTS: dict[str, Any] = {
    "egress_timezone": "America/Phoenix",
    "egress_locale": "en-US",
    "allow_automated_accounts": False,
    "presubmit_max_apps_per_company_per_day": 3,
}
#: Vault refs for the sandbox-connection secrets (Proxmox token secret, RDP pass).
_SANDBOX_TOKEN_REF = "sandbox.proxmox_token_secret"
_SANDBOX_RDP_REF = "sandbox.proxmox_rdp_password"
_DEFAULT_MAX_TIERS = 10
#: Defensive backstop TTL for the in-process tier-ladder cache (perf item #7).
#: ``_save_tiers`` invalidates the cache synchronously on every write made through
#: this class (the ONLY writer of ``_LADDER_KEY`` in the codebase), so in practice
#: the cache is never stale — this TTL only guards against a write reaching the
#: underlying store through some path other than this instance (e.g. a second
#: process). Kept short so such a write is still picked up almost immediately.
_TIER_LADDER_CACHE_TTL_S = 5.0

#: Default TTL for :class:`TTLCachedGate` when wrapping the automated-work
#: onboarding gate (perf item #8). Campaign readiness (criteria + résumé) is a
#: rare, user-driven event, not something that needs sub-second freshness, so a
#: few seconds of staleness is an acceptable trade for turning "scan every
#: campaign + recompute readiness" from a per-poll cost into a per-5s cost. Kept
#: short because this specifically backs ``require_automated_work``: it must
#: never authorize work for long past the moment it should have closed again.
DEFAULT_ONBOARDING_GATE_CACHE_TTL_S = 5.0


class TTLCachedGate:
    """Memoize an expensive boolean gate closure behind a short TTL (perf item #8).

    Built for closures like the container's ``_onboarding_gate`` — it scans
    EVERY campaign and computes full apply-readiness (criteria load + résumé
    check) per campaign — which back ``require_automated_work`` and are
    therefore re-run on every 45-60s poll from ``agent_status``, digest, and
    agent-runs. Wrapping the closure (not :meth:`SetupService.is_automated_work_
    allowed`) is deliberate: unit tests construct a bare ``SetupService`` with
    their own real-time gate closure and assert the gate flips the instant the
    underlying data changes (see ``tests/unit/test_apply_readiness_gate.py``) —
    wrapping inside ``SetupService`` itself would make those assertions flaky.
    Only the container's real (expensive, rarely-changing) closure is wrapped.

    Safety note: this cache backs a gate that BLOCKS automated work, never one
    that self-authorizes it beyond what the underlying data says. A TTL means a
    "not yet ready" can read stale for up to ``ttl_seconds`` after work becomes
    ready (a harmless extra delay) and, symmetrically, a "ready" can read stale
    for up to ``ttl_seconds`` after something regresses — bounded to the same
    short window, not indefinite. ``invalidate()`` is provided for any future
    write path that wants an immediate recheck without waiting out the TTL.
    """

    def __init__(self, fn: Callable[[], bool], ttl_seconds: float) -> None:
        self._fn = fn
        self._ttl = ttl_seconds
        self._value: bool | None = None
        self._at = 0.0

    def __call__(self) -> bool:
        now = time.monotonic()
        if self._value is not None and (now - self._at) < self._ttl:
            return self._value
        self._value = bool(self._fn())
        self._at = now
        return self._value

    def invalidate(self) -> None:
        """Drop the cached value so the next call re-runs the wrapped closure."""
        self._value = None
        self._at = 0.0


class SetupService:
    """Implements the SetupWizard driving port with persistent state."""

    def __init__(
        self,
        *,
        llm_configured: bool = False,
        config_store: AppConfigStore | None = None,
        credentials: Any | None = None,
        onboarding_gate: Callable[[], bool] | None = None,
        channels_gate: Callable[[], bool] | None = None,
        sandbox_backend: str = "local",
    ) -> None:
        self._store = config_store or InMemoryAppConfigStore()
        self._credentials = credentials
        self._llm_preconfigured = llm_configured
        self._fonts_ready = False
        self._onboarding_complete = False
        # Real gates: onboarding completion (FR-ONBOARD-2) + channels (FR-OOBE-3).
        # When provided, these override the local advance-step flags so the
        # "automated work may begin" gate reflects genuine backend state.
        self._onboarding_gate = onboarding_gate
        self._channels_gate = channels_gate
        # Which sandbox backend is selected — the sandbox-connection step only GATES
        # when the native proxmox-windows backend is selected (FR-OOBE, FR-SANDBOX-1).
        self._sandbox_backend = sandbox_backend
        # Optional reporter for the required-to-apply readiness (the hard apply-gate):
        # returns an ApplyReadiness snapshot (or None) computed from real campaign data
        # so status() can surface the remaining essentials + a plain reason. Wired
        # additively by the composition root; when unset, the readiness payload is
        # omitted and behavior is unchanged.
        self._apply_readiness_reporter: Callable[[], Any] | None = None
        # Config-change hooks fired AFTER the LLM tier ladder is persisted, so a model
        # connected at runtime takes effect with no engine restart: the composition
        # root registers the live LLM adapter's ``refresh_ladder`` here, which drops its
        # cached (initially-empty) ladder so the next completion re-reads the new tiers.
        # Empty by default ⇒ behavior unchanged when nothing is registered.
        self._llm_config_change_hooks: list[Callable[[], None]] = []
        # In-process cache of the persisted LLM tier ladder (perf item #7):
        # ``is_setup_gate_open``/``is_automated_work_allowed`` are evaluated by
        # ``require_llm_configured``/``require_automated_work`` on nearly every
        # request — including every 45-60s poll from every surface — and were
        # each paying a real SELECT against the shared boot Session. The ladder
        # changes only when an operator explicitly (re)configures it, so cache the
        # loaded value and invalidate it synchronously in ``_save_tiers`` (the sole
        # write path) rather than re-reading on every gate check.
        self._tiers_cache: list[dict[str, Any]] | None = None
        self._tiers_cache_at: float = 0.0

    def register_llm_config_change_hook(self, hook: Callable[[], None]) -> None:
        """Register a callback fired after the LLM ladder is (re)configured.

        Additive + optional. Used by the composition root to re-arm the live LLM
        adapter when a model is connected/changed at runtime so the running engine
        picks it up immediately (FR-LLM-2/3) — no process restart. A failing hook is
        logged and never propagates, so persisting the config still succeeds.
        """
        self._llm_config_change_hooks.append(hook)

    def _fire_llm_config_change(self) -> None:
        for hook in self._llm_config_change_hooks:
            try:
                hook()
            except Exception:  # pragma: no cover - a hook hiccup never breaks config
                log.warning("llm_config_change_hook_failed", exc_info=True)

    def set_apply_readiness_reporter(self, reporter: Callable[[], Any]) -> None:
        """Inject the required-to-apply readiness reporter (composition root).

        Additive + optional: when unset, ``apply_readiness()`` returns ``None`` and the
        status payload omits the readiness block — behavior is unchanged. The reporter
        returns an ``ApplyReadiness`` (``ready``/``missing``/``reason``) from real
        campaign data; this service never fabricates the missing set.
        """
        self._apply_readiness_reporter = reporter

    def apply_readiness(self) -> Any | None:
        """Return the current required-to-apply readiness snapshot (or ``None``)."""
        if self._apply_readiness_reporter is None:
            return None
        try:
            return self._apply_readiness_reporter()
        except Exception:  # pragma: no cover - a reporter hiccup never breaks status
            log.warning("apply_readiness_report_failed")
            return None

    def set_suggested_attributes_reporter(
        self, reporter: Callable[[], list[dict]]
    ) -> None:
        """Inject the engine-proposed-attribute reporter (composition root, #273).

        Additive + optional: surfaces the attribute suggestions the learning layer
        derives from the candidate's stored inputs so the front-door "suggested
        attribute" approval card has a data source. When unset the status payload still
        carries an empty ``suggested_attributes`` list (a stable contract, never noise).
        """
        self._suggested_attributes_reporter = reporter

    def suggested_attributes(self) -> list[dict]:
        """Return engine-proposed attributes awaiting operator approval (#273)."""
        reporter = getattr(self, "_suggested_attributes_reporter", None)
        if reporter is None:
            return []
        try:
            return list(reporter() or [])
        except Exception:  # pragma: no cover - a reporter hiccup never breaks status
            log.warning("suggested_attributes_report_failed")
            return []

    @property
    def sandbox_backend(self) -> str:
        """The selected sandbox backend (``local`` | ``proxmox-windows``)."""
        return self._sandbox_backend

    # --- persistence helpers ---------------------------------------------
    def _load_tiers(self) -> list[dict[str, Any]]:
        """Return the persisted tier ladder, cached in-process (perf item #7).

        Cache-hit path does zero store access. A hit requires both a populated
        cache AND freshness within the defensive TTL — cache invalidation on the
        write side (``_save_tiers``) is what actually keeps this correct; the TTL
        is only a backstop (see its docstring).
        """
        now = time.monotonic()
        if (
            self._tiers_cache is not None
            and (now - self._tiers_cache_at) < _TIER_LADDER_CACHE_TTL_S
        ):
            return list(self._tiers_cache)
        rec = self._store.get(_LADDER_KEY)
        tiers = list(rec.get("tiers", [])) if rec else []
        self._tiers_cache = tiers
        self._tiers_cache_at = now
        return list(tiers)

    def _save_tiers(self, tiers: list[dict[str, Any]]) -> None:
        self._store.set(_LADDER_KEY, {"tiers": tiers})
        # Write-through: the next read reflects this write immediately, with no
        # window where a caller could observe a stale ladder after a real write.
        self._tiers_cache = list(tiers)
        self._tiers_cache_at = time.monotonic()

    def _steps_complete(self) -> set[str]:
        rec = self._store.get(_STEPS_KEY)
        steps = set(rec.get("steps", [])) if rec else set()
        if self._fonts_ready:
            steps.add(WizardStep.FONTS.value)
        # Onboarding completion is gated on the real onboarding state when wired
        # (FR-ONBOARD-2); fall back to the local advance flag otherwise.
        if self._onboarding_complete_now():
            steps.add(WizardStep.ONBOARDING.value)
        else:
            steps.discard(WizardStep.ONBOARDING.value)
        if self._channels_complete_now():
            steps.add(WizardStep.CHANNELS.value)
        # The sandbox-connection step completes once the Proxmox Windows connection is
        # configured (FR-OOBE) OR when the native backend is NOT selected (it does not
        # apply to the local backend, so it never blocks there).
        if self._sandbox_step_complete_now():
            steps.add(WizardStep.SANDBOX.value)
        else:
            steps.discard(WizardStep.SANDBOX.value)
        return steps

    def _sandbox_step_complete_now(self) -> bool:
        """The sandbox step is satisfied unless the native backend needs config."""
        if self._sandbox_backend != "proxmox-windows":
            return True
        return self.sandbox_connection_configured()

    def _onboarding_complete_now(self) -> bool:
        if self._onboarding_gate is not None:
            return bool(self._onboarding_gate())
        return self._onboarding_complete

    def _channels_complete_now(self) -> bool:
        rec = self._store.get(_STEPS_KEY)
        flagged = bool(rec and WizardStep.CHANNELS.value in set(rec.get("steps", [])))
        if self._channels_gate is not None:
            return bool(self._channels_gate()) or flagged
        return flagged or self.channels_configured()

    def set_channels_gate(self, gate: Callable[[], bool]) -> None:
        """Inject the channels gate after construction (composition root, FR-OOBE-3)."""
        self._channels_gate = gate

    # --- notification channels (FR-OOBE-2/3, FR-NOTIF-1) ------------------
    def get_channels(self) -> dict[str, str]:
        """Return persisted channel config (non-secret enough for the notifier)."""
        rec = self._store.get(_CHANNELS_KEY)
        return dict(rec) if rec else {}

    def channels_configured(self) -> bool:
        """True once at least Discord, email, OR ntfy push is configured (FR-OOBE-3)."""
        chan = self.get_channels()
        return bool(
            chan.get("discord_webhook_url")
            or chan.get("apprise_urls")
            or chan.get("ntfy_url")
        )

    #: Bounds for the UI-configurable email-escalation delay (FR-NOTIF-2), in minutes.
    EMAIL_TIMEOUT_MIN_MINUTES = 1
    EMAIL_TIMEOUT_MAX_MINUTES = 24 * 60
    EMAIL_TIMEOUT_DEFAULT_MINUTES = 15

    def get_email_timeout_minutes(self) -> int:
        """The configured email-escalation delay in minutes (FR-NOTIF-2), default 15."""
        raw = self.get_channels().get("email_timeout_minutes")
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            return self.EMAIL_TIMEOUT_DEFAULT_MINUTES
        return max(
            self.EMAIL_TIMEOUT_MIN_MINUTES, min(self.EMAIL_TIMEOUT_MAX_MINUTES, minutes)
        )

    def configure_channels(
        self,
        *,
        discord_webhook_url: str = "",
        apprise_urls: str = "",
        ntfy_url: str = "",
        email_timeout_minutes: int | None = None,
    ) -> None:
        """Persist notification-channel config from the wizard (FR-OOBE-2).

        Configuring Discord, email, or ntfy push marks the channels step able to
        complete and ungates automated work (FR-OOBE-3). ``email_timeout_minutes``
        sets the UI-configurable email-escalation delay (FR-NOTIF-2). Secrets are
        not logged.
        """
        # Item 12 (SSRF): all are operator-supplied. The Discord webhook is an https
        # URL; Apprise + ntfy URLs are comma-separated lists (http(s) entries are
        # guarded, native Apprise schemes like mailto://discord://ntfy:// pass through).
        validate_operator_url(discord_webhook_url, field="Discord webhook URL")
        validate_operator_urls(apprise_urls, field="Apprise URL")
        validate_operator_urls(ntfy_url, field="ntfy URL")
        rec = self.get_channels()
        if discord_webhook_url:
            rec["discord_webhook_url"] = discord_webhook_url
        if apprise_urls:
            rec["apprise_urls"] = apprise_urls
        if ntfy_url:
            rec["ntfy_url"] = ntfy_url
        if email_timeout_minutes is not None:
            rec["email_timeout_minutes"] = max(
                self.EMAIL_TIMEOUT_MIN_MINUTES,
                min(self.EMAIL_TIMEOUT_MAX_MINUTES, int(email_timeout_minutes)),
            )
        self._store.set(_CHANNELS_KEY, rec)
        if self.channels_configured():
            steps_rec = self._store.get(_STEPS_KEY) or {"steps": []}
            steps = set(steps_rec.get("steps", []))
            steps.add(WizardStep.CHANNELS.value)
            self._store.set(_STEPS_KEY, {"steps": sorted(steps)})
        log.info(
            "channels_configured",
            discord=bool(discord_webhook_url),
            email=bool(apprise_urls),
            ntfy=bool(ntfy_url),
        )

    # --- quiet hours (FR-NOTIF-5) -----------------------------------------
    def get_quiet_hours(self) -> dict[str, Any]:
        """Return the persisted quiet-hours window for the UI (no secrets).

        Shape: ``{"enabled": bool, "start": "HH:MM", "end": "HH:MM", "tz": str,
        "channels": {"discord": bool, "email": bool}}``. ``enabled=False`` is 24/7
        mode (always notify). Defaults are a sensible overnight window so enabling it
        once is one click. ``channels`` is the per-channel preference (FR-NOTIF-5):
        ``True`` = the channel respects quiet hours; ``False`` = it still delivers
        overnight. Both default to True (respect quiet hours).
        """
        chan = self.get_channels()
        return {
            "enabled": bool(chan.get("quiet_hours_enabled", False)),
            "start": chan.get("quiet_hours_start", "22:00"),
            "end": chan.get("quiet_hours_end", "07:00"),
            "tz": chan.get("quiet_hours_tz", ""),
            "channels": {
                "discord": bool(chan.get("quiet_hours_discord", True)),
                "email": bool(chan.get("quiet_hours_email", True)),
            },
        }

    def get_quiet_hours_channels(self) -> dict[str, bool]:
        """The per-channel quiet-hours map keyed by notifier channel value (#302).

        Maps the transport channel names the notifier uses (``"discord"``,
        ``"email"``) to whether they respect quiet hours. A channel mapped ``False``
        is exempt (delivers overnight). Returned in the shape the live notifier's
        ``configure(quiet_hours_channels=...)`` consumes.
        """
        chan = self.get_channels()
        return {
            "discord": bool(chan.get("quiet_hours_discord", True)),
            "email": bool(chan.get("quiet_hours_email", True)),
        }

    def set_quiet_hours(
        self,
        *,
        enabled: bool,
        start: str = "22:00",
        end: str = "07:00",
        tz: str = "",
        discord_respects: bool | None = None,
        email_respects: bool | None = None,
    ) -> None:
        """Persist the quiet-hours window (FR-NOTIF-5).

        ``enabled=False`` selects 24/7 mode (approvals/digests notify any hour);
        ``enabled=True`` defers approval/digest push channels to the next allowed
        hour inside the ``[start, end)`` window. Errors are NEVER deferred — that gate
        lives in the notifier and is independent of this setting. Times are validated
        to HH:MM; the window is stored alongside the channel config so it travels with
        it. Secrets are not involved.

        ``discord_respects`` / ``email_respects`` (#302) set the per-channel quiet
        preference: ``False`` exempts that channel so it still delivers overnight.
        ``None`` leaves the persisted value untouched.
        """
        start = validate_hhmm(start, field="Quiet-hours start")
        end = validate_hhmm(end, field="Quiet-hours end")
        rec = self.get_channels()
        rec["quiet_hours_enabled"] = bool(enabled)
        rec["quiet_hours_start"] = start or "22:00"
        rec["quiet_hours_end"] = end or "07:00"
        rec["quiet_hours_tz"] = (tz or "").strip()
        if discord_respects is not None:
            rec["quiet_hours_discord"] = bool(discord_respects)
        if email_respects is not None:
            rec["quiet_hours_email"] = bool(email_respects)
        self._store.set(_CHANNELS_KEY, rec)
        log.info(
            "quiet_hours_configured",
            enabled=bool(enabled),
            start=rec["quiet_hours_start"],
            end=rec["quiet_hours_end"],
            tz=bool(rec["quiet_hours_tz"]),
            discord_respects=bool(rec.get("quiet_hours_discord", True)),
            email_respects=bool(rec.get("quiet_hours_email", True)),
        )

    # --- sandbox connection (native Proxmox Windows VM, FR-OOBE, FR-VAULT-3) --
    def configure_sandbox_connection(self, settings: SandboxConnectionSettings) -> None:
        """Persist the Proxmox Windows VM connection/login data (FR-OOBE).

        Non-secrets (API URL/node/token id/VMID/clone mode/CDP/RDP user/takeover)
        persist to app-config; the SECRETS (Proxmox API token secret + RDP password)
        are sealed in the credential vault and only a marker is stored — secrets are
        NEVER logged or returned (FR-VAULT-3, NFR-PRIV-1).
        """
        if not (settings.proxmox_api_url and settings.proxmox_node):
            raise ValueError("Proxmox API URL and node are required.")
        if not settings.template_vmid:
            raise ValueError("A Windows template/persistent VMID is required.")
        if not (settings.proxmox_token_id and settings.proxmox_token_secret):
            raise ValueError("Proxmox API token id + secret are required.")
        record: dict[str, Any] = {
            "proxmox_api_url": settings.proxmox_api_url,
            "proxmox_node": settings.proxmox_node,
            "proxmox_token_id": settings.proxmox_token_id,
            "template_vmid": int(settings.template_vmid),
            "clone_mode": settings.clone_mode,
            "cdp_host": settings.cdp_host,
            "cdp_port": int(settings.cdp_port),
            "rdp_username": settings.rdp_username,
            "takeover_method": settings.takeover_method,
            "takeover_url_template": settings.takeover_url_template,
        }
        if self._credentials is not None:
            self._store_secret(_SANDBOX_TOKEN_REF, settings.proxmox_token_secret)
            record["token_secret_ref"] = _SANDBOX_TOKEN_REF
            if settings.rdp_password:
                self._store_secret(_SANDBOX_RDP_REF, settings.rdp_password)
                record["rdp_password_ref"] = _SANDBOX_RDP_REF
        else:  # no vault wired (tests) — inline but NEVER logged
            record["token_secret"] = settings.proxmox_token_secret
            if settings.rdp_password:
                record["rdp_password"] = settings.rdp_password
        self._store.set(_SANDBOX_CONN_KEY, record)
        # Mark the sandbox step complete so the gate ungates.
        rec = self._store.get(_STEPS_KEY) or {"steps": []}
        steps = set(rec.get("steps", []))
        steps.add(WizardStep.SANDBOX.value)
        self._store.set(_STEPS_KEY, {"steps": sorted(steps)})
        log.info(
            "sandbox_connection_configured",
            node=settings.proxmox_node,
            template_vmid=int(settings.template_vmid),
            clone_mode=settings.clone_mode,
            takeover_method=settings.takeover_method,
        )

    def get_sandbox_connection(self) -> dict[str, Any]:
        """Return the persisted connection config WITHOUT secrets (for the UI)."""
        rec = self._store.get(_SANDBOX_CONN_KEY)
        if not rec:
            return {}
        return {
            k: v
            for k, v in rec.items()
            if k not in ("token_secret", "rdp_password", "token_secret_ref", "rdp_password_ref")
        }

    def sandbox_connection_configured(self) -> bool:
        """True once the Proxmox Windows connection has been collected (FR-OOBE)."""
        rec = self._store.get(_SANDBOX_CONN_KEY)
        return bool(
            rec and rec.get("proxmox_api_url") and rec.get("proxmox_node")
            and rec.get("template_vmid")
        )

    def resolve_sandbox_secret(self, which: str) -> str:
        """Unseal a sandbox secret by name (``token`` | ``rdp``); ``""`` if absent.

        Used only by the composition root to build the real Proxmox client; never
        exposed via an endpoint and never logged.
        """
        rec = self._store.get(_SANDBOX_CONN_KEY) or {}
        if which == "token":
            if "token_secret" in rec:
                return rec["token_secret"]
            ref = rec.get("token_secret_ref")
        elif which == "rdp":
            if "rdp_password" in rec:
                return rec["rdp_password"]
            ref = rec.get("rdp_password_ref")
        else:
            return ""
        if ref and self._credentials is not None:
            return self._retrieve_secret(ref) or ""
        return ""

    def is_sandbox_backend_ready(self) -> bool:
        """True if the selected sandbox backend is usable.

        The local backend is always ready; the native proxmox-windows backend is
        usable ONLY once its connection/login data has been collected (the gate).
        """
        if self._sandbox_backend != "proxmox-windows":
            return True
        return self.sandbox_connection_configured()

    # --- Settings > Automation (dark-engine audit items 82/84/85) ---------
    def get_automation_prefs(self) -> dict[str, Any]:
        """Return the persisted Automation-tab overrides (no defaults merged in).

        Only the keys an operator explicitly saved are present -- mirrors
        ``get_channels``. Callers (the setup router) merge this onto the
        env-sourced ``Settings`` defaults so the UI always shows a real,
        currently-effective value, not just "whatever was saved."
        """
        rec = self._store.get(_AUTOMATION_KEY)
        return dict(rec) if rec else {}

    def set_automation_prefs(
        self,
        *,
        egress_timezone: str | None = None,
        egress_locale: str | None = None,
        allow_automated_accounts: bool | None = None,
        presubmit_max_apps_per_company_per_day: int | None = None,
        pii_retention_days: int | None = None,
        presubmit_duplicate_cooldown_days: int | None = None,
    ) -> None:
        """Persist Automation-tab overrides (dark-engine audit items 82/84/85/87/88).

        ``None`` leaves the persisted value for that key untouched (the same
        "unset = no-op" convention ``set_quiet_hours`` uses) so a partial save
        from one control never clobbers the others. Server-side validation:
        the per-company cap, the data-retention window, and the re-apply
        cooldown can't go negative (the browser input already clamps this,
        but the engine never trusts a caller-supplied value alone -- see the
        fabrication-guard note in CLAUDE.md).

        ``pii_retention_days`` (item 87) mirrors ``config.py``'s
        ``PII_RETENTION_DAYS``: how many days parsed PII/EEO/intake data is
        kept before a retention sweep prunes it; ``0`` (the default) means
        "keep forever" -- no time-based prune. ``presubmit_duplicate_cooldown_
        days`` (item 88) mirrors ``PRESUBMIT_DUPLICATE_COOLDOWN_DAYS``: how
        many days must pass before the engine will re-apply to the same
        (company, role) pair.
        """
        if (
            presubmit_max_apps_per_company_per_day is not None
            and presubmit_max_apps_per_company_per_day < 0
        ):
            raise ValueError("The per-company daily cap cannot be negative.")
        if pii_retention_days is not None and pii_retention_days < 0:
            raise ValueError("The data-retention window cannot be negative.")
        if (
            presubmit_duplicate_cooldown_days is not None
            and presubmit_duplicate_cooldown_days < 0
        ):
            raise ValueError("The re-apply cooldown cannot be negative.")
        rec = self.get_automation_prefs()
        if egress_timezone is not None:
            rec["egress_timezone"] = (
                egress_timezone.strip() or AUTOMATION_PREFS_DEFAULTS["egress_timezone"]
            )
        if egress_locale is not None:
            rec["egress_locale"] = (
                egress_locale.strip() or AUTOMATION_PREFS_DEFAULTS["egress_locale"]
            )
        if allow_automated_accounts is not None:
            rec["allow_automated_accounts"] = bool(allow_automated_accounts)
        if presubmit_max_apps_per_company_per_day is not None:
            rec["presubmit_max_apps_per_company_per_day"] = int(
                presubmit_max_apps_per_company_per_day
            )
        if pii_retention_days is not None:
            rec["pii_retention_days"] = int(pii_retention_days)
        if presubmit_duplicate_cooldown_days is not None:
            rec["presubmit_duplicate_cooldown_days"] = int(
                presubmit_duplicate_cooldown_days
            )
        self._store.set(_AUTOMATION_KEY, rec)
        log.info(
            "automation_prefs_configured",
            egress_timezone=rec.get("egress_timezone"),
            egress_locale=rec.get("egress_locale"),
            allow_automated_accounts=rec.get("allow_automated_accounts"),
            presubmit_max_apps_per_company_per_day=rec.get(
                "presubmit_max_apps_per_company_per_day"
            ),
            pii_retention_days=rec.get("pii_retention_days"),
            presubmit_duplicate_cooldown_days=rec.get(
                "presubmit_duplicate_cooldown_days"
            ),
        )

    # --- status ----------------------------------------------------------
    def status(self) -> WizardStatus:
        steps = self._steps_complete()
        if self.is_setup_gate_open():
            steps.add(WizardStep.LLM.value)
        ordered = [s.value for s in STEP_ORDER if s.value in steps]
        current = next((s.value for s in STEP_ORDER if s.value not in steps), STEP_ORDER[-1].value)
        return WizardStatus(
            llm_configured=self.is_setup_gate_open(),
            channels_configured=WizardStep.CHANNELS.value in steps,
            fonts_ready=WizardStep.FONTS.value in steps,
            onboarding_complete=WizardStep.ONBOARDING.value in steps,
            current_step=current,
            steps_complete=ordered,
        )

    # --- LLM settings / tier ladder (FR-LLM-2/3) -------------------------
    def configure_llm(self, settings: LLMSettings) -> None:
        """Set the L1 tier (creates or replaces the first ladder rung)."""
        if not settings.provider or not settings.model:
            raise ValueError("LLM provider and model are required.")
        # Item 12 (SSRF): the LLM base_url is operator-supplied; reject non-http(s) /
        # cloud-metadata targets (local Ollama / private endpoints are allowed).
        validate_operator_url(settings.base_url, field="LLM base_url")
        tier = self._tier_to_record(
            TierSettings(
                provider=settings.provider,
                base_url=settings.base_url,
                model=settings.model,
                api_key=settings.api_key,
                context_window=settings.context_window,
            ),
            tier_no=1,
        )
        tiers = self._load_tiers()
        if tiers:
            tiers[0] = tier
        else:
            tiers = [tier]
        self._save_tiers(tiers)
        log.info("llm_configured", provider=settings.provider, model=settings.model)
        # Re-arm the live LLM adapter so this runtime change takes effect without a
        # restart (the boot-time adapter otherwise keeps its stale ladder).
        self._fire_llm_config_change()

    def configure_llm_from_endpoint(
        self, *, endpoint_resolver: Callable[[], dict[str, Any] | None], model: str
    ) -> None:
        """Configure the LLM from a saved model endpoint + a chosen model.

        ``endpoint_resolver`` returns the endpoint's ``{base_url, api_key, name}``
        (the caller resolves the sealed key); this maps the user's setup-page choice
        into the LLM tier ladder so picking an endpoint + model actually wires the
        model the rest of the app uses.
        """
        ep = endpoint_resolver()
        if ep is None:
            raise ValueError("Unknown model endpoint; add it first.")
        if not model:
            raise ValueError("Choose a model for the endpoint.")
        base_url = ep.get("base_url", "")
        provider = "ollama" if ("11434" in base_url or "ollama" in base_url.lower()) else "openai"
        self.configure_llm(
            LLMSettings(
                provider=provider,
                base_url=base_url,
                api_key=ep.get("api_key", ""),
                model=model,
            )
        )

    def get_tiers(self) -> list[dict[str, Any]]:
        """Return the persisted ladder as non-secret records (for the UI)."""
        return [{k: v for k, v in t.items() if k != "api_key"} for t in self._load_tiers()]

    def set_tiers(self, tiers: list[TierSettings]) -> None:
        """Replace the whole ladder (reorder/add/remove; 1-N, FR-LLM-3).

        Key preservation: a tier may carry only an ``api_key_ref`` (no new
        ``api_key``) to keep its already-sealed key across an edit/reorder. We
        resolve EVERY tier's effective key against the CURRENT stored state FIRST
        (phase 1), then re-seal at the new positions (phase 2) — so re-sealing one
        tier never clobbers the secret another tier is preserving by ref.
        """
        if not tiers:
            raise ValueError("At least one tier is required.")
        if len(tiers) > _DEFAULT_MAX_TIERS:
            raise ValueError(f"At most {_DEFAULT_MAX_TIERS} tiers are supported.")
        # Item 12 (SSRF): each tier's operator-supplied base_url is guarded.
        for t in tiers:
            validate_operator_url(t.base_url, field="LLM base_url")
        # Phase 1 — resolve effective keys from current state (reads only, no writes).
        effective_keys: list[str] = []
        for t in tiers:
            key = t.api_key
            if not key and getattr(t, "api_key_ref", ""):
                key = self._resolve_secret({"api_key_ref": t.api_key_ref})
            effective_keys.append(key or "")
        # Phase 2 — build + seal at the new positions.
        records = [
            self._tier_to_record(t, i + 1, effective_keys[i])
            for i, t in enumerate(tiers)
        ]
        for r in records:
            if not r["provider"] or not r["model"]:
                raise ValueError("Each tier needs provider and model.")
        self._save_tiers(records)
        log.info("llm_ladder_set", tiers=len(records))
        # Re-arm the live LLM adapter so a runtime ladder edit/reorder applies at once.
        self._fire_llm_config_change()

    def build_ladder(self) -> TierLadder | None:
        """Materialize a :class:`TierLadder` from persisted config (with secrets)."""
        tiers = self._load_tiers()
        if not tiers:
            return None
        configs = [
            TierConfig(
                provider=t["provider"],
                base_url=t.get("base_url", ""),
                model=t["model"],
                api_key=self._resolve_secret(t),
                context_window=int(t.get("context_window", 8192)),
            )
            for t in tiers
        ]
        return TierLadder(tiers=configs)

    def _tier_to_record(
        self, tier: TierSettings, tier_no: int, key: str | None = None
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "provider": tier.provider,
            "base_url": tier.base_url,
            "model": tier.model,
            "context_window": tier.context_window,
        }
        # ``key`` is the pre-resolved effective key (phase 1 of set_tiers); when not
        # supplied, fall back to the tier's inline key (direct callers).
        effective = key if key is not None else tier.api_key
        if effective:
            if self._credentials is not None:
                # Seal the key in the credential store; persist only a marker.
                self._store_secret(f"llm.tier{tier_no}", effective)
                record["api_key_ref"] = f"llm.tier{tier_no}"
            else:
                # No credential store wired (tests): keep inline but never logged.
                record["api_key"] = effective
        return record

    def _resolve_secret(self, record: dict[str, Any]) -> str:
        if "api_key" in record:
            return record["api_key"]
        ref = record.get("api_key_ref")
        if ref and self._credentials is not None:
            cred = self._retrieve_secret(ref)
            return cred or ""
        return ""

    # --- credential-store helpers (LLM keys reuse the vault path) ---------
    def _store_secret(self, ref: str, secret: str) -> None:
        from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId
        from applicant.ports.driven.credential_store import Credential

        self._credentials.store(
            CampaignId(SYSTEM_CAMPAIGN_ID),
            Credential(tenant_key=ref, username="api_key", secret=secret),
        )

    def _retrieve_secret(self, ref: str) -> str | None:
        from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId

        cred = self._credentials.retrieve(CampaignId(SYSTEM_CAMPAIGN_ID), ref)
        return cred.secret if cred else None

    # --- gate + step advance ---------------------------------------------
    def is_setup_gate_open(self) -> bool:
        """True once the LLM gate is satisfied (FR-UI-5)."""
        return bool(self._load_tiers()) or self._llm_preconfigured

    def is_automated_work_allowed(self) -> bool:
        """True only when automated applying may begin (FR-UI-5, FR-ONBOARD-2).

        Requires ONLY: LLM configured (FR-UI-5) AND the required-to-apply essentials
        present (the apply-gate, wired through ``onboarding_gate``: target roles, work
        mode, locations, salary floor, key skills, and a résumé). The onboarding FORM
        requires virtually nothing — the agent gathers these over time — but applying
        is HARD-GATED until the essentials exist, so the loop BLOCKS rather than
        half-applies. Notification channels and the automation sandbox are OPTIONAL
        (they moved into Settings; in-app notifications always work and the default
        local sandbox is always ready), so neither gates work here.
        """
        return self.is_setup_gate_open() and self._onboarding_complete_now()

    def advance_step(self, step: WizardStep) -> WizardStatus:
        """Mark a wizard step complete (FR-OOBE-2). LLM is gated by its config."""
        if step is WizardStep.LLM and not self.is_setup_gate_open():
            raise ValueError("Configure the LLM before completing the LLM step.")
        if step is WizardStep.SANDBOX and not self._sandbox_step_complete_now():
            raise ValueError(
                "The Proxmox Windows connection is not configured; collect it before "
                "advancing (FR-OOBE, proxmox-windows backend)."
            )
        if step is WizardStep.ONBOARDING and not self._onboarding_complete_now():
            # The onboarding step only completes when the intake is complete
            # (FR-ONBOARD-2). When no real gate is wired, the local flag is used.
            if self._onboarding_gate is not None:
                raise ValueError(
                    "Onboarding intake is not complete; finish it before advancing."
                )
        if step is WizardStep.FONTS:
            self._fonts_ready = True
        elif step is WizardStep.ONBOARDING:
            self._onboarding_complete = True
        rec = self._store.get(_STEPS_KEY) or {"steps": []}
        steps = set(rec.get("steps", []))
        steps.add(step.value)
        self._store.set(_STEPS_KEY, {"steps": sorted(steps)})
        log.info("wizard_step_complete", step=step.value)
        return self.status()
