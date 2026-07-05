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
#: Settings > Automation overrides (dark-engine audit items 82/84/85, plus
#: 86/90): the browser-fingerprint timezone/locale, whether the engine may
#: create ATS accounts from vaulted credentials, the per-company daily
#: application cap, how long a pending final-approval waits before timing out
#: (days, with an optional precise-seconds override), and how often the 24/7
#: loop ticks. Stored as an OVERRIDE record (only keys the operator actually
#: saved are present) exactly like ``_CHANNELS_KEY`` -- callers merge this
#: onto the env-sourced ``Settings`` defaults, so an unconfigured knob still
#: shows the value the running engine actually uses today.
_AUTOMATION_KEY = "automation.prefs"
#: Defaults duplicated here (NOT imported from ``applicant.app.config.Settings``)
#: so this module has zero import-time dependency on the pydantic settings
#: layer -- the same reason ``get_quiet_hours`` hardcodes "22:00"/"07:00"
#: rather than importing them. Keep in sync with ``config.py``'s field
#: defaults (egress_timezone/egress_locale/allow_automated_accounts/
#: presubmit_max_apps_per_company_per_day/approval_timeout_days/
#: approval_wait_seconds/scheduler_interval_seconds).
AUTOMATION_PREFS_DEFAULTS: dict[str, Any] = {
    "egress_timezone": "America/Phoenix",
    "egress_locale": "en-US",
    "allow_automated_accounts": False,
    "presubmit_max_apps_per_company_per_day": 3,
    "approval_timeout_days": 30,
    "approval_wait_seconds": None,
    "scheduler_interval_seconds": 60.0,
}

#: Allowed-value tuples for the SELECT-style Settings > Automation knobs added for
#: dark-engine audit items 92/93/94/96/100/103/104. Duplicated here (NOT imported
#: from ``applicant.app.config``) for the SAME reason ``AUTOMATION_PREFS_DEFAULTS``
#: duplicates its literals rather than importing ``Settings`` -- this module keeps
#: zero import-time dependency on the pydantic-settings layer. Keep in sync with
#: config.py's own ``SANDBOX_BACKENDS``/``STEALTH_PERSONAS``/``BROWSER_ENGINES``/
#: ``BROWSER_CHANNELS``/``TAKEOVER_DESKTOPS``/``REMOTE_VIEW_BACKENDS``.
_SANDBOX_BACKENDS = ("local", "proxmox-windows")
#: Empty string is ALSO valid (item 92): it means "auto-derive from the sandbox
#: backend", mirroring config.py's own ``STEALTH_PERSONA`` default of ``""``.
_STEALTH_PERSONAS = ("linux", "native")
_BROWSER_ENGINES = ("camoufox", "chromium")
_BROWSER_CHANNELS = ("chrome", "chromium")
#: Item 94: the assistant/loop tool-autonomy master switches. ``off`` (the
#: conservative default) never registers tools; ``auto`` registers them only when
#: the configured model also advertises tool calling (config.py CHAT_TOOLS/LOOP_TOOLS).
_TOOL_AUTONOMY_MODES = ("off", "auto")
#: Item 96: desktop-assist backend/capture-mode/approval-posture (config.py
#: COMPUTER_USE_BACKEND/_MODE/_APPROVALS).
_COMPUTER_USE_BACKENDS = ("noop", "cua")
_COMPUTER_USE_MODES = ("som", "ax")
_COMPUTER_USE_APPROVAL_MODES = ("manual", "session")
#: Item 100: the proactive-cadence knobs (CURATION_SCHEDULE/STATUS_UPDATE_SCHEDULE/
#: ESSENTIALS_NUDGE_SCHEDULE). The scheduler only distinguishes "off" from
#: "anything else" (scheduler.py), but the Settings UI offers the one meaningful
#: opt-in cadence (``daily``) rather than an unbounded free-text cron-like field.
_SCHEDULE_CADENCES = ("off", "daily")
#: Item 103: live-takeover desktop environment + remote-view backend (config.py
#: TAKEOVER_DESKTOP/REMOTE_VIEW_BACKEND).
_TAKEOVER_DESKTOPS = ("cinnamon", "xfce", "gnome", "pantheon")
_REMOTE_VIEW_BACKENDS = ("webtop", "neko")
#: Item 104: resume render fidelity (config.py RESUME_RENDER); ``auto`` degrades to
#: a deterministic stub when the real TeX/LibreOffice binaries are absent, ``on``
#: forces the real render, ``off`` forces the stub.
_RESUME_RENDER_MODES = ("auto", "on", "off")
#: Item 83: captcha-handling strategy (config.py CAPTCHA_STRATEGY) -- ``human``
#: (default, safe) hands every captcha to the operator; ``avoid`` lets
#: score/behavioral families proceed via the stealth layer while interactive
#: challenges still hand off; ``service`` additionally farms interactive
#: challenges to the third-party solving service below. This is a
#: consequential, terms-sensitive opt-in (a paid third party may see the
#: challenge), hence the plain-language warning on the Settings card.
_CAPTCHA_STRATEGIES = ("human", "avoid", "service")
#: Item 83: the third-party captcha-solving services the ``service`` strategy
#: may farm interactive challenges to (config.py CAPTCHA_SERVICE default
#: "capsolver"; mirrors the providers named in
#: ``adapters/captcha/solver_service.py``'s module docstring).
_CAPTCHA_SERVICES = ("capsolver", "2captcha", "anticaptcha")
#: Item 89: residential-egress mode (config.py EGRESS_MODE) -- ``direct`` (the
#: default) uses the host's own connection; ``residential-proxy`` routes
#: automation traffic through the attested-residential proxy configured below
#: (a datacenter exit is refused unless ``egress_residential`` is set True).
_EGRESS_MODES = ("direct", "residential-proxy")

