"""EPIC STEALTH — the dedicated Stealth settings surface (FR-STEALTH-1/-4).

The single Settings home for the anti-detect / egress / residential-reputation
posture described in ``docs/APPLICANT-BACKLOG.md`` §EPIC STEALTH. It mirrors the
MODEL-CONFIG settings surface pattern (a settings router the ``a0-applicant`` shell
reaches through a matching api proxy + webui panel), and it is deliberately THIN
over plumbing that already exists — it does NOT fork a second config store:

  * the EXISTING egress/browser fields (``egress_mode`` / ``egress_proxy_url`` /
    ``egress_residential`` / ``browser_engine``) are read from + written back
    through ``SetupService.get_automation_prefs`` / ``set_automation_prefs`` — the
    SAME persistence + SSRF/enum validation the Settings > Automation surface uses,
    so there is exactly one source of truth for them (no drift, no fork);
  * the NEW stealth-only fields (per-source proxy policy, residential enable +
    sticky sessid, WebRTC suppression, request pacing / rate-limit, block-detect
    thresholds) are persisted as ONE namespaced record (``stealth.prefs``) on the
    SAME :class:`AppConfigStore` the SetupService uses — the established "one JSON
    key per settings group" pattern (``automation.prefs`` / ``channels`` /
    ``telemetry`` all do this), NOT a second store.

EPIC STEALTH principle: every stealth value is a PRESET DEFAULT that is CHANGEABLE
here — a fresh install shows the recommended posture (VPS egress, camoufox on,
WebRTC suppressed, selective residential escalation, paced requests) and the
operator overrides any of it from the panel.

The pure helpers (:class:`StealthPrefsStore`, :func:`build_stealth_view`,
:func:`apply_stealth_update`, the validators) are module-level so they are
unit-testable without the framework — the FastAPI handlers are a thin shell over
them. Mirrors ``a0-applicant/api/tiers.py`` / ``model_config.py`` on the proxy side.

WIRING: this router is NOT registered here (shared wiring —
``src/applicant/app/routers/__init__.py`` and ``container.py`` — is owned by the
Integrate step). Register it additively::

    from applicant.app.routers import stealth      # add to the import block
    app.include_router(stealth.router)              # ungated, alongside setup/automation

No new container binding is needed: the router reuses ``container.settings`` +
``container.setup_service`` (whose config store already backs ``automation.prefs``),
both of which are wired in ``deps.get_container`` today.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.adapters.storage.app_config_store import (
    AppConfigStore,
    InMemoryAppConfigStore,
)
from applicant.app.deps import get_container
from applicant.core.stealth_policy import (
    STEALTH_RUNTIME_DEFAULTS,
    StealthPosture,
    resolve_stealth_posture,
)

router = APIRouter(prefix="/api/setup/stealth", tags=["setup", "stealth"])


# ---------------------------------------------------------------------------
# Enums / presets (pure — importable + unit-testable without the framework)
# ---------------------------------------------------------------------------

#: The namespaced app-config key holding the NEW stealth-only prefs (one JSON
#: record, same pattern as ``automation.prefs``). The EXISTING egress/browser
#: fields are NOT duplicated here — they live in ``automation.prefs`` and are
#: read/written through ``SetupService`` so there is a single source of truth.
STEALTH_PREFS_KEY = "stealth.prefs"

#: Egress ROUTE (the panel's primary 3-way, FR-STEALTH-4 + [[VPS Egress Node]]).
#: ``home`` / ``vps`` both egress via the host network route (the WireGuard VPS
#: tunnel when it is configured — which the network layer, not the app, enforces),
#: so both map to the engine's ``direct`` egress mode; ``residential`` threads the
#: attested residential proxy into the browser launch (engine ``residential-proxy``).
EGRESS_ROUTE_HOME = "home"
EGRESS_ROUTE_VPS = "vps"
EGRESS_ROUTE_RESIDENTIAL = "residential"
EGRESS_ROUTES = (EGRESS_ROUTE_HOME, EGRESS_ROUTE_VPS, EGRESS_ROUTE_RESIDENTIAL)

#: Engine-level egress modes (mirror ``config.EGRESS_MODES``; kept local only for
#: the route<->mode mapping — the authoritative validation stays in
#: ``SetupService.set_automation_prefs`` / ``Settings``, never forked here).
_ENGINE_EGRESS_DIRECT = "direct"
_ENGINE_EGRESS_RESIDENTIAL_PROXY = "residential-proxy"

#: Per-source residential-proxy policy (ST-2/ST-5 selective escalation — conserve
#: the residential IP's reputation + GB). ``selective`` (default): only escalate a
#: source to the residential proxy after a block is detected; ``always``: route
#: every hard source through it; ``never``: never escalate (direct only).
PROXY_POLICY_SELECTIVE = "selective"
PROXY_POLICY_ALWAYS = "always"
PROXY_POLICY_NEVER = "never"
PROXY_POLICIES = (PROXY_POLICY_SELECTIVE, PROXY_POLICY_ALWAYS, PROXY_POLICY_NEVER)

#: Browser engines (mirror ``config.BROWSER_ENGINES``; camoufox on/off is surfaced
#: as a single checkbox that maps to the engine's ``browser_engine`` field).
_BROWSER_ENGINE_CAMOUFOX = "camoufox"
_BROWSER_ENGINE_CHROMIUM = "chromium"

#: Bounds for the numeric knobs — reject an absurd value at save instead of
#: persisting something the engine would have to clamp later.
_MAX_PACING_MS = 60_000
_MAX_RATE_PER_MIN = 6_000
_MAX_BLOCK_THRESHOLD = 100
_MAX_SESSID_LEN = 64

#: Preset DEFAULTS for the NEW stealth-only fields. Every value is a CHANGEABLE
#: default (EPIC STEALTH principle) — merged in by ``build_stealth_view`` so a
#: fresh install (nothing saved) shows the recommended posture. The stealth-only
#: subset lives in ``core.stealth_policy.STEALTH_RUNTIME_DEFAULTS`` (the SAME presets
#: the runtime resolver falls back to, so the panel display == runtime); this adds
#: only the display-only ``egress_route``.
STEALTH_PREFS_DEFAULTS: dict[str, Any] = {
    "egress_route": EGRESS_ROUTE_VPS,
    **STEALTH_RUNTIME_DEFAULTS,
}


class StealthPrefsIn(BaseModel):
    """Settings > Stealth body — every field optional / ``None`` = leave the saved
    value untouched (partial-update convention, mirrors ``AutomationPrefsIn`` /
    ``QuietHoursIn``) so the panel can PUT just the one control that changed.

    ``egress_route`` / ``egress_proxy_url`` / ``egress_residential`` /
    ``camoufox_enabled`` are DERIVED onto the existing engine automation-prefs
    fields; the rest persist to the ``stealth.prefs`` record.
    """

    #: Primary egress route (home/vps/residential). Drives the engine egress mode.
    egress_route: str | None = None
    #: Residential proxy URL (SSRF-validated by ``set_automation_prefs``; may embed
    #: credentials, plain-stored like ``discovery_proxies`` — matches that precedent).
    egress_proxy_url: str | None = None
    #: Operator attestation that the configured proxy is a genuine residential exit.
    egress_residential: bool | None = None
    #: Whether residential escalation is permitted at all (master switch, ST-5).
    residential_enabled: bool | None = None
    #: Sticky session id (one identity per browse->apply flow, ST-5). Empty = the
    #: engine mints a per-flow id automatically.
    residential_sticky_sessid: str | None = None
    #: Per-source residential escalation policy (selective/always/never).
    per_source_proxy_policy: str | None = None
    #: Camoufox anti-detect browser on/off (maps to ``browser_engine``).
    camoufox_enabled: bool | None = None
    #: WebRTC-leak suppression (ST-3/ST-5 — no local-IP leak past the proxy).
    webrtc_suppression: bool | None = None
    #: Human-like request pacing: minimum delay between requests, milliseconds.
    request_pacing_ms: int | None = None
    #: Request rate ceiling (requests/minute) for the automation crawler.
    request_rate_per_min: int | None = None
    #: Consecutive detected blocks before escalating a source (ST-6).
    block_detect_threshold: int | None = None
    #: HTTP statuses treated as a block (comma-separated, e.g. ``403,429,503``).
    block_detect_statuses: str | None = None


# ---------------------------------------------------------------------------
# Persistence — a thin namespaced view over the SAME AppConfigStore (no fork)
# ---------------------------------------------------------------------------


class StealthPrefsStore:
    """Read/write the NEW stealth-only prefs under one namespaced key.

    Wraps any :class:`AppConfigStore` (the SAME instance the SetupService uses), so
    this is a new *key*, not a new *store* — mirrors how ``SetupService`` keeps
    ``automation.prefs`` / ``channels`` / ``telemetry`` as sibling records. Only
    the keys an operator explicitly saved are returned (``get_raw``); defaults are
    merged by :func:`build_stealth_view`, matching ``get_automation_prefs``.
    """

    def __init__(self, store: AppConfigStore) -> None:
        self._store = store

    def get_raw(self) -> dict[str, Any]:
        return dict(self._store.get(STEALTH_PREFS_KEY) or {})

    def update(self, values: dict[str, Any]) -> None:
        """Merge ``values`` (already validated) into the record; ``None`` skips a key."""
        rec = dict(self._store.get(STEALTH_PREFS_KEY) or {})
        for key, val in values.items():
            if val is not None:
                rec[key] = val
        self._store.set(STEALTH_PREFS_KEY, rec)


def _stealth_prefs_store(setup_service: Any) -> StealthPrefsStore:
    """Build a :class:`StealthPrefsStore` over the SetupService's own config store.

    Reuses the boot config store (SqlAlchemy-backed when a DB is configured, so the
    prefs survive restarts; in-memory otherwise). Degrades to a fresh in-memory
    store if the service exposes none, so the endpoint never 500s on a bare service.
    """
    store = getattr(setup_service, "_store", None)
    if store is None:
        store = InMemoryAppConfigStore()
    return StealthPrefsStore(store)


def resolve_effective_posture(settings: Any, setup_service: Any) -> StealthPosture:
    """Resolve the effective runtime stealth posture from the persisted prefs.

    The glue that lets the runtime (container.py wiring + the live re-read callables)
    fold the persisted Settings > Stealth prefs OVER the env ``Settings`` the SAME way
    the panel view does: it reads ``automation.prefs`` via ``SetupService`` and the
    ``stealth.prefs`` record via :class:`StealthPrefsStore` (the SAME config store —
    NO second store) and hands both to the pure core resolver
    (``core.stealth_policy.resolve_stealth_posture``).

    Read fresh each call so a panel save governs the browser/discovery egress WITHOUT
    an engine restart (mirrors ``container._effective_smart_routing`` /
    ``_LivePresubmitSafetyParams``). SAFETY: selects app-level egress/proxy posture
    only — never the host wg0/VPS route that protects the home IP.
    """
    automation_prefs = setup_service.get_automation_prefs()
    stealth_prefs = _stealth_prefs_store(setup_service).get_raw()
    return resolve_stealth_posture(settings, automation_prefs, stealth_prefs)


# ---------------------------------------------------------------------------
# Validation (pure — raise ValueError; the router maps that to HTTP 400)
# ---------------------------------------------------------------------------


def _validate_choice(value: str, allowed: tuple[str, ...], field: str) -> str:
    norm = (value or "").strip().lower()
    if norm not in allowed:
        raise ValueError(f"{field} must be one of {allowed} (got {value!r}).")
    return norm


def _validate_int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    try:
        iv = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a whole number (got {value!r}).") from exc
    if iv < minimum or iv > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum} (got {iv}).")
    return iv


def _validate_sessid(value: str) -> str:
    """A sticky session label: empty (auto) or a short URL/label-safe token."""
    v = (value or "").strip()
    if not v:
        return v
    if len(v) > _MAX_SESSID_LEN:
        raise ValueError(f"Sticky session id must be at most {_MAX_SESSID_LEN} characters.")
    if not all(c.isalnum() or c in "-_" for c in v):
        raise ValueError("Sticky session id may only contain letters, digits, '-' and '_'.")
    return v


def _validate_statuses(value: str) -> str:
    """A comma-separated list of HTTP status codes (100-599). Empty is allowed."""
    raw = (value or "").strip()
    if not raw:
        return raw
    codes: list[str] = []
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue
        try:
            code = int(entry)
        except ValueError as exc:
            raise ValueError(f"Block-detect statuses must be HTTP codes (got {entry!r}).") from exc
        if code < 100 or code > 599:
            raise ValueError(f"Block-detect status {code} is not a valid HTTP status (100-599).")
        codes.append(str(code))
    if not codes:
        return ""
    return ",".join(codes)


def _route_from_engine_mode(engine_mode: str) -> str:
    """Best-effort route inferred from the engine egress mode when the operator has
    not explicitly picked a route in this panel: ``residential-proxy`` -> the
    residential route; anything else -> the recommended default (VPS)."""
    if (engine_mode or "").strip().lower() == _ENGINE_EGRESS_RESIDENTIAL_PROXY:
        return EGRESS_ROUTE_RESIDENTIAL
    return STEALTH_PREFS_DEFAULTS["egress_route"]


def _engine_mode_from_route(route: str) -> str:
    """Map the panel's 3-way route onto the engine's 2-way egress mode.

    ``residential`` -> ``residential-proxy`` (thread the proxy into the browser);
    ``home`` / ``vps`` -> ``direct`` (egress via the host route — the WireGuard VPS
    tunnel when configured, which is a network-layer fact the app cannot toggle).
    """
    if route == EGRESS_ROUTE_RESIDENTIAL:
        return _ENGINE_EGRESS_RESIDENTIAL_PROXY
    return _ENGINE_EGRESS_DIRECT


# ---------------------------------------------------------------------------
# View builder + update applier (pure)
# ---------------------------------------------------------------------------


def build_stealth_view(
    settings: Any, automation_prefs: dict[str, Any], stealth_prefs: dict[str, Any]
) -> dict[str, Any]:
    """Assemble the effective Stealth view for the panel.

    ``automation_prefs`` = the persisted Settings > Automation overrides (only
    saved keys); ``stealth_prefs`` = the RAW ``stealth.prefs`` record (only saved
    keys). Existing engine fields prefer a persisted override, else the env-sourced
    ``Settings`` default; the stealth-only fields fall back to
    :data:`STEALTH_PREFS_DEFAULTS`. The result always reflects what the running
    engine would actually use today, even before anything was saved here.
    """
    auto = automation_prefs or {}
    prefs = stealth_prefs or {}

    egress_mode = auto.get("egress_mode", getattr(settings, "egress_mode", _ENGINE_EGRESS_DIRECT))
    egress_proxy_url = auto.get("egress_proxy_url", getattr(settings, "egress_proxy_url", ""))
    egress_residential = bool(
        auto.get("egress_residential", getattr(settings, "egress_residential", False))
    )
    browser_engine = auto.get(
        "browser_engine", getattr(settings, "browser_engine", _BROWSER_ENGINE_CAMOUFOX)
    )

    # egress_route: an explicitly-saved value wins; else infer from the engine mode.
    saved_route = prefs.get("egress_route")
    egress_route = (
        saved_route if saved_route in EGRESS_ROUTES else _route_from_engine_mode(egress_mode)
    )

    def _pref(key: str) -> Any:
        return prefs.get(key, STEALTH_PREFS_DEFAULTS[key])

    view = {
        # --- egress (existing engine fields, single source of truth) ---
        "egress_route": egress_route,
        "egress_mode": egress_mode,  # derived engine value (read-only echo)
        "egress_proxy_url": egress_proxy_url,
        "egress_residential": egress_residential,
        # --- residential conservation (new) ---
        "residential_enabled": bool(_pref("residential_enabled")),
        "residential_sticky_sessid": _pref("residential_sticky_sessid"),
        "per_source_proxy_policy": _pref("per_source_proxy_policy"),
        # --- browser fingerprint (existing) ---
        "camoufox_enabled": browser_engine == _BROWSER_ENGINE_CAMOUFOX,
        "browser_engine": browser_engine,
        # --- leak suppression + pacing + block detection (new) ---
        "webrtc_suppression": bool(_pref("webrtc_suppression")),
        "request_pacing_ms": int(_pref("request_pacing_ms")),
        "request_rate_per_min": int(_pref("request_rate_per_min")),
        "block_detect_threshold": int(_pref("block_detect_threshold")),
        "block_detect_statuses": _pref("block_detect_statuses"),
        # --- select choices for the UI ---
        "choices": {
            "egress_route": list(EGRESS_ROUTES),
            "per_source_proxy_policy": list(PROXY_POLICIES),
        },
    }
    # Non-blocking coherence hints (honest, like model_config's endpoint_missing badge).
    warnings: list[str] = []
    if egress_route == EGRESS_ROUTE_RESIDENTIAL and not (egress_proxy_url or "").strip():
        warnings.append(
            "Residential egress is selected but no proxy URL is set — the browser "
            "will refuse to launch until one is provided."
        )
    if (
        egress_route == EGRESS_ROUTE_RESIDENTIAL
        and (egress_proxy_url or "").strip()
        and not egress_residential
    ):
        warnings.append(
            "Residential egress is selected but the proxy is not attested as "
            "residential — a datacenter exit is refused. Confirm the attestation."
        )
    view["warnings"] = warnings
    return view


def _validate_and_split(body: StealthPrefsIn) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the incoming body and split it into (automation-prefs kwargs,
    stealth-prefs values). Raises ``ValueError`` on any invalid field so the router
    can 400 BEFORE anything is persisted (no partial write).
    """
    auto_kwargs: dict[str, Any] = {}
    stealth_values: dict[str, Any] = {}

    if body.egress_route is not None:
        route = _validate_choice(body.egress_route, EGRESS_ROUTES, "Egress route")
        stealth_values["egress_route"] = route
        # Derive the engine egress mode from the route (single source of truth).
        auto_kwargs["egress_mode"] = _engine_mode_from_route(route)

    if body.egress_proxy_url is not None:
        # SSRF validation is delegated to set_automation_prefs (its own guard);
        # pass the trimmed value through.
        auto_kwargs["egress_proxy_url"] = body.egress_proxy_url.strip()

    if body.egress_residential is not None:
        auto_kwargs["egress_residential"] = bool(body.egress_residential)

    if body.camoufox_enabled is not None:
        auto_kwargs["browser_engine"] = (
            _BROWSER_ENGINE_CAMOUFOX if body.camoufox_enabled else _BROWSER_ENGINE_CHROMIUM
        )

    if body.residential_enabled is not None:
        stealth_values["residential_enabled"] = bool(body.residential_enabled)

    if body.residential_sticky_sessid is not None:
        stealth_values["residential_sticky_sessid"] = _validate_sessid(
            body.residential_sticky_sessid
        )

    if body.per_source_proxy_policy is not None:
        stealth_values["per_source_proxy_policy"] = _validate_choice(
            body.per_source_proxy_policy, PROXY_POLICIES, "Per-source proxy policy"
        )

    if body.webrtc_suppression is not None:
        stealth_values["webrtc_suppression"] = bool(body.webrtc_suppression)

    if body.request_pacing_ms is not None:
        stealth_values["request_pacing_ms"] = _validate_int(
            body.request_pacing_ms, "Request pacing (ms)", minimum=0, maximum=_MAX_PACING_MS
        )

    if body.request_rate_per_min is not None:
        stealth_values["request_rate_per_min"] = _validate_int(
            body.request_rate_per_min,
            "Request rate (per minute)",
            minimum=0,
            maximum=_MAX_RATE_PER_MIN,
        )

    if body.block_detect_threshold is not None:
        stealth_values["block_detect_threshold"] = _validate_int(
            body.block_detect_threshold,
            "Block-detect threshold",
            minimum=1,
            maximum=_MAX_BLOCK_THRESHOLD,
        )

    if body.block_detect_statuses is not None:
        stealth_values["block_detect_statuses"] = _validate_statuses(body.block_detect_statuses)

    return auto_kwargs, stealth_values


