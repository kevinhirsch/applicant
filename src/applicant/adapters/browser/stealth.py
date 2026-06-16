"""Stealth / fingerprint-normalization + human-like interaction (FR-STEALTH-1..5).

This module is the *honest browser identity* toolkit shared by the browser
adapter. It is pure and deterministic-under-injection so the default test lane is
hermetic: every source of randomness (timing jitter, typing cadence, mouse path)
is driven by an injected :class:`random.Random` and an injected monotonic clock,
so tests pin a seed and assert exact values instead of sleeping on a wall clock.

What lives here (and the requirement each satisfies):

* :data:`NORMALIZED_FINGERPRINT` + :func:`fingerprint_is_coherent` — a single,
  internally-consistent honest identity: UA + locale ``en-US`` + tz
  ``America/Phoenix`` + realistic resolution + non-obvious WebGL/Canvas, where the
  OS implied by the UA never contradicts the WebGL renderer (FR-STEALTH-1).
* :class:`HumanInteraction` — human-like timing, typing cadence, mouse motion,
  scroll, and jitter, all from injected randomness/clock (FR-STEALTH-2).
* :class:`BrowserProfile` + :class:`ProfileStore` — a **persistent per-site/tenant**
  browser profile so the user appears as a returning real user (FR-STEALTH-3).
* :class:`EgressPolicy` — the residential-egress *config seam*: the engine must
  egress via the user's residential connection and MUST refuse a datacenter exit
  (FR-STEALTH-4). No real network here; this is the guardrail + seam.
* :data:`STEALTH_CAVEAT` — the honest best-effort UX caveat copy (FR-STEALTH-5).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# --- FR-STEALTH-1: coherent, honest browser identity ------------------------
#: A single internally-consistent fingerprint (UA/locale/timezone/resolution).
#: The OS implied by the UA must match the WebGL/Canvas renderer (no spoofing an
#: OS the WebGL contradicts) — that internal consistency is the whole point.
NORMALIZED_FINGERPRINT: dict[str, str] = {
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "locale": "en-US",
    "timezone": "America/Phoenix",
    "resolution": "1920x1080",
    "webgl_vendor": "Google Inc. (Intel)",
    "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "platform": "Win32",
}

#: FR-STEALTH-5: honest best-effort caveat surfaced in UX copy. Anti-detection is
#: never a guarantee; the user performing the irreducible human steps (account
#: submit, CAPTCHA, verification, final submit) is the strongest legitimacy lever.
STEALTH_CAVEAT = (
    "Anti-detection is best-effort, never a guarantee. The strongest legitimacy "
    "signal is you performing the irreducible human steps yourself: completing "
    "account creation, any CAPTCHA or verification, and the final submit in the "
    "live session. The engine pre-fills; you stay in control of the moments that "
    "matter."
)


def fingerprint_is_coherent(fp: dict[str, str]) -> bool:
    """True if the fingerprint is internally consistent (FR-STEALTH-1).

    The OS family in the UA must agree with the ``platform`` and the WebGL
    renderer must not contradict it (e.g. a Windows UA must not carry a macOS
    Metal renderer). Conservative checks; the real adapter expands these.
    """
    ua = fp.get("user_agent", "").lower()
    platform = fp.get("platform", "").lower()
    renderer = fp.get("webgl_renderer", "").lower()
    if "windows" in ua:
        if "win" not in platform:
            return False
        if "metal" in renderer or "apple" in renderer:
            return False
    if "mac os" in ua:
        if "win" in platform:
            return False
        if "direct3d" in renderer or "angle" in renderer:
            return False
    return bool(fp.get("locale") and fp.get("timezone") and fp.get("resolution"))


# --- FR-STEALTH-2: human-like interaction (deterministic under injection) ----
@dataclass(frozen=True)
class Keystroke:
    """A single typed character with the dwell (ms) the engine waits before it."""

    char: str
    delay_ms: float


@dataclass(frozen=True)
class MouseStep:
    """A point on a human-like (eased, jittered) mouse path."""

    x: float
    y: float


class HumanInteraction:
    """Human-like timing/cadence/motion driven by an INJECTED rng + clock.

    All randomness comes from ``rng`` (a ``random.Random``) and all "waiting" is
    accumulated against an injected logical clock (a mutable ``[float]`` of elapsed
    ms) rather than ``time.sleep`` — so tests are deterministic and never sleep.
    The real adapter feeds these delays/paths into Playwright's input APIs.
    """

    def __init__(
        self,
        rng: random.Random | None = None,
        *,
        base_keystroke_ms: float = 90.0,
        jitter_ms: float = 40.0,
    ) -> None:
        self._rng = rng or random.Random()
        self._base = base_keystroke_ms
        self._jitter = jitter_ms
        #: total simulated elapsed time in ms (a logical clock, not wall-clock).
        self.elapsed_ms: float = 0.0

    def type_cadence(self, text: str) -> list[Keystroke]:
        """Return a per-character keystroke plan with human-like dwell times.

        Cadence varies per character (FR-STEALTH-2); a brief extra pause follows
        word boundaries the way a real typist hesitates. Advances the logical
        clock so a caller can assert total typing time deterministically.
        """
        plan: list[Keystroke] = []
        for ch in text:
            delay = self._base + self._rng.uniform(-self._jitter, self._jitter)
            if ch == " ":
                delay += self._rng.uniform(20.0, 120.0)  # word-boundary hesitation
            delay = max(15.0, delay)
            self.elapsed_ms += delay
            plan.append(Keystroke(char=ch, delay_ms=round(delay, 3)))
        return plan

    def think_delay(self, *, min_ms: float = 250.0, max_ms: float = 1500.0) -> float:
        """A pause between fields, as a human reads/scans before typing."""
        delay = self._rng.uniform(min_ms, max_ms)
        self.elapsed_ms += delay
        return round(delay, 3)

    def mouse_path(
        self, start: tuple[float, float], end: tuple[float, float], *, steps: int = 12
    ) -> list[MouseStep]:
        """Eased, jittered mouse path from ``start`` to ``end`` (FR-STEALTH-2).

        Uses an ease-in-out interpolation plus small per-step jitter so the path is
        a believable curve, never a straight teleport. Deterministic under ``rng``.
        """
        sx, sy = start
        ex, ey = end
        path: list[MouseStep] = []
        for i in range(steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)  # smoothstep ease-in-out
            jx = self._rng.uniform(-1.5, 1.5) if 0 < i < steps else 0.0
            jy = self._rng.uniform(-1.5, 1.5) if 0 < i < steps else 0.0
            path.append(
                MouseStep(
                    x=round(sx + (ex - sx) * eased + jx, 3),
                    y=round(sy + (ey - sy) * eased + jy, 3),
                )
            )
        return path

    def scroll_plan(self, total_px: int, *, step_px: int = 120) -> list[int]:
        """A list of incremental scroll deltas summing to ``total_px``.

        Real users scroll in jittered chunks, not one jump (FR-STEALTH-2).
        """
        remaining = total_px
        deltas: list[int] = []
        while remaining > 0:
            chunk = min(remaining, step_px + self._rng.randint(-30, 30))
            chunk = max(1, chunk)
            deltas.append(chunk)
            remaining -= chunk
        return deltas


# --- FR-STEALTH-3: persistent per-site/tenant browser profile ----------------
@dataclass
class BrowserProfile:
    """A persistent per-tenant browser profile (cookies/storage/profile dir).

    Workday is per-tenant, so the profile key is the tenant. Keeping the profile
    around between sessions makes the user look like a returning real user
    (FR-STEALTH-3). The real adapter points Playwright's persistent-context user
    data dir at :attr:`user_data_dir`.
    """

    tenant_key: str
    user_data_dir: str
    fingerprint: dict[str, str] = field(default_factory=lambda: dict(NORMALIZED_FINGERPRINT))
    visit_count: int = 0


class ProfileStore:
    """Persistent per-tenant profile registry (FR-STEALTH-3).

    In-memory here (the real adapter persists the user-data dir on disk), but the
    contract is real: the SAME profile (and thus the same fingerprint) is returned
    for a tenant across sessions, and the visit count increments so a tenant a user
    has visited before is recognizably a returning visitor.
    """

    def __init__(self, root_dir: str = "profiles") -> None:
        self._root = root_dir.rstrip("/")
        self._profiles: dict[str, BrowserProfile] = {}

    def for_tenant(self, tenant_key: str) -> BrowserProfile:
        profile = self._profiles.get(tenant_key)
        if profile is None:
            profile = BrowserProfile(
                tenant_key=tenant_key,
                user_data_dir=f"{self._root}/{tenant_key}",
            )
            self._profiles[tenant_key] = profile
        profile.visit_count += 1
        return profile

    def is_returning(self, tenant_key: str) -> bool:
        profile = self._profiles.get(tenant_key)
        return profile is not None and profile.visit_count > 1


# --- FR-STEALTH-4: residential egress (config seam + guardrail) --------------
class DatacenterEgressRefused(Exception):
    """Raised when egress would route through a datacenter exit (FR-STEALTH-4)."""


#: Explicit egress modes (FR-STEALTH-4). ``direct`` => the host's own (residential)
#: connection; ``residential-proxy`` => MUST have an attested residential proxy and
#: it is threaded into the real browser launch.
EGRESS_DIRECT = "direct"
EGRESS_RESIDENTIAL_PROXY = "residential-proxy"

#: Honest, best-effort caveat: IP/ASN classification is heuristic. We refuse a
#: self-flagged datacenter exit and require an attested residential proxy when the
#: residential-proxy mode is selected, but we cannot *prove* an upstream is
#: residential — operator attestation + the mode are the guardrail (FR-STEALTH-4).
EGRESS_CAVEAT = (
    "Egress residential-classification is best-effort: the engine refuses a "
    "self-flagged datacenter exit and, in residential-proxy mode, requires an "
    "attested residential proxy that is threaded into the browser launch — but "
    "IP/ASN residential classification cannot be fully proven (FR-STEALTH-4)."
)


@dataclass(frozen=True)
class EgressPolicy:
    """The residential-egress config seam + guardrail (FR-STEALTH-4).

    Egress MUST go via the user's residential connection. There are two honest
    modes: ``direct`` (the host's own connection) and ``residential-proxy`` (an
    attested residential proxy/Tailscale exit, threaded into the real browser
    launch). A datacenter exit is forbidden — it is the single biggest legitimacy
    tell — and so is selecting ``residential-proxy`` without a valid proxy: the
    engine REFUSES to launch rather than silently egress from the datacenter.
    """

    #: ``None`` => direct residential connection (the default, honest path).
    proxy_url: str | None = None
    #: True only when the operator explicitly attests the proxy is residential.
    residential: bool = True
    #: Explicit egress mode (FR-STEALTH-4): ``direct`` | ``residential-proxy``.
    mode: str = EGRESS_DIRECT

    def validate(self) -> None:
        """Refuse a non-residential / under-configured egress (FR-STEALTH-4).

        * A configured-but-non-residential (datacenter) proxy is always refused.
        * In ``residential-proxy`` mode a valid proxy URL is REQUIRED — refuse to
          launch when it is missing/blank, rather than silently egressing direct
          from the datacenter the engine may be hosted in.
        """
        if self.proxy_url is not None and not self.residential:
            raise DatacenterEgressRefused(
                "Refusing datacenter egress: configure a residential connection "
                "(direct or residential proxy/Tailscale exit) (FR-STEALTH-4)."
            )
        if self.mode == EGRESS_RESIDENTIAL_PROXY and not (self.proxy_url or "").strip():
            raise DatacenterEgressRefused(
                "Residential-proxy egress required but no proxy is configured; "
                "refusing to launch (would egress from the datacenter) (FR-STEALTH-4)."
            )
        if self.mode == EGRESS_RESIDENTIAL_PROXY and not self.residential:
            # A residential-proxy that is NOT operator-attested residential must
            # refuse to launch: we cannot assume an arbitrary proxy is residential
            # (it may well be a datacenter exit — the biggest legitimacy tell).
            raise DatacenterEgressRefused(
                "Residential-proxy mode requires an operator-attested residential "
                "proxy (set EGRESS_RESIDENTIAL=true). Refusing to launch with an "
                "un-attested proxy that may egress from a datacenter (FR-STEALTH-4)."
            )

    @property
    def is_direct_residential(self) -> bool:
        return self.proxy_url is None and self.residential

    def launch_proxy(self) -> dict[str, str] | None:
        """Playwright ``proxy=`` kwarg for the browser launch, or ``None`` (direct).

        Threaded into ``launch_persistent_context(proxy=...)`` so a configured
        residential proxy is ACTUALLY used for automation egress (FR-STEALTH-4),
        not merely validated. ``None`` => no proxy (direct residential egress).
        """
        if self.proxy_url and (self.proxy_url or "").strip():
            return {"server": self.proxy_url}
        return None

    @classmethod
    def from_settings(
        cls, *, mode: str, proxy_url: str, residential: bool = False
    ) -> EgressPolicy:
        """Build a policy from app settings (FR-STEALTH-4).

        ``residential`` is the explicit operator attestation (EGRESS_RESIDENTIAL):
        it must be ``True`` for a ``residential-proxy`` exit to be accepted. When a
        proxy is configured but NOT attested residential, :meth:`validate` refuses to
        launch — so the datacenter-egress refusal is reachable through prod wiring.
        The ``direct`` mode (the host's own connection) is residential by definition.
        """
        mode_norm = (mode or EGRESS_DIRECT).strip() or EGRESS_DIRECT
        url = (proxy_url or "").strip() or None
        # `direct` uses the host's own (residential) connection; a proxied exit is
        # residential only when the operator explicitly attests it.
        attested = True if mode_norm == EGRESS_DIRECT else bool(residential)
        return cls(proxy_url=url, residential=attested, mode=mode_norm)