#: Vault refs for the sandbox-connection secrets (Proxmox token secret, RDP pass).
_SANDBOX_TOKEN_REF = "sandbox.proxmox_token_secret"
_SANDBOX_RDP_REF = "sandbox.proxmox_rdp_password"
#: Vault ref for the captcha-solver API key (item 83, FR-VAULT-3). Mirrors the
#: sandbox-connection secret pattern: a non-empty key reseals it here and only a
#: marker (``captcha_api_key_ref``) is persisted in the plain config-store record.
_CAPTCHA_API_KEY_REF = "automation.captcha_api_key"
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

    # --- Settings > Automation (dark-engine audit items
    # 82/83/84/85/86/87/88/89/90/91/92/93/94/95/96/97/98/99/100/101/102/103/104/105/106/107) ---
    def get_automation_prefs(self) -> dict[str, Any]:
        """Return the persisted Automation-tab overrides (no defaults merged in).

        Only the keys an operator explicitly saved are present -- mirrors
        ``get_channels``. Callers (the setup router) merge this onto the
        env-sourced ``Settings`` defaults so the UI always shows a real,
        currently-effective value, not just "whatever was saved."

        Item 83 (SECURITY, FR-VAULT-3): the captcha-solver API key is a SECRET.
        This general-purpose accessor NEVER surfaces its raw value or vault-ref
        marker -- only a computed ``captcha_api_key_configured`` boolean, mirroring
        how ``get_sandbox_connection()`` filters the Proxmox secrets. The raw
        record (needed to preserve the vault linkage across a partial save) is
        read directly from the store inside ``set_automation_prefs``, NOT through
        this method.
        """
        rec = self._store.get(_AUTOMATION_KEY)
        if not rec:
            return {}
        out = dict(rec)
        out.pop("captcha_api_key", None)
        out.pop("captcha_api_key_ref", None)
        out["captcha_api_key_configured"] = bool(
            rec.get("captcha_api_key_ref") or rec.get("captcha_api_key")
        )
        return out

    def resolve_captcha_api_key(self) -> str:
        """Unseal the captcha-solver API key (item 83). Internal use only -- the
        composition root would wire this into the real solver adapter; never
        exposed via an endpoint and never logged."""
        rec = self._store.get(_AUTOMATION_KEY) or {}
        if "captcha_api_key" in rec:
            return rec["captcha_api_key"]
        ref = rec.get("captcha_api_key_ref")
        if ref and self._credentials is not None:
            return self._retrieve_secret(ref) or ""
        return ""

    def set_automation_prefs(
        self,
        *,
        egress_timezone: str | None = None,
        egress_locale: str | None = None,
        allow_automated_accounts: bool | None = None,
        presubmit_max_apps_per_company_per_day: int | None = None,
        pii_retention_days: int | None = None,
        presubmit_duplicate_cooldown_days: int | None = None,
        approval_timeout_days: int | None = None,
        approval_wait_seconds: float | None = None,
        scheduler_interval_seconds: float | None = None,
        ats_match_rate_floor: float | None = None,
        presubmit_eligibility_enabled: bool | None = None,
        presubmit_max_listing_age_days: int | None = None,
        memory_write_approval: bool | None = None,
        skills_write_approval: bool | None = None,
        memory_max_chars: int | None = None,
        user_max_chars: int | None = None,
        llm_smart_routing_prefer_local: bool | None = None,
        context_compress_threshold: int | None = None,
        loop_failure_alert_threshold: int | None = None,
        prefill_use_planner: bool | None = None,
        sandbox_backend: str | None = None,
        stealth_persona: str | None = None,
        browser_engine: str | None = None,
        browser_channel: str | None = None,
        chat_tools: str | None = None,
        loop_tools: str | None = None,
        material_research_enabled: bool | None = None,
        computer_use_backend: str | None = None,
        computer_use_mode: str | None = None,
        computer_use_approvals: str | None = None,
        curation_schedule: str | None = None,
        status_update_schedule: str | None = None,
        essentials_nudge_schedule: str | None = None,
        discovery_proxies: str | None = None,
        #: Item 80 (dark-engine audit B7): comma-separated custom job-board RSS
        #: feed URL list, SSRF/format-validated the same way ``discovery_proxies``
        #: is, and merged ALONGSIDE the hardcoded default feed at the discovery
        #: factory (never replacing it).
        discovery_rss_feeds: str | None = None,
        takeover_desktop: str | None = None,
        remote_view_backend: str | None = None,
        resume_render: str | None = None,
        #: Item 83: captcha-handling strategy ("human"/"avoid"/"service") + the
        #: third-party solving service used by "service". ``captcha_api_key`` is
        #: the SECRET solver-service API key: a non-empty value reseals it in the
        #: credential vault; ``None``/blank leaves any already-vaulted key alone
        #: (so a save of an unrelated field never wipes it, and the key is never
        #: required to be resent on every save).
        captcha_strategy: str | None = None,
        captcha_service: str | None = None,
        captcha_api_key: str | None = None,
        #: Item 89: residential-egress mode ("direct"/"residential-proxy"), the
        #: operator's explicit attestation that the configured proxy is a genuine
        #: residential exit, and the proxy URL itself.
        egress_mode: str | None = None,
        egress_residential: bool | None = None,
        egress_proxy_url: str | None = None,
    ) -> None:
        """Persist Automation-tab overrides (dark-engine audit items
        82/83/84/85/86/87/88/89/90/91/92/93/94/95/96/97/98/99/100/101/102/103/104/105/106/107).

        ``None`` leaves the persisted value for that key untouched (the same
        "unset = no-op" convention ``set_quiet_hours`` uses) so a partial save
        from one control never clobbers the others. Server-side validation:
        the per-company cap, the data-retention window, the re-apply cooldown,
        the approval timeout, and the scheduler interval can't go
        negative/non-positive (the browser inputs already clamp these, but the
        engine never trusts a caller-supplied value alone -- see the
        fabrication-guard note in CLAUDE.md).

        ``pii_retention_days`` (item 87) mirrors ``config.py``'s
        ``PII_RETENTION_DAYS``: how many days parsed PII/EEO/intake data is
        kept before a retention sweep prunes it; ``0`` (the default) means
        "keep forever" -- no time-based prune. ``presubmit_duplicate_cooldown_
        days`` (item 88) mirrors ``PRESUBMIT_DUPLICATE_COOLDOWN_DAYS``: how
        many days must pass before the engine will re-apply to the same
        (company, role) pair.

        ``ats_match_rate_floor`` (item 91, mirrors ``ATS_MATCH_RATE_FLOOR``):
        the minimum fields-filled ratio (0.0-1.0) below which an application
        is flagged for review instead of offered for submit.
        ``presubmit_eligibility_enabled`` (item 97, ``PRESUBMIT_ELIGIBILITY_
        ENABLED``): whether postings are filtered on work-authorization /
        sponsorship / clearance requirements. ``presubmit_max_listing_age_
        days`` (item 98, ``PRESUBMIT_MAX_LISTING_AGE_DAYS``): blocks postings
        older than this many days. ``memory_write_approval``/
        ``skills_write_approval`` (item 99, ``MEMORY_WRITE_APPROVAL``/
        ``SKILLS_WRITE_APPROVAL``): auto-apply vs staged memory/skills
        writes. ``memory_max_chars``/``user_max_chars`` (item 99,
        ``MEMORY_MAX_CHARS``/``USER_MAX_CHARS``): the curated-memory prompt
        budget caps, in characters -- must stay positive (a zero/negative
        budget would silently blank out the memory the loop relies on).
        ``llm_smart_routing_prefer_local`` (item 102, ``LLM_SMART_ROUTING_
        PREFER_LOCAL``): whether the smart router's tier ladder prefers a
        local endpoint when one is online. ``context_compress_threshold``
        (item 105, ``CONTEXT_COMPRESS_THRESHOLD``): the token budget above
        which older turns are compressed; ``0`` disables compression.
        ``loop_failure_alert_threshold`` (item 106, ``LOOP_FAILURE_ALERT_
        THRESHOLD``): consecutive tick failures before a stall alert fires --
        must be at least 1 (0/negative would alert on the first failure or
        never, mirroring the ``config.py`` field's own ``ge=1`` guard).
        ``prefill_use_planner`` (item 107, ``PREFILL_USE_PLANNER``): switches
        pre-fill to the experimental plan-as-data planner.

        ``sandbox_backend``/``stealth_persona`` (item 92, mirror config.py's
        ``SANDBOX_BACKEND``/``STEALTH_PERSONA``): which sandbox the engine
        automates in (``local`` container sandbox vs a native ``proxmox-
        windows`` VM) and the browser-fingerprint persona (``linux`` spoofed,
        ``native`` real identity, or ``""`` to auto-derive from the backend).
        ``browser_engine``/``browser_channel`` (item 93, ``BROWSER_ENGINE``/
        ``BROWSER_CHANNEL``): the browser ALL outbound automation routes
        through (``camoufox`` anti-detect vs ``chromium`` patchright+Chrome)
        and, for the ``chromium`` engine only, which channel it launches.
        ``chat_tools``/``loop_tools`` (item 94, ``CHAT_TOOLS``/``LOOP_TOOLS``):
        the assistant/loop tool-autonomy master switches -- ``off`` (default)
        never registers tools, ``auto`` registers them when the configured
        model also advertises tool calling. ``material_research_enabled``
        (item 95, ``MATERIAL_RESEARCH_ENABLED``): folds capped company
        research into cover-letter generation. ``computer_use_backend``/
        ``computer_use_mode``/``computer_use_approvals`` (item 96,
        ``COMPUTER_USE_BACKEND``/``_MODE``/``_APPROVALS``): the desktop-assist
        backend (``noop`` no side effects vs ``cua`` the real driver), capture
        mode (``som`` screenshot-with-elements vs ``ax`` accessibility-tree
        text), and approval posture (``manual`` per-action vs ``session``
        per-takeover). ``curation_schedule``/``status_update_schedule``/
        ``essentials_nudge_schedule`` (item 100, ``CURATION_SCHEDULE``/
        ``STATUS_UPDATE_SCHEDULE``/``ESSENTIALS_NUDGE_SCHEDULE``): the
        proactive-cadence knobs (``off`` or ``daily``) for the memory-curation
        nudge, the periodic campaign status push, and the "still blocked on
        essentials" reminder. ``discovery_proxies`` (item 101,
        ``DISCOVERY_PROXIES``): a comma-separated proxy list the discovery
        crawler routes through instead of direct egress; each entry is
        SSRF-checked the same way Apprise/ntfy URLs are (item 12).
        ``discovery_rss_feeds`` (item 80, ``DISCOVERY_RSS_FEEDS``): a
        comma-separated list of custom job-board RSS feed URLs, validated
        exactly like ``discovery_proxies`` above, and merged ALONGSIDE the
        engine's hardcoded default feed at the discovery factory (an empty
        value reproduces today's hardcoded-only behavior byte-identical).
        ``takeover_desktop``/``remote_view_backend`` (item 103,
        ``TAKEOVER_DESKTOP``/``REMOTE_VIEW_BACKEND``): the live-takeover
        desktop environment and remote-view technology. ``resume_render``
        (item 104, ``RESUME_RENDER``): resume render fidelity (``auto``
        degrades to a deterministic stub when TeX/LibreOffice are absent,
        ``on`` forces the real render, ``off`` forces the stub).

        ``captcha_strategy``/``captcha_service``/``captcha_api_key`` (item 83,
        ``CAPTCHA_STRATEGY``/``CAPTCHA_SERVICE``/``CAPTCHA_API_KEY``): whether
        captchas hand off to the operator (``human``, the safe default), are
        avoided where possible (``avoid``), or are additionally solved for
        interactive challenges by a paid third-party service (``service`` --
        a consequential, terms-sensitive opt-in: some sites' terms prohibit
        automated captcha solving, and the service is a paid external
        dependency, hence the Settings card's plain-language warning).
        ``captcha_api_key`` is the SECRET API key for that service: sealed in
        the credential vault (never the plain config-store record) and never
        echoed back by ``get_automation_prefs`` -- only a computed
        ``captcha_api_key_configured`` boolean is. A blank/omitted key leaves
        any already-vaulted key untouched.
        ``egress_mode``/``egress_residential``/``egress_proxy_url`` (item 89,
        ``EGRESS_MODE``/``EGRESS_RESIDENTIAL``/``EGRESS_PROXY_URL``): whether
        automation traffic exits directly (``direct``, the default) or through
        a residential proxy (``residential-proxy``), the operator's explicit
        attestation that the configured proxy is a genuine residential exit
        (a datacenter exit is refused otherwise), and the proxy URL itself.
        The proxy URL may legitimately embed credentials (``http://user:pass@
        host:port``) -- it is SSRF-validated the same way a single Apprise/ntfy
        URL is and, like ``discovery_proxies`` (which has the same embedded-
        credential shape), plain-stored rather than vaulted (matching that
        field's own precedent, not treated as a distinct secret).

        All of the above SELECT-style knobs are validated against their real
        allowed value set server-side (never trusting a caller-supplied value
        alone -- the fabrication-guard convention in CLAUDE.md) so a bad enum
        value 400s instead of silently persisting an inert/undefined setting.
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
        if approval_timeout_days is not None and approval_timeout_days < 0:
            raise ValueError("The approval timeout cannot be negative.")
        if approval_wait_seconds is not None and approval_wait_seconds < 0:
            raise ValueError("The approval wait override cannot be negative.")
        if scheduler_interval_seconds is not None and scheduler_interval_seconds <= 0:
            raise ValueError("The check interval must be greater than zero.")
        if ats_match_rate_floor is not None and not (0.0 <= ats_match_rate_floor <= 1.0):
            raise ValueError("The fill-rate floor must be between 0.0 and 1.0.")
        if (
            presubmit_max_listing_age_days is not None
            and presubmit_max_listing_age_days < 0
        ):
            raise ValueError("The maximum listing age cannot be negative.")
        if memory_max_chars is not None and memory_max_chars <= 0:
            raise ValueError("The memory character budget must be positive.")
        if user_max_chars is not None and user_max_chars <= 0:
            raise ValueError("The user-preferences character budget must be positive.")
        if context_compress_threshold is not None and context_compress_threshold < 0:
            raise ValueError("The context-compression threshold cannot be negative.")
        if loop_failure_alert_threshold is not None and loop_failure_alert_threshold < 1:
            raise ValueError("The failure-alert threshold must be at least 1.")
        if sandbox_backend is not None and sandbox_backend not in _SANDBOX_BACKENDS:
            raise ValueError(f"Sandbox backend must be one of {_SANDBOX_BACKENDS}.")
        if stealth_persona is not None and stealth_persona not in ("", *_STEALTH_PERSONAS):
            raise ValueError(
                f"Stealth persona must be one of {_STEALTH_PERSONAS} "
                "(or empty to auto-derive from the sandbox backend)."
            )
        if browser_engine is not None and browser_engine not in _BROWSER_ENGINES:
            raise ValueError(f"Browser engine must be one of {_BROWSER_ENGINES}.")
        if browser_channel is not None and browser_channel not in _BROWSER_CHANNELS:
            raise ValueError(f"Browser channel must be one of {_BROWSER_CHANNELS}.")
        if chat_tools is not None and chat_tools not in _TOOL_AUTONOMY_MODES:
            raise ValueError(
                f"Assistant tool autonomy must be one of {_TOOL_AUTONOMY_MODES}."
            )
        if loop_tools is not None and loop_tools not in _TOOL_AUTONOMY_MODES:
            raise ValueError(
                f"Loop tool autonomy must be one of {_TOOL_AUTONOMY_MODES}."
            )
        if computer_use_backend is not None and computer_use_backend not in _COMPUTER_USE_BACKENDS:
            raise ValueError(
                f"Desktop-assist backend must be one of {_COMPUTER_USE_BACKENDS}."
            )
        if computer_use_mode is not None and computer_use_mode not in _COMPUTER_USE_MODES:
            raise ValueError(
                f"Desktop-assist capture mode must be one of {_COMPUTER_USE_MODES}."
            )
        if (
            computer_use_approvals is not None
            and computer_use_approvals not in _COMPUTER_USE_APPROVAL_MODES
        ):
            raise ValueError(
                "Desktop-assist approval posture must be one of "
                f"{_COMPUTER_USE_APPROVAL_MODES}."
            )
        if curation_schedule is not None and curation_schedule not in _SCHEDULE_CADENCES:
            raise ValueError(f"Curation cadence must be one of {_SCHEDULE_CADENCES}.")
        if (
            status_update_schedule is not None
            and status_update_schedule not in _SCHEDULE_CADENCES
        ):
            raise ValueError(
                f"Status-update cadence must be one of {_SCHEDULE_CADENCES}."
            )
        if (
            essentials_nudge_schedule is not None
            and essentials_nudge_schedule not in _SCHEDULE_CADENCES
        ):
            raise ValueError(
                f"Essentials-nudge cadence must be one of {_SCHEDULE_CADENCES}."
            )
        if discovery_proxies is not None:
            # Item 12 (SSRF): each comma-separated proxy entry is guarded the
            # SAME way Apprise/ntfy URLs are -- reuses the existing helper
            # rather than re-implementing the check.
            validate_operator_urls(discovery_proxies, field="Discovery proxy")
        if discovery_rss_feeds is not None:
            # Item 80 (SSRF/format, B7): each comma-separated custom feed URL is
            # guarded the SAME way ``discovery_proxies`` is above -- reuses the
            # identical helper rather than re-implementing the check.
            validate_operator_urls(discovery_rss_feeds, field="RSS feed")
        if takeover_desktop is not None and takeover_desktop not in _TAKEOVER_DESKTOPS:
            raise ValueError(f"Takeover desktop must be one of {_TAKEOVER_DESKTOPS}.")
        if (
            remote_view_backend is not None
            and remote_view_backend not in _REMOTE_VIEW_BACKENDS
        ):
            raise ValueError(
                f"Remote-view backend must be one of {_REMOTE_VIEW_BACKENDS}."
            )
        if resume_render is not None and resume_render not in _RESUME_RENDER_MODES:
            raise ValueError(f"Resume render mode must be one of {_RESUME_RENDER_MODES}.")
        if captcha_strategy is not None and captcha_strategy not in _CAPTCHA_STRATEGIES:
            raise ValueError(f"Captcha strategy must be one of {_CAPTCHA_STRATEGIES}.")
        if captcha_service is not None and captcha_service not in _CAPTCHA_SERVICES:
            raise ValueError(
                f"Captcha solving service must be one of {_CAPTCHA_SERVICES}."
            )
        if egress_mode is not None and egress_mode not in _EGRESS_MODES:
            raise ValueError(f"Egress mode must be one of {_EGRESS_MODES}.")
        if egress_proxy_url is not None:
            # Item 12 (SSRF): a single URL, guarded the same way a single
            # Apprise/ntfy URL entry is (the plural discovery_proxies list uses
            # the comma-joined variant of this same helper above).
            validate_operator_url(egress_proxy_url, field="Egress proxy URL")
        # Item 83 (SECURITY): read the RAW stored record (NOT the filtered
        # get_automation_prefs()) so an already-vaulted captcha_api_key_ref stays
        # intact across a save that doesn't touch the captcha fields -- using the
        # filtered accessor here would silently drop the vault linkage on every
        # unrelated save.
        rec = dict(self._store.get(_AUTOMATION_KEY) or {})
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
        if approval_timeout_days is not None:
            rec["approval_timeout_days"] = int(approval_timeout_days)
        if approval_wait_seconds is not None:
            rec["approval_wait_seconds"] = float(approval_wait_seconds)
        if scheduler_interval_seconds is not None:
            rec["scheduler_interval_seconds"] = float(scheduler_interval_seconds)
        if ats_match_rate_floor is not None:
            rec["ats_match_rate_floor"] = float(ats_match_rate_floor)
        if presubmit_eligibility_enabled is not None:
            rec["presubmit_eligibility_enabled"] = bool(presubmit_eligibility_enabled)
        if presubmit_max_listing_age_days is not None:
            rec["presubmit_max_listing_age_days"] = int(presubmit_max_listing_age_days)
        if memory_write_approval is not None:
            rec["memory_write_approval"] = bool(memory_write_approval)
        if skills_write_approval is not None:
            rec["skills_write_approval"] = bool(skills_write_approval)
        if memory_max_chars is not None:
            rec["memory_max_chars"] = int(memory_max_chars)
        if user_max_chars is not None:
            rec["user_max_chars"] = int(user_max_chars)
        if llm_smart_routing_prefer_local is not None:
            rec["llm_smart_routing_prefer_local"] = bool(llm_smart_routing_prefer_local)
        if context_compress_threshold is not None:
            rec["context_compress_threshold"] = int(context_compress_threshold)
        if loop_failure_alert_threshold is not None:
            rec["loop_failure_alert_threshold"] = int(loop_failure_alert_threshold)
        if prefill_use_planner is not None:
            rec["prefill_use_planner"] = bool(prefill_use_planner)
        if sandbox_backend is not None:
            rec["sandbox_backend"] = sandbox_backend
        if stealth_persona is not None:
            rec["stealth_persona"] = stealth_persona
        if browser_engine is not None:
            rec["browser_engine"] = browser_engine
        if browser_channel is not None:
            rec["browser_channel"] = browser_channel
        if chat_tools is not None:
            rec["chat_tools"] = chat_tools
        if loop_tools is not None:
            rec["loop_tools"] = loop_tools
        if material_research_enabled is not None:
            rec["material_research_enabled"] = bool(material_research_enabled)
        if computer_use_backend is not None:
            rec["computer_use_backend"] = computer_use_backend
        if computer_use_mode is not None:
            rec["computer_use_mode"] = computer_use_mode
        if computer_use_approvals is not None:
            rec["computer_use_approvals"] = computer_use_approvals
        if curation_schedule is not None:
            rec["curation_schedule"] = curation_schedule
        if status_update_schedule is not None:
            rec["status_update_schedule"] = status_update_schedule
        if essentials_nudge_schedule is not None:
            rec["essentials_nudge_schedule"] = essentials_nudge_schedule
        if discovery_proxies is not None:
            rec["discovery_proxies"] = discovery_proxies.strip()
        if discovery_rss_feeds is not None:
            rec["discovery_rss_feeds"] = discovery_rss_feeds.strip()
        if takeover_desktop is not None:
            rec["takeover_desktop"] = takeover_desktop
        if remote_view_backend is not None:
            rec["remote_view_backend"] = remote_view_backend
        if resume_render is not None:
            rec["resume_render"] = resume_render
        if captcha_strategy is not None:
            rec["captcha_strategy"] = captcha_strategy
        if captcha_service is not None:
            rec["captcha_service"] = captcha_service
        if captcha_api_key:
            # Non-empty only -- a blank/omitted value leaves any already-vaulted
            # key untouched (see the param docstring above). SECRET: seal in the
            # credential vault; only a marker is ever persisted in this record.
            if self._credentials is not None:
                self._store_secret(_CAPTCHA_API_KEY_REF, captcha_api_key)
                rec["captcha_api_key_ref"] = _CAPTCHA_API_KEY_REF
                rec.pop("captcha_api_key", None)
            else:  # no vault wired (tests) -- inline but NEVER logged
                rec["captcha_api_key"] = captcha_api_key
        if egress_mode is not None:
            rec["egress_mode"] = egress_mode
        if egress_residential is not None:
            rec["egress_residential"] = bool(egress_residential)
        if egress_proxy_url is not None:
            # NOT a secret by this codebase's own precedent (matches
            # discovery_proxies, which has the identical embedded-credential
            # shape and is plain-stored, not vaulted) -- see the docstring above.
            rec["egress_proxy_url"] = egress_proxy_url.strip()
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
            approval_timeout_days=rec.get("approval_timeout_days"),
            approval_wait_seconds=rec.get("approval_wait_seconds"),
            scheduler_interval_seconds=rec.get("scheduler_interval_seconds"),
            ats_match_rate_floor=rec.get("ats_match_rate_floor"),
            presubmit_eligibility_enabled=rec.get("presubmit_eligibility_enabled"),
            presubmit_max_listing_age_days=rec.get("presubmit_max_listing_age_days"),
            memory_write_approval=rec.get("memory_write_approval"),
            skills_write_approval=rec.get("skills_write_approval"),
            memory_max_chars=rec.get("memory_max_chars"),
            user_max_chars=rec.get("user_max_chars"),
            llm_smart_routing_prefer_local=rec.get("llm_smart_routing_prefer_local"),
            context_compress_threshold=rec.get("context_compress_threshold"),
            loop_failure_alert_threshold=rec.get("loop_failure_alert_threshold"),
            prefill_use_planner=rec.get("prefill_use_planner"),
            sandbox_backend=rec.get("sandbox_backend"),
            stealth_persona=rec.get("stealth_persona"),
            browser_engine=rec.get("browser_engine"),
            browser_channel=rec.get("browser_channel"),
            chat_tools=rec.get("chat_tools"),
            loop_tools=rec.get("loop_tools"),
            material_research_enabled=rec.get("material_research_enabled"),
            computer_use_backend=rec.get("computer_use_backend"),
            computer_use_mode=rec.get("computer_use_mode"),
            computer_use_approvals=rec.get("computer_use_approvals"),
            curation_schedule=rec.get("curation_schedule"),
            status_update_schedule=rec.get("status_update_schedule"),
            essentials_nudge_schedule=rec.get("essentials_nudge_schedule"),
            discovery_proxies=rec.get("discovery_proxies"),
            # NEW field (item 80): the stricter bar noted above -- only whether one
            # is configured, not the raw feed URL list.
            discovery_rss_feeds_configured=bool(rec.get("discovery_rss_feeds")),
            takeover_desktop=rec.get("takeover_desktop"),
            remote_view_backend=rec.get("remote_view_backend"),
            resume_render=rec.get("resume_render"),
            captcha_strategy=rec.get("captcha_strategy"),
            captcha_service=rec.get("captcha_service"),
            # NEVER log the raw key -- only whether one is configured (item 83).
            captcha_api_key_configured=bool(
                rec.get("captcha_api_key_ref") or rec.get("captcha_api_key")
            ),
            egress_mode=rec.get("egress_mode"),
            egress_residential=rec.get("egress_residential"),
            # NEVER log the raw proxy URL -- it may embed a password (item 89);
            # log only whether one is configured, same care as the API key above
            # (discovery_proxies' own existing log line predates this stricter
            # bar and is out of scope here, but a NEW field must not repeat it).
            egress_proxy_url_configured=bool(rec.get("egress_proxy_url")),
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