def apply_stealth_update(
    body: StealthPrefsIn, setup_service: Any, store: StealthPrefsStore
) -> None:
    """Validate + persist a partial stealth update.

    Existing engine fields are written through ``SetupService.set_automation_prefs``
    (reusing its SSRF/enum validation + the ``automation.prefs`` record); the new
    stealth-only fields are written to ``stealth.prefs``. Validation runs FIRST, so
    an invalid field raises before any write (no partial persistence); the automation
    write runs before the stealth write, so if the former raises (e.g. a bad proxy
    URL) the stealth record is left untouched too.
    """
    auto_kwargs, stealth_values = _validate_and_split(body)
    if auto_kwargs:
        setup_service.set_automation_prefs(**auto_kwargs)
    if stealth_values:
        store.update(stealth_values)


# ---------------------------------------------------------------------------
# HTTP handlers (thin shell over the pure helpers above)
# ---------------------------------------------------------------------------


@router.get("")
def get_stealth(container=Depends(get_container)) -> dict:
    """Return the effective Stealth settings (FR-STEALTH-1/-4).

    Merges the persisted Settings > Automation egress/browser overrides + the
    ``stealth.prefs`` record onto the env-sourced ``Settings`` defaults so the panel
    always shows a real, currently-effective posture — even on a fresh install.
    """
    svc = container.setup_service
    automation_prefs = svc.get_automation_prefs()
    stealth_prefs = _stealth_prefs_store(svc).get_raw()
    return build_stealth_view(container.settings, automation_prefs, stealth_prefs)


@router.put("", status_code=status.HTTP_204_NO_CONTENT)
def set_stealth(body: StealthPrefsIn, container=Depends(get_container)) -> None:
    """Save a partial Stealth update (validated). Invalid input -> 400."""
    svc = container.setup_service
    try:
        apply_stealth_update(body, svc, _stealth_prefs_store(svc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
