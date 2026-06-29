"""Page-source abstraction: the swappable boundary between the in-memory fake
driver (default, hermetic) and the real patchright/Playwright driver (FR-PREFILL-1).

A :class:`PageSource` is the thin surface the :class:`PatchrightBrowser` adapter
drives: navigate, read the current page, detect fields, type a value into a field,
capture a screenshot, advance to the next page. Two implementations:

* :class:`FakePageSource` — an in-memory model walked from an
  :class:`~applicant.adapters.browser.ats.AtsAdapter` page list. NO browser. This
  is what the DEFAULT test lane uses, so the whole maximal-pre-fill loop, the
  boundary, the sensitive-field policy, and the ATS abstraction are exercised with
  nothing installed.
* :class:`PlaywrightPageSource` — the REAL driver. It imports patchright/Playwright
  lazily inside ``__init__`` so importing this module never requires a browser
  binary; the default lane never constructs it. It is integration-gated and skips
  when no browser is present.

This is the clearly-marked boundary the work package asks for: swapping
``FakePageSource`` for ``PlaywrightPageSource`` is the only change to go live.
"""

from __future__ import annotations

import logging
import re
import socket
import time
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from applicant.adapters.browser.ats import AtsAdapter, FakePage, resolve_ats
from applicant.core.errors import InvalidInput
from applicant.core.rules.url_safety import ip_chain_is_blocked, scheme_is_allowed
from applicant.ports.driven.browser_automation import DetectedField, PageState

log = logging.getLogger(__name__)


def url_safety_violation(url: str) -> str | None:
    """Return a reason string if ``url`` targets a non-public host (SSRF), else None.

    Shared core of the SSRF guard: require an http(s) scheme and resolve the host —
    if it (or ANY address it resolves to) is a loopback/link-local/private/reserved/
    metadata address the URL is unsafe. Resolving the host (not just inspecting the
    literal) closes the DNS-rebinding hole where a public name points at an internal
    IP. ``getaddrinfo`` of a numeric literal or ``localhost`` needs no network, so the
    logic stays testable. Returns ``None`` only for a safe, public http(s) URL.

    Used both at the navigation entry (``assert_navigable_url``, which raises) and at
    the per-request route guard (``PlaywrightPageSource``, which aborts the request) so
    redirects and subresources are re-validated, not just the entry URL.
    """
    raw = (url or "").strip()
    parts = urlsplit(raw)
    if not scheme_is_allowed(parts.scheme):
        return f"non-http(s) URL (scheme {parts.scheme!r})"
    host = (parts.hostname or "").strip()
    if not host:
        return "URL with no host"
    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return f"{host!r}: DNS resolution failed"
    addrs = [info[4][0] for info in infos]
    # Refuse if ANY resolved address is non-public (a host can resolve to several).
    if ip_chain_is_blocked(addrs):
        return f"{host!r}: resolves to a non-public address ({', '.join(addrs)})"
    return None


def assert_navigable_url(url: str) -> None:
    """Refuse to navigate an UNTRUSTED URL that targets a non-public host (SSRF).

    The pre-fill loop opens a scraped job-posting ``source_url`` in the real
    browser; that value is attacker-influenced. Before the browser touches it we
    require an http(s) scheme and resolve the host — if it (or ANY address it
    resolves to) is a loopback/link-local/private/reserved/metadata address we
    raise instead of letting the browser reach the cloud-metadata endpoint, the
    internal ``api`` service, or a LAN host. Public destinations pass through.
    """
    reason = url_safety_violation(url)
    if reason is not None:
        raise InvalidInput(f"refusing to navigate {reason} (SSRF guard).")

#: Characters allowed in a screenshot filename slug; everything else is replaced.
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slugify(value: str) -> str:
    """Make a string safe for a filename: replace ``/ ? : ...`` with ``-``."""
    return _SLUG_RE.sub("-", value).strip("-")

#: Confirmation-page heuristics (FR-LOG-4): markers a post-submission page shows.
_CONFIRMATION_URL_MARKERS = ("confirmation", "thank-you", "thankyou", "submitted", "success")
_CONFIRMATION_TEXT_MARKERS = (
    "application submitted",
    "thank you for applying",
    "we have received your application",
    "your application has been received",
    "submission successful",
)


def detect_confirmation(url: str = "", text: str = "") -> bool:
    """Heuristic: does this page look like a post-submission confirmation? (FR-LOG-4).

    Combines URL markers (``/confirmation``, ``/thank-you``, ...) with on-page text
    markers ("Application submitted", "Thank you for applying", ...). Conservative:
    only fires on a clear confirmation signal so a false positive never marks a
    submission that did not happen.
    """
    low_url = url.lower()
    low_text = text.lower()
    if any(m in low_url for m in _CONFIRMATION_URL_MARKERS):
        return True
    return any(m in low_text for m in _CONFIRMATION_TEXT_MARKERS)


@runtime_checkable
class PageSource(Protocol):
    """The swappable page-driver surface (fake <-> real browser)."""

    def open(self, url: str) -> None:
        """Navigate to ``url`` (the first page of the flow)."""
        ...

    def current(self) -> PageState:
        """Snapshot the current page (url, fields, detection signals)."""
        ...

    def detect_fields(self) -> list[DetectedField]:
        """Detect all fillable fields on the current page (FR-PREFILL-2/3)."""
        ...

    def type_value(
        self, selector: str, value: str, *, cadence_ms: list[float] | None = None
    ) -> None:
        """Type ``value`` into ``selector`` on the current page (human-like).

        ``cadence_ms`` is an optional per-character dwell plan (FR-STEALTH-2); when
        provided the real driver uses it instead of a constant keystroke delay.
        """
        ...

    def set_input_files(self, selector: str, file_path: str) -> None:
        """Attach ``file_path`` to a file ``<input type=file>`` (FR-RESUME-4).

        A deterministic, idempotent pre-fill step — uploading the rendered base
        résumé, not a submit — so it never crosses the pre-fill-stop boundary.
        """
        ...

    def screenshot(self) -> str:
        """Capture a per-page screenshot; return its ref (FR-LOG-2)."""
        ...

    def advance(self) -> PageState | None:
        """Move to the next page; ``None`` once past the last page."""
        ...

    def enter_application(self) -> PageState | None:
        """Click the ATS "Apply" entry into the application flow (FR-PREFILL-1).

        Returns the new page, or ``None`` when not needed (already in-flow)."""
        ...

    def log_in(self, username: str, password: str) -> bool:
        """Attempt an email/password sign-in at the account gate; return success."""
        ...

    def offers_google_signin(self) -> bool:
        """True when the account gate offers OAuth 'Sign in with Google'."""
        ...

    def log_in_with_google(self, username: str, password: str) -> str:
        """Drive 'Sign in with Google'; return 'ok' | 'two_factor' | 'failed'."""
        ...

    def create_account(self, username: str, password: str) -> str:
        """Create an account from a predefined credential; return
        'ok' | 'email_verify' | 'failed' (gated by the adapter)."""
        ...

    def is_account_create_page(self) -> bool:
        ...

    def is_account_gate(self) -> bool:
        """True at the account step (sign-in OR create-account) — hand off / log in."""
        ...

    def is_final_submit_page(self) -> bool:
        ...

    def is_confirmation_page(self) -> bool:
        """True if the current page is a post-submission confirmation (FR-LOG-4)."""
        ...

    def execute(self, plan: "Plan") -> list[dict]:
        """Execute a Plan-as-Data typed-DSL plan against the current page.

        Returns a list of per-op results ``[{"op": ..., "ok": bool, "detail": ...}]``.
        The default implementation for in-memory fakes delegates to the existing
        ``type_value`` / ``set_input_files`` / ``click`` methods.
        """
        ...


# --- in-memory fake driver (DEFAULT, hermetic) -------------------------------
class FakePageSource:
    """In-memory :class:`PageSource` walking an ATS adapter's page list (no browser)."""

    def __init__(self, ats: AtsAdapter | None = None) -> None:
        self._ats = ats
        self._pages: list[FakePage] = []
        self._index = 0
        self._screenshot_seq = 0

    def open(self, url: str) -> None:
        self._ats = self._ats or resolve_ats(url)
        self._pages = self._ats.pages(url)
        self._index = 0
        self._screenshot_seq = 0

    @property
    def _page(self) -> FakePage:
        if not self._pages:
            raise KeyError("no open page; call open() first")
        return self._pages[self._index]

    def current(self) -> PageState:
        page = self._page
        return PageState(
            url=page.url,
            fields=page.fields,
            screenshot_ref=None,
            detection_signals=page.detection_signals,
            status=page.status,
            body=page.body,
            expected_host=page.expected_host,
        )

    def detect_fields(self) -> list[DetectedField]:
        return list(self._page.fields)

    def type_value(
        self, selector: str, value: str, *, cadence_ms: list[float] | None = None
    ) -> None:
        # The fake model records the value; cadence is accepted for protocol parity
        # (the real driver applies it) and ignored here.
        self._page.filled[selector] = value

    def set_input_files(self, selector: str, file_path: str) -> None:
        # The fake model records the uploaded path (the real driver attaches it via
        # Playwright's set_input_files); kept separate from typed ``filled`` values.
        self._page.uploaded[selector] = file_path

    def screenshot(self) -> str:
        self._screenshot_seq += 1
        return f"screenshot://fake/{self._index}/{self._screenshot_seq}"

    def advance(self) -> PageState | None:
        if self._index + 1 >= len(self._pages):
            return None
        self._index += 1
        return self.current()

    def enter_application(self) -> PageState | None:
        # The fake model's pages() already starts at the application's first page
        # (account-create), so there is no separate posting/landing page to click
        # through — a no-op that keeps the flow on the current page.
        return None

    def log_in(self, username: str, password: str) -> bool:
        # Simulate a successful sign-in: advance past the account gate. (The fake
        # assumes the supplied credential is valid; failure paths are exercised with
        # dedicated stubs.)
        self.advance()
        return True

    def offers_google_signin(self) -> bool:
        # The fake models an email/password account-create gate, not OAuth.
        return False

    def log_in_with_google(self, username: str, password: str) -> str:
        return "failed"

    def submit_account(self) -> None:
        # Simulate the create-account submit by advancing past the gate.
        self.advance()

    def create_account(self, username: str, password: str) -> str:
        # Simulate a successful account creation: advance past the gate.
        self.advance()
        return "ok"

    def is_account_create_page(self) -> bool:
        return self._page.is_account_create

    def is_account_gate(self) -> bool:
        # Align with PlaywrightPageSource.is_account_gate (issue #213): the gate is
        # broader than account-create — a sign-in-only page (email/password fields,
        # no create-account option) is a gate too. When the page is not flagged as
        # account-create, fall back to URL-path and detection-signal login markers.
        if self._page.is_account_create:
            return True
        url = (self._page.url or "").lower()
        if any(m in url for m in ("/signin", "/login", "/sign-in", "/log-in")):
            return True
        signals = " ".join(self._page.detection_signals or ()).lower()
        if any(m in signals for m in ("sign in", "log in", "login")):
            return True
        return False

    def is_final_submit_page(self) -> bool:
        return self._page.is_final_submit

    def is_confirmation_page(self) -> bool:
        page = self._page
        # An explicit flag short-circuits; otherwise apply the URL/text heuristics.
        return page.is_confirmation or detect_confirmation(url=page.url, text=page.text)

    # --- test/seam helpers (used by the adapter + tests) -----------------
    def filled(self) -> dict[str, str]:
        return dict(self._page.filled)

    def uploaded(self) -> dict[str, str]:
        """Selector -> uploaded file path on the current page (FR-RESUME-4)."""
        return dict(self._page.uploaded)

    def inject_detection_signal(self, signal: str) -> None:
        from dataclasses import replace

        page = self._page
        self._pages[self._index] = replace(
            page, detection_signals=(*page.detection_signals, signal)
        )

    def inject_page_signals(
        self,
        *,
        status: int | None = None,
        body: str | None = None,
        expected_host: str | None = None,
        url: str | None = None,
    ) -> None:
        """Seam/test helper: set HTTP status / body / expected_host on the page.

        Models what the live driver observes (a 403/429 response, raw markup with a
        Cloudflare/CAPTCHA marker, or a redirect to an unexpected host) so cautious
        mode can be exercised against every classify_signals input (FR-PREFILL-6).
        """
        from dataclasses import replace

        page = self._page
        changes: dict = {}
        if status is not None:
            changes["status"] = status
        if body is not None:
            changes["body"] = body
        if expected_host is not None:
            changes["expected_host"] = expected_host
        if url is not None:
            changes["url"] = url
        self._pages[self._index] = replace(page, **changes)

    def execute(self, plan: "Plan") -> list[dict]:
        """Execute a plan-as-data typed-DSL plan (fake: apply to in-memory pages)."""
        from applicant.core.entities.plan import OpKind

        results: list[dict] = []
        for op in plan:
            kind = op.kind
            try:
                if kind == OpKind.GOTO:
                    self.open(op.url)
                    results.append({"op": "goto", "ok": True, "detail": op.url})
                elif kind == OpKind.FILL:
                    self.type_value(op.ref, op.attribute_id)
                    results.append({"op": "fill", "ok": True, "detail": op.ref})
                elif kind == OpKind.SELECT:
                    self.type_value(op.ref, op.attribute_id)
                    results.append({"op": "select", "ok": True, "detail": op.ref})
                elif kind == OpKind.CLICK:
                    self.advance()
                    results.append({"op": "click", "ok": True, "detail": op.ref})
                elif kind == OpKind.UPLOAD:
                    self.set_input_files(op.ref, op.document_id)
                    results.append({"op": "upload", "ok": True, "detail": op.ref})
                elif kind == OpKind.WAIT:
                    results.append({"op": "wait", "ok": True, "detail": op.for_})
                elif kind == OpKind.STOP:
                    results.append({"op": "stop", "ok": True, "detail": op.reason})
                elif kind == OpKind.GOTO:
                    results.append({"op": "goto", "ok": True, "detail": op.url})
                else:
                    results.append({"op": kind.value, "ok": True, "detail": "stub"})
            except Exception as exc:
                results.append({"op": kind.value, "ok": False, "detail": str(exc)})
                break
        return results

    def simulate_confirmation(self, *, text: str = "Application submitted") -> None:
        """Seam/test helper: turn the current page into a confirmation page.

        Models what the live driver observes after the user (or authorized engine)
        clicks final submit and the ATS renders its confirmation page.
        """
        from dataclasses import replace

        page = self._page
        self._pages[self._index] = replace(page, is_confirmation=True, text=text)


# --- real browser driver (REAL, integration-gated) --------------------------
class PlaywrightPageSource:
    """REAL :class:`PageSource` driven over the Playwright API (FR-PREFILL-1).

    Two launch engines, selected by ``engine``, share ALL of the navigate / read /
    detect / type / screenshot logic below (Camoufox is "fully compatible with
    existing Playwright code", so only the launch differs):

    * ``camoufox`` (the default) — a Firefox-based anti-detect browser that injects
      its own coherent, real-world-distribution fingerprint (FR-STEALTH-1). Because
      Camoufox owns the fingerprint, the Chrome WebGL/platform init-script override
      is NOT applied on this path.
    * ``chromium`` — patchright (a Playwright fork that strips automation tells) +
      real Google Chrome/Chromium, presenting the coherent honest real-Chrome
      identity, with the WebGL/platform init script applied. This is also the engine
      used for the Proxmox Windows CDP backend (connect to a remote real Chrome).

    The browser driver is imported LAZILY so importing this module costs nothing and
    needs no browser binary; the default test lane never constructs this class. Only
    integration-gated smoke tests (which skip if the browser is not installed) drive
    it. The human-like input cadence (FR-STEALTH-2) is applied via the type API.

    NOTE: clicks/submits are NOT performed here — the adapter routes the boundary
    decisions; this driver only navigates + reads + types + screenshots, never
    clicking an account-create or final submit (FR-PREFILL-4/5).
    """

    #: The default driving browser channel for the ``chromium`` engine: real Google
    #: Chrome (FR-STEALTH-1). Real Chrome (not Chromium, not headless) yields the
    #: genuine Chrome TLS/JA3 + HTTP/2 fingerprint and correct Sec-CH-UA hints.
    DEFAULT_CHANNEL = "chrome"

    #: The default launch engine. ``camoufox`` is the product default (every outbound
    #: browser request routes through it); ``chromium`` is the patchright/Chrome path.
    DEFAULT_ENGINE = "chromium"

    def __init__(
        self,
        fingerprint: dict[str, str],
        *,
        headless: bool | str = False,
        proxy: dict[str, str] | None = None,
        user_data_dir: str = "",
        channel: str = DEFAULT_CHANNEL,
        cdp_endpoint: str = "",
        persona: str = "linux",
        engine: str = DEFAULT_ENGINE,
        browser_os: str = "linux",
        geoip: bool = True,
        humanize: bool = True,
    ) -> None:
        self._fingerprint = dict(fingerprint)
        self._channel = channel
        # FR-STEALTH-4: the residential-egress proxy (or None for direct egress),
        # threaded into the launch options below (both engines accept Playwright's
        # ``{"server": ...}`` proxy dict).
        self._proxy = dict(proxy) if proxy else None
        #: CDP-connect mode (FR-SANDBOX-1, FR-STEALTH-1): when an endpoint is set, the
        #: engine CONNECTS to a remote Chrome (the Windows VM) over CDP instead of
        #: launching a local browser. Persona is then ``native`` — NO fingerprint
        #: override, because it IS real Windows + real Chrome (genuine fingerprint).
        #: CDP always uses the chromium engine (Camoufox is Firefox, no Chrome CDP).
        self._cdp_endpoint = cdp_endpoint
        self._persona = persona
        self._engine = (engine or self.DEFAULT_ENGINE).strip().lower()
        # Playwright handle (chromium engine) vs Camoufox context-manager handle
        # (camoufox engine) — exactly one is set; teardown closes whichever launched.
        self._pw = None
        self._cam = None
        self._context = None
        self._page = None
        self._browser = None
        self._headless = headless
        self._user_data_dir = user_data_dir
        # Captured per-navigation main-frame HTTP status + the expected host so
        # current() can populate cautious-mode signals (FR-PREFILL-6).
        self._status: int | None = None
        self._expected_host: str | None = None
        # Camoufox engine (the default product path): a local launch only. A CDP
        # endpoint forces the chromium path (remote real Chrome over CDP).
        if self._engine == "camoufox" and not self._cdp_endpoint:
            self._launch_camoufox(
                headless=headless,
                proxy=self._proxy,
                user_data_dir=user_data_dir,
                browser_os=browser_os,
                geoip=geoip,
                humanize=humanize,
            )
            return
        self._launch_chromium(headless=headless, user_data_dir=user_data_dir)

    def _launch_chromium(self, *, headless: bool | str, user_data_dir: str) -> None:
        """Launch the patchright/Chrome engine (or connect to a remote Chrome via CDP)."""
        try:
            # patchright is a drop-in Playwright fork that removes automation tells
            # (FR-STEALTH-1); fall back to vanilla playwright if only that is present.
            try:
                from patchright.sync_api import sync_playwright  # type: ignore
            except ImportError:  # pragma: no cover - exercised only when patchright absent
                from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError as exc:  # pragma: no cover - integration-gated
            raise RuntimeError(
                "No browser driver installed. Install patchright or playwright "
                "and run `patchright install chromium` (integration-only)."
            ) from exc

        self._pw = sync_playwright().start()
        try:  # pragma: no cover - integration-gated
            if self._cdp_endpoint:
                # Connect to the REMOTE Windows VM's Chrome over CDP. The browser is
                # genuinely Windows; we do NOT apply any fingerprint override (native
                # persona) — that would only RISK incoherence with a real OS.
                self._browser = self._pw.chromium.connect_over_cdp(self._cdp_endpoint)
                contexts = self._browser.contexts
                self._context = contexts[0] if contexts else self._browser.new_context()
                pages = self._context.pages
                self._page = pages[0] if pages else self._context.new_page()
            else:
                kwargs = self.launch_kwargs(
                    self._fingerprint,
                    headless=bool(headless),
                    proxy=self._proxy,
                    user_data_dir=user_data_dir,
                    channel=self._channel,
                )
                self._context = self._pw.chromium.launch_persistent_context(**kwargs)
                # FR-STEALTH-1: apply the coherent fingerprint (WebGL vendor/renderer
                # + navigator.platform) to every page in the context via an init
                # script so the launched browser actually reports the normalized
                # identity, not the host's real GPU/platform. Skipped entirely in
                # ``native`` persona (real OS already coherent).
                if self._persona != "native":
                    self._apply_fingerprint_overrides(self._context)
                self._page = self._context.new_page()
            self._finalize_page()
        except Exception:
            self._safe_teardown()
            raise

    def _launch_camoufox(
        self,
        *,
        headless: bool | str,
        proxy: dict[str, str] | None,
        user_data_dir: str,
        browser_os: str,
        geoip: bool,
        humanize: bool,
    ) -> None:
        """Launch the Camoufox anti-detect browser as the page driver (FR-STEALTH-1).

        Camoufox is a context manager around the Playwright API; we drive it without
        the ``with`` block (entering/exiting manually) so the context/page live for
        the driver's lifetime, exactly like the chromium path. Camoufox injects its
        own coherent fingerprint, so NO Chrome init-script override is applied here.
        """
        try:
            from camoufox.sync_api import Camoufox  # type: ignore
        except ImportError as exc:  # pragma: no cover - integration-gated
            raise RuntimeError(
                "Camoufox is not installed. Install the browser extra "
                "(`uv sync --extra browser`) and run `camoufox fetch` (integration-only)."
            ) from exc

        options = self.camoufox_options(
            self._fingerprint,
            headless=headless,
            proxy=proxy,
            user_data_dir=user_data_dir,
            browser_os=browser_os,
            geoip=geoip,
            humanize=humanize,
        )
        persistent = bool(options.get("persistent_context"))
        self._cam = Camoufox(**options)
        try:  # pragma: no cover - integration-gated
            # __enter__ launches the browser; with persistent_context it returns a
            # BrowserContext directly, otherwise a Browser we open a context from.
            handle = self._cam.__enter__()
            if persistent:
                self._context = handle
            else:
                self._browser = handle
                self._context = handle.new_context()
            self._page = self._context.new_page()
            self._finalize_page()
        except Exception:
            self._safe_teardown()
            raise

    def _finalize_page(self) -> None:  # pragma: no cover - integration-gated
        """Apply the shared per-context timeouts + response capture (both engines).

        Fail fast on a stuck control: a single unfillable field must not hang the
        whole walk on Playwright's 30s default (a real Lever form otherwise took
        100s+). Navigation keeps a longer budget; per-action (fill/click/type) is
        short so the soft-error path triggers quickly (universal-ATS robustness).
        """
        try:
            self._context.set_default_timeout(8_000)
            self._context.set_default_navigation_timeout(30_000)
        except Exception:
            pass
        # SSRF guard for the WHOLE navigation, not just the entry URL: a scraped
        # posting that resolves public but 3xx-redirects to an internal/metadata host,
        # OR any subresource the page requests, would otherwise reach a non-public host
        # and have its body captured. Intercept every request (main frame + redirects +
        # subresources) and abort any whose resolved IP is non-public (#310, refs #168).
        try:
            self._context.route("**/*", self._guard_route)
        except Exception:
            pass
        self._page.on("response", self._on_response)

    def _guard_route(self, route) -> None:  # pragma: no cover - integration-gated
        """Abort a request whose target resolves to a non-public host (SSRF).

        Reuses the same scheme + DNS-resolution + ``ip_is_blocked`` logic as the
        entry-URL guard via ``url_safety_violation`` so the policy is identical on
        every hop. Continues the request only when the destination is a public
        http(s) host; aborts otherwise (Playwright treats an aborted request as a
        network failure, so the blocked body is never fetched)."""
        try:
            target = route.request.url
        except Exception:
            target = ""
        if url_safety_violation(target) is not None:
            try:
                route.abort()
            except Exception:
                pass
            return
        try:
            route.continue_()
        except Exception:
            pass

    def _on_response(self, response) -> None:  # pragma: no cover - integration-gated
        """Capture the main-frame document response status for cautious mode."""
        try:
            if response.url == self._page.url or response.request.is_navigation_request():
                self._status = response.status
        except Exception:
            pass

    def _is_crashed(self) -> bool:  # pragma: no cover - integration-gated
        """Check whether the browser page has crashed (detached or closed).

        Returns True if the page or context is no longer usable, so callers can
        trigger recovery instead of operating on a dead browser."""
        try:
            page = getattr(self, "_page", None)
            if page is None:
                return True
            # A simple no-op evaluate: if the page is detached this raises.
            page.evaluate("1 + 1")
            return False
        except Exception:  # noqa: BLE001 — any error means crashed/dead
            return True

    def health_check(self) -> bool:  # pragma: no cover - integration-gated
        """Verify the browser page is still connected and responsive.

        Returns True if the browser page is reachable and evaluates a trivial
        expression without error, False otherwise.  Never raises."""
        try:
            page = getattr(self, "_page", None)
            if page is None:
                return False
            page.evaluate("1 + 1")
            return True
        except Exception:  # noqa: BLE001 — health check never raises
            return False

    def _recover(self) -> None:  # pragma: no cover - integration-gated
        """Attempt to recover from a browser crash by tearing down and re-launching.

        Logs the recovery attempt. If re-launch fails the exception propagates."""
        log.warning("Browser crash detected — attempting recovery")
        self._safe_teardown()
        # Re-launch using stored constructor parameters.
        self._launch_chromium(
            headless=getattr(self, "_headless", False),
            user_data_dir=getattr(self, "_user_data_dir", ""),
        )


    def _crash_safe_call(self, fn, *args, **kwargs):  # pragma: no cover - integration-gated
        """Execute a page/browser operation with crash detection and recovery.

        If the operation raises :class:`TargetClosedError` or :class:`TimeoutError`
        (Playwright's signals for a detached/dead page), attempts to recover by
        re-launching the browser and retrying once.  Other exceptions propagate
        immediately."""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            if exc_name in ("TargetClosedError", "TimeoutError"):
                log.warning("Browser crash detected during operation", exc_info=exc)
                self._recover()
                return fn(*args, **kwargs)
            raise

    def _safe_teardown(self) -> None:  # pragma: no cover - integration-gated
        """Best-effort cleanup of a partially-constructed driver.

        Camoufox owns its own browser + Playwright lifecycle, so we exit its context
        manager (which closes the browser and stops Playwright). In CDP-connect mode
        the remote browser is the Windows VM's Chrome — we only DISCONNECT (close our
        local handle); the VM lifecycle is owned by the sandbox adapter (it tears the
        VM down). We never destroy a remote context we attached to that we did not
        create. ``getattr`` defaults keep this safe on a partially-built instance.
        """
        cam = getattr(self, "_cam", None)
        cdp_endpoint = getattr(self, "_cdp_endpoint", "")
        browser = getattr(self, "_browser", None)
        context = getattr(self, "_context", None)
        pw = getattr(self, "_pw", None)
        try:
            if cam is not None:
                # Camoufox.__exit__ closes the browser AND stops its Playwright.
                cam.__exit__(None, None, None)
            elif cdp_endpoint and browser is not None:
                # Disconnect from the remote Chrome without closing its context.
                browser.close()
            elif context is not None:
                context.close()
        except Exception as exc:
            log.warning("Browser teardown (context/browser) failed", exc_info=exc)
            raise
        try:
            if pw is not None:
                pw.stop()
        except Exception as exc:
            log.warning("Playwright stop failed", exc_info=exc)
            raise

    @staticmethod
    def fingerprint_init_script(fingerprint: dict[str, str]) -> str:
        """Build the JS init script applying the coherent real-Linux/Chrome identity.

        Pure + unit-testable (no browser): the default lane asserts the coherent
        WebGL vendor/renderer, ``navigator.platform`` (``Linux x86_64``),
        ``navigator.vendor`` (``Google Inc.``) and ``navigator.languages``
        (``en-US,en``) are baked into the script injected into every page
        (FR-STEALTH-1). It does NOT touch ``Sec-CH-UA`` — real Google Chrome emits
        those client hints itself; re-setting them would risk an incoherent double.
        """
        import json as _json

        vendor = fingerprint.get("webgl_vendor", "")
        renderer = fingerprint.get("webgl_renderer", "")
        platform = fingerprint.get("platform", "")
        nav_vendor = fingerprint.get("vendor", "Google Inc.")
        languages = [
            lang.strip()
            for lang in fingerprint.get("languages", "en-US,en").split(",")
            if lang.strip()
        ]
        return (
            "(() => {"
            f"  const vendor = {_json.dumps(vendor)};"
            f"  const renderer = {_json.dumps(renderer)};"
            f"  const platform = {_json.dumps(platform)};"
            f"  const navVendor = {_json.dumps(nav_vendor)};"
            f"  const languages = {_json.dumps(languages)};"
            "  try {"
            "    Object.defineProperty(navigator, 'platform', {get: () => platform});"
            "  } catch (e) {}"
            "  try {"
            "    Object.defineProperty(navigator, 'vendor', {get: () => navVendor});"
            "  } catch (e) {}"
            "  try {"
            "    Object.defineProperty(navigator, 'languages', {get: () => languages});"
            "  } catch (e) {}"
            "  const patch = (proto) => {"
            "    if (!proto || !proto.getParameter) return;"
            "    const orig = proto.getParameter;"
            "    proto.getParameter = function(p) {"
            "      if (p === 37445) return vendor;"   # UNMASKED_VENDOR_WEBGL
            "      if (p === 37446) return renderer;"  # UNMASKED_RENDERER_WEBGL
            "      return orig.call(this, p);"
            "    };"
            "  };"
            "  if (window.WebGLRenderingContext) patch(WebGLRenderingContext.prototype);"
            "  if (window.WebGL2RenderingContext) patch(WebGL2RenderingContext.prototype);"
            "})();"
        )

    def _apply_fingerprint_overrides(self, context) -> None:  # pragma: no cover
        """Inject the fingerprint init script into every page in the context."""
        context.add_init_script(self.fingerprint_init_script(self._fingerprint))

    #: Browser launch args that REMOVE automation/headless tells without revealing
    #: automation (FR-STEALTH-1). ``--disable-blink-features=AutomationControlled``
    #: drops the ``navigator.webdriver`` tell; we add NO automation-revealing flags
    #: (no ``--headless``, no ``--enable-automation``). Patchright layers its own
    #: stealth patches on top of these.
    #:
    #: ``--enable-unsafe-swiftshader`` keeps a working WebGL context on GPU-less hosts
    #: (the default deploy launches the browser inside the api container, which has no
    #: GPU). Recent Chrome/Chromium dropped the automatic SwiftShader fallback, so
    #: without this flag ``canvas.getContext('webgl')`` returns ``null`` — and a real
    #: Chrome-on-Linux ALWAYS exposes WebGL, so a missing context is itself an
    #: incoherence (FR-STEALTH-1). With a context present, the fingerprint init script
    #: above masks the SwiftShader vendor/renderer to the coherent values. On a host
    #: that does have a usable GPU the flag is a no-op (SwiftShader stays a fallback).
    _STEALTH_ARGS = (
        "--disable-blink-features=AutomationControlled",
        "--enable-unsafe-swiftshader",
    )

    @staticmethod
    def launch_kwargs(
        fingerprint: dict[str, str],
        *,
        headless: bool = False,
        proxy: dict[str, str] | None = None,
        user_data_dir: str = "",
        channel: str = DEFAULT_CHANNEL,
    ) -> dict:
        """Build the ``launch_persistent_context`` kwargs (pure + unit-testable).

        Kept pure (no browser) so the default lane can assert the coherent
        real-Linux/Chrome fingerprint (FR-STEALTH-1), the driving CHANNEL (real
        Google Chrome, headful), the tz/locale tied to egress, AND the residential
        proxy (FR-STEALTH-4) are all threaded into the real launch, without
        constructing a browser.
        """
        width, _, height = fingerprint.get("resolution", "1920x1080").partition("x")
        scale = fingerprint.get("device_scale_factor", "1")
        try:
            scale_f = float(scale)
        except (TypeError, ValueError):
            scale_f = 1.0
        kwargs: dict = {
            "user_data_dir": user_data_dir,  # the adapter supplies a per-tenant dir
            # Real Google Chrome (channel), HEADFUL (no --headless): the genuine
            # Chrome TLS/JA3 + client hints come for free (FR-STEALTH-1).
            "channel": channel,
            "headless": headless,
            "user_agent": fingerprint.get("user_agent"),
            "locale": fingerprint.get("locale", "en-US"),
            # FR-STEALTH-1 <-> FR-STEALTH-4: tz/locale pinned to the residential
            # egress geolocation so tz/locale <-> IP are consistent.
            "timezone_id": fingerprint.get("timezone", "America/Phoenix"),
            "viewport": {"width": int(width or 1920), "height": int(height or 1080)},
            "device_scale_factor": scale_f,
            "args": list(PlaywrightPageSource._STEALTH_ARGS),
        }
        if proxy:
            # FR-STEALTH-4: residential proxy actually used for automation egress.
            kwargs["proxy"] = dict(proxy)
        return kwargs

    @staticmethod
    def camoufox_options(
        fingerprint: dict[str, str],
        *,
        headless: bool | str = False,
        proxy: dict[str, str] | None = None,
        user_data_dir: str = "",
        browser_os: str = "linux",
        geoip: bool = True,
        humanize: bool = True,
    ) -> dict:
        """Build the ``Camoufox(...)`` launch options (pure + unit-testable).

        Kept pure (no browser) so the default lane can assert the residential proxy
        (FR-STEALTH-4), the persistent per-tenant profile (FR-STEALTH-3), the spoofed
        OS, IP-coherent geolocation and human-like cursor are all threaded into the
        real launch without constructing a browser. Camoufox generates its OWN
        coherent fingerprint (BrowserForge), so — unlike the chromium path — no
        Chrome user-agent / WebGL / Sec-CH-UA values are injected here.
        """
        # A headful request becomes a real, RENDERED browser on a virtual X server
        # inside the display-less container — that is headful (no headless detection
        # tell), just on Xvfb. An explicit ``True``/``"virtual"`` is honored as given.
        resolved_headless: bool | str = "virtual" if headless is False else headless
        persistent = bool((user_data_dir or "").strip())
        options: dict = {
            # Spoof a coherent OS fingerprint (default Linux, matching the deploy).
            "os": browser_os or "linux",
            "headless": resolved_headless,
            # FR-STEALTH-2: human-like cursor movement (the typing cadence is applied
            # separately via the HumanInteraction plan fed to the type API).
            "humanize": bool(humanize),
            # FR-STEALTH-1 <-> FR-STEALTH-4: derive geolocation/timezone/locale from
            # the EXIT IP (the residential proxy, or the host's own IP for direct
            # egress) so the fingerprint never contradicts where the traffic exits.
            "geoip": bool(geoip),
            "locale": fingerprint.get("locale", "en-US"),
            # FR-STEALTH-3: a persistent per-tenant profile (same identity on return).
            "persistent_context": persistent,
        }
        if persistent:
            options["user_data_dir"] = user_data_dir
        if proxy:
            # FR-STEALTH-4: residential proxy actually used for automation egress.
            options["proxy"] = dict(proxy)
        return options

    #: Next/Continue control candidates tried in order when advancing (FR-PREFILL-1).
    _NEXT_SELECTORS = (
        "button[data-automation-id='bottom-navigation-next-button']",  # Workday
        "button[data-automation-id='pageFooterNextButton']",
        "button:has-text('Next')",
        "button:has-text('Continue')",
        "button:has-text('Save and Continue')",
        "a:has-text('Next')",
        "[role='button']:has-text('Continue')",
    )

    #: "Apply" entry controls on a job posting / landing page (Workday first), tried
    #: in order to move from the posting INTO the application flow (FR-PREFILL-1). A
    #: Workday posting renders an "Apply" button (``adventureButton``); the form lives
    #: behind it, so without this click the engine only ever sees the posting page.
    _APPLY_SELECTORS = (
        "a[data-automation-id='adventureButton']",
        "button[data-automation-id='adventureButton']",
        "button:has-text('Apply')",
        "a:has-text('Apply')",
        "[role='button']:has-text('Apply')",
    )
    #: After the first Apply click, prefer a MANUAL application over résumé-autofill or
    #: a third-party (LinkedIn/Indeed) sign-in entry, so the engine drives the real form.
    _APPLY_MANUALLY_SELECTORS = (
        "a[data-automation-id='applyManually']",
        "button[data-automation-id='applyManually']",
        "button:has-text('Apply Manually')",
        "a:has-text('Apply Manually')",
        "[role='button']:has-text('Apply Manually')",
    )

    def _settle(self, timeout_ms: int = 12_000) -> None:  # pragma: no cover - integration-gated
        """Wait for an SPA to finish hydrating before the page is inspected.

        Workday (and most modern ATSes) render an empty shell on the ``load`` event
        and hydrate the real DOM afterward, so a field-scan / screenshot taken at
        ``load`` is blank. Wait for network to go idle — bounded + best-effort
        (never raises; a slow page just proceeds with whatever has rendered)."""
        try:
            self._page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            log.warning("_settle(): wait_for_load_state timed out after %d ms", timeout_ms, exc_info=True)

    def _click_first(self, selectors) -> bool:  # pragma: no cover - integration-gated
        """Click the first present + enabled selector; return whether one was clicked."""
        for sel in selectors:
            try:
                loc = self._page.locator(sel).first
                if loc.count() == 0 or not loc.is_enabled():
                    continue
                loc.click()
                return True
            except Exception:
                continue
        return False

    def open(self, url: str) -> None:  # pragma: no cover - integration-gated
        # SSRF guard: ``url`` is an attacker-influenced scraped posting. Refuse to
        # navigate it before the browser issues a request if it targets a non-public
        # host (cloud metadata / internal ``api`` / LAN), per assert_navigable_url.
        assert_navigable_url(url)
        # Remember the host we expected so an anomalous redirect is detectable.
        self._expected_host = url.split("//", 1)[-1].split("/", 1)[0] or None
        response = self._page.goto(url)
        if response is not None:
            self._status = response.status
        # FR-PREFILL-1: let the SPA hydrate so the field-scan / screenshot / page
        # predicates see the real DOM, not the empty shell rendered at ``load``.
        self._settle()

    def enter_application(self) -> PageState | None:  # pragma: no cover - integration-gated
        """Click the ATS "Apply" entry to move from the posting/landing page into the
        application flow (sign-in / create-account / form).

        Best-effort and idempotent: returns the new :class:`PageState` when an entry
        was clicked, else ``None`` (the URL already lands inside the flow, or there is
        no entry control). A benign navigation — never an irreducible human step."""
        if not self._click_first(self._APPLY_SELECTORS):
            return None
        self._settle()
        # Workday usually offers "Apply Manually" alongside résumé-autofill / 3rd-party
        # sign-in; take the manual path so the engine drives the real fields.
        if self._click_first(self._APPLY_MANUALLY_SELECTORS):
            self._settle()
        return self.current()

    #: Controls that reveal the email/password sign-in form (Workday shows OAuth +
    #: "Sign in with email" first; click that to get the credential form).
    _SIGN_IN_WITH_EMAIL_SELECTORS = (
        "button:has-text('Sign in with email')",
        "a:has-text('Sign in with email')",
        "button:has-text('Sign in with Email')",
        "[data-automation-id='signInWithEmail']",
    )
    #: Submit controls for the email/password sign-in form.
    _LOGIN_SUBMIT_SELECTORS = (
        "button[data-automation-id='signInSubmitButton']",
        "button[data-automation-id='click_filter']",
        "button:has-text('Sign In')",
        "button:has-text('Log In')",
        "button[type='submit']",
    )

    def log_in(self, username: str, password: str) -> bool:  # pragma: no cover - integration-gated
        """Attempt an email/password sign-in at the account gate (automate-by-default).

        Reveals the email form (Workday shows "Sign in with email" before the inputs),
        fills the email + password from the stored credential, submits, and settles.
        Returns True when we appear to be PAST the gate (login likely succeeded), else
        False — the caller then holds the sandbox + hands off. Never raises.

        Does NOT drive OAuth ("Sign in with Google") — that path is handled separately
        via a persistent session + the 2FA hand-off (see the plan)."""
        # Reveal the email/password form if it is behind a "Sign in with email" button.
        self._click_first(self._SIGN_IN_WITH_EMAIL_SELECTORS)
        self._settle()
        if not self._fill_login_fields(username, password):
            return False
        self._click_first(self._LOGIN_SUBMIT_SELECTORS)
        self._settle()
        # Success heuristic: the account gate is no longer the current page.
        try:
            return not self.is_account_gate()
        except Exception:
            return False

    def _fill_login_fields(self, username: str, password: str) -> bool:  # pragma: no cover
        """Fill the email/identifier + password inputs on a login form; return whether
        both were found and filled."""
        email_sel = pwd_sel = None
        for fld in self.detect_fields():
            ftype = (fld.field_type or "").lower()
            label = (fld.label or "").lower()
            if pwd_sel is None and ftype == "password":
                pwd_sel = fld.selector
            elif email_sel is None and (
                "email" in label or "user" in label or ftype in ("text", "email")
            ):
                email_sel = fld.selector
        if not email_sel or not pwd_sel:
            return False
        self.type_value(email_sel, username)
        self.type_value(pwd_sel, password)
        return True

    #: "Sign in with Google" entry controls (OAuth).
    _GOOGLE_SIGNIN_SELECTORS = (
        "button:has-text('Sign in with Google')",
        "a:has-text('Sign in with Google')",
        "[data-automation-id='googleSignInButton']",
        "[aria-label*='Google' i]",
    )
    #: Markers that a Google login is now demanding a second factor (the engine cannot
    #: produce it → 2FA hand-off). Broad on purpose: Google phrases this many ways.
    _TWO_FACTOR_MARKERS = (
        "2-step verification",
        "2-step",
        "two-factor",
        "two factor",
        "verify it's you",
        "verify it’s you",
        "tap yes",
        "check your phone",
        "approve this sign-in",
        "enter the code",
        "authenticator",
        "passkey",
    )

    def offers_google_signin(self) -> bool:  # pragma: no cover - integration-gated
        """True when the account gate offers an OAuth "Sign in with Google" entry."""
        for sel in self._GOOGLE_SIGNIN_SELECTORS:
            try:
                if self._page.locator(sel).first.count() > 0:
                    return True
            except Exception:
                continue
        return False

    def log_in_with_google(self, username: str, password: str) -> str:  # pragma: no cover
        """Drive an OAuth "Sign in with Google" sign-in. Returns a status:

        * ``"ok"``       — authenticated (a live persistent Google session carried us
                           through, or the email/password were accepted) and we are past
                           the gate;
        * ``"two_factor"`` — Google is demanding a second factor the engine cannot
                           produce → the caller runs the 2FA notify/continue/retry flow;
        * ``"failed"``   — could not complete (caller hands off).

        Best-effort against Google's live DOM/popups; never raises. Live tuning is
        expected (Google cannot be exercised from CI)."""
        if not self._click_first(self._GOOGLE_SIGNIN_SELECTORS):
            return "failed"
        self._settle()
        # A live persistent Google session clicks straight through OAuth consent.
        try:
            if not self.is_account_gate():
                return "ok"
        except Exception:
            pass
        # Otherwise Google asks for the account: type the stored email then password
        # across Google's two-step identifier/password screens.
        for value in (username, password):
            self._fill_first_text(value)
            self._click_first(("button:has-text('Next')", "#identifierNext", "#passwordNext", "button[type='submit']"))
            self._settle()
        if self._has_two_factor_challenge():
            return "two_factor"
        try:
            return "ok" if not self.is_account_gate() else "failed"
        except Exception:
            return "failed"

    def _fill_first_text(self, value: str) -> bool:  # pragma: no cover - integration-gated
        """Type ``value`` into the first visible text/email/password input."""
        for fld in self.detect_fields():
            if (fld.field_type or "").lower() in ("text", "email", "password", "tel"):
                self.type_value(fld.selector, value)
                return True
        return False

    def _has_two_factor_challenge(self) -> bool:  # pragma: no cover - integration-gated
        text = self._heading_and_buttons().lower()
        try:
            text += " " + (self._page.inner_text("body") or "").lower()
        except Exception:
            pass
        return any(m in text for m in self._TWO_FACTOR_MARKERS)

    #: Controls that reveal / submit the create-account form.
    _CREATE_ACCOUNT_REVEAL_SELECTORS = (
        "button:has-text('Create Account')",
        "a:has-text('Create Account')",
        "[data-automation-id='createAccountLink']",
    )
    _CREATE_SUBMIT_SELECTORS = (
        "button[data-automation-id='createAccountSubmitButton']",
        "button[data-automation-id='click_filter']",
        "button:has-text('Create Account')",
        "button[type='submit']",
    )
    _EMAIL_VERIFY_MARKERS = (
        "verify your email",
        "check your email",
        "verification email",
        "confirm your email",
        "we sent you an email",
    )

    def submit_account(self) -> None:  # pragma: no cover - integration-gated
        """Click the account-creating submit (the boundary check is in the adapter)."""
        self._click_first(self._CREATE_SUBMIT_SELECTORS)

    def create_account(self, username: str, password: str) -> str:  # pragma: no cover
        """Fill + submit a create-account form from a predefined credential, then report
        'ok' | 'email_verify' | 'failed'. Best-effort against the live DOM."""
        self._click_first(self._CREATE_ACCOUNT_REVEAL_SELECTORS)
        self._settle()
        if not self._fill_login_fields(username, password):
            return "failed"
        # Many create-account forms also have a verify/confirm-password field.
        for fld in self.detect_fields():
            label = (fld.label or "").lower()
            if "verify" in label or "confirm" in label:
                self.type_value(fld.selector, password)
        self.submit_account()
        self._settle()
        if self._needs_email_verify():
            return "email_verify"
        try:
            return "ok" if not self.is_account_gate() else "failed"
        except Exception:
            return "failed"

    def _needs_email_verify(self) -> bool:  # pragma: no cover - integration-gated
        text = self._heading_and_buttons().lower()
        try:
            text += " " + (self._page.inner_text("body") or "").lower()
        except Exception:
            pass
        return any(m in text for m in self._EMAIL_VERIFY_MARKERS)

    def current(self) -> PageState:  # pragma: no cover - integration-gated
        # Populate status/body/detection markers so cautious mode (FR-PREFILL-6) is
        # NOT blind: classify_signals needs the HTTP status, the raw body (for
        # Cloudflare/CAPTCHA markers), and the expected host for redirect detection.
        body = ""
        try:
            body = self._page.content()
        except Exception:
            body = ""
        status = self._last_status()
        detection = self._detection_signals(body)
        return PageState(
            url=self._page.url,
            fields=tuple(self.detect_fields()),
            status=status,
            body=body,
            detection_signals=detection,
            expected_host=self._expected_host,
        )

    def _last_status(self) -> int | None:  # pragma: no cover - integration-gated
        """The HTTP status of the last main-frame response, if captured."""
        return getattr(self, "_status", None)

    #: Selectors for ACTIVE (rendered) challenge widgets. An embedded-but-invisible
    #: reCAPTCHA script is NOT one of these — only a visible challenge counts, so the
    #: engine doesn't hand off on the many login/account pages that merely include the
    #: script (FR-PREFILL-6 / automate-by-default).
    _VISIBLE_CHALLENGE_SELECTORS: tuple[tuple[str, str], ...] = (
        ("recaptcha", "iframe[src*='recaptcha'][src*='bframe']"),  # the challenge popup, not the invisible badge
        ("recaptcha", "iframe[title*='recaptcha challenge']"),
        ("hcaptcha", "iframe[src*='hcaptcha'][src*='challenge']"),
        ("turnstile", ".cf-turnstile, iframe[src*='challenges.cloudflare.com']"),
        ("captcha", "[id*='px-captcha'], [class*='px-captcha']"),  # PerimeterX press & hold
    )

    #: Full-page interstitial / challenge TEXT that only appears when a block page is
    #: actually shown (so matching it in the body is safe, unlike a widget script).
    _INTERSTITIAL_BODY_MARKERS: tuple[str, ...] = (
        "checking your browser",
        "attention required",
        "needs to review the security of your connection",
        "verify you are human",
        "are you a robot",
        "complete the captcha",
        "complete the security check",
        "press & hold",
    )

    def _detection_signals(self, body: str) -> tuple[str, ...]:  # pragma: no cover
        """Extract challenge markers, distinguishing an ACTIVE challenge from a page
        that merely embeds a (usually invisible) bot-detection script.

        Widget markers (recaptcha/hcaptcha/turnstile/captcha) are emitted ONLY when a
        challenge element is actually rendered + visible; the bare script token in the
        markup is ignored. Genuine full-page interstitial phrases still match on text.
        """
        signals: list[str] = []
        for marker, selector in self._VISIBLE_CHALLENGE_SELECTORS:
            try:
                el = self._page.query_selector(selector)
                if el is not None and el.is_visible():
                    signals.append(marker)
            except Exception:
                continue
        low = (body or "").lower()
        for marker in self._INTERSTITIAL_BODY_MARKERS:
            if marker in low:
                signals.append(marker)
        # De-dup while preserving order.
        return tuple(dict.fromkeys(signals))

    def detect_fields(self) -> list[DetectedField]:  # pragma: no cover
        fields: list[DetectedField] = []
        for handle in self._page.query_selector_all("input, select, textarea"):
            # A typeable ARIA combobox (react-select) is an <input> too — skip it here
            # so it is handled once by the dropdown path below (type-to-filter + pick),
            # not typed into as a plain text field (which leaves a filter string, no
            # selection). Avoids double-detecting the same field.
            if self._is_combobox(handle):
                continue
            # The logical key (name/id) for bookkeeping AND a REAL selector usable by
            # Playwright fill/type. A raw ``name``/``id`` attribute value is NOT a
            # selector — fields never resolved. Build ``[name="..."]`` / ``#id``.
            name = handle.get_attribute("name") or ""
            elem_id = handle.get_attribute("id") or ""
            selector = self._build_selector(name, elem_id, handle)
            label = self._best_label(handle) or name or elem_id
            ftype = handle.get_attribute("type") or handle.evaluate("e => e.tagName.toLowerCase()")
            if selector:
                fields.append(
                    DetectedField(
                        selector=selector,
                        label=label,
                        field_type=ftype,
                        required=self._field_required(handle),
                    )
                )
        # Workday-style custom dropdowns are <button aria-haspopup="listbox"> (or an
        # ARIA combobox) — NOT <select>, so the query above misses them entirely.
        # Real Workday uses these for Country, Phone Device Type, and every EEO field;
        # without this the engine silently skips them (FR-PREFILL-2/3).
        for handle in self._page.query_selector_all(
            "button[aria-haspopup='listbox'], [role='combobox']"
        ):
            name = handle.get_attribute("name") or ""
            elem_id = handle.get_attribute("id") or ""
            selector = self._build_selector(name, elem_id, handle)
            label = (
                self._best_label(handle)
                or handle.get_attribute("data-automation-id")
                or name
                or elem_id
            )
            if selector:
                fields.append(
                    DetectedField(
                        selector=selector,
                        label=label,
                        field_type="listbox",
                        required=self._field_required(handle),
                    )
                )
        return fields

    @staticmethod
    def _best_label(handle) -> str:  # pragma: no cover - integration-gated
        """Resolve a field's human label the way a person reads the form.

        Order: ``aria-label`` → ``aria-labelledby`` target → the associated
        ``<label>`` (``el.labels`` / wrapping label) → ``placeholder`` → ``title``.
        Most real ATS forms (Greenhouse, Lever, iCIMS) label fields with a separate
        ``<label for=…>`` element, NOT ``aria-label`` — without this the engine only
        saw the opaque field id and could not map the field (universal-ATS support)."""
        try:
            text = handle.evaluate(
                """el => {
                  const t = s => (s || '').replace(/\\s+/g, ' ').trim();
                  if (el.getAttribute('aria-label')) return t(el.getAttribute('aria-label'));
                  const lb = el.getAttribute('aria-labelledby');
                  if (lb) { const e = document.getElementById(lb); if (e) return t(e.innerText); }
                  if (el.labels && el.labels.length) return t(el.labels[0].innerText);
                  const wrap = el.closest('label'); if (wrap) return t(wrap.innerText);
                  if (el.getAttribute('placeholder')) return t(el.getAttribute('placeholder'));
                  if (el.getAttribute('title')) return t(el.getAttribute('title'));
                  return '';
                }"""
            )
            return (text or "").strip()
        except Exception:
            try:
                return (handle.get_attribute("aria-label") or "").strip()
            except Exception:
                return ""

    @staticmethod
    def _field_required(handle) -> bool:  # pragma: no cover - integration-gated
        """Whether the DOM marks a field required (``required`` / ``aria-required``)."""
        try:
            if handle.get_attribute("required") is not None:
                return True
            return (handle.get_attribute("aria-required") or "").lower() == "true"
        except Exception:
            return False

    @staticmethod
    def _build_selector(name: str, elem_id: str, handle=None) -> str:  # pragma: no cover
        """Build a usable Playwright selector from a field's attributes.

        Prefers ``[name="..."]`` (stable across re-render), then ``#id``, then a
        Workday ``[data-automation-id="..."]`` if present. Returns ``""`` when no
        usable selector can be formed (the field is skipped).
        """
        if name:
            return f'[name="{name}"]'
        if elem_id:
            # CSS id selector; fall back to attribute form for ids with odd chars.
            if re.match(r"^[A-Za-z_][\w\-]*$", elem_id):
                return f"#{elem_id}"
            return f'[id="{elem_id}"]'
        if handle is not None:
            auto = handle.get_attribute("data-automation-id")
            if auto:
                return f'[data-automation-id="{auto}"]'
        return ""

    def type_value(
        self, selector: str, value: str, *, cadence_ms: list[float] | None = None
    ) -> None:  # pragma: no cover
        # A <select> dropdown cannot be typed into — it must be chosen via
        # select_option (real forms use selects for EEO, work-authorization,
        # country/state, yes/no, etc.). Without this branch every dropdown failed to
        # fill (FR-PREFILL-2/3). Detect the element kind and route accordingly.
        if self._is_select(selector):
            self._select_option(selector, value)
            return
        # A Workday custom dropdown (button[aria-haspopup=listbox] / role=combobox) is
        # operated by clicking it open and choosing the matching option — typing into
        # it does nothing.
        if self._is_listbox_button(selector):
            self._choose_listbox_option(selector, value)
            return
        # Apply the per-keystroke cadence (FR-STEALTH-2): the adapter computes a
        # dwell-per-character plan; feed it to Playwright press-by-press instead of
        # the old constant 80ms delay. Fall back to a constant delay only when no
        # plan is supplied.
        self._page.fill(selector, "")
        if cadence_ms and len(cadence_ms) == len(value):
            locator = self._page.locator(selector)
            for ch, delay in zip(value, cadence_ms, strict=True):
                locator.press_sequentially(ch, delay=max(0.0, float(delay)))
        else:
            self._page.type(selector, value, delay=80)

    def set_input_files(self, selector: str, file_path: str) -> None:  # pragma: no cover
        # Attach the rendered base résumé to the file input (FR-RESUME-4). Playwright's
        # set_input_files drives the native file chooser without opening an OS dialog.
        self._page.set_input_files(selector, file_path)

    #: Phrasings that all mean "decline / prefer not to answer" — so the user's stored
    #: decline value (e.g. "prefer not to say" / "decline to self-identify") maps to a
    #: form's own wording for the same intent ("Decline To Self Identify", "I don't
    #: wish to answer", "I do not want to answer"), common on EEO dropdowns.
    _DECLINE_MARKERS: tuple[str, ...] = (
        "decline", "prefer not", "do not wish", "don't wish", "dont wish",
        "do not want", "don't want", "dont want", "not to answer", "not to say",
        "not to disclose", "not to identify", "rather not", "wish not", "choose not",
    )

    @staticmethod
    def _norm_text(s: str) -> str:  # pragma: no cover
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

    @classmethod
    def _is_decline(cls, text: str) -> bool:  # pragma: no cover
        low = (text or "").lower()
        return any(m in low for m in cls._DECLINE_MARKERS)

    @staticmethod
    def _significant_tokens(norm: str) -> set[str]:  # pragma: no cover
        """Word tokens excluding pure-number ones, so 'United States +1' (a dialing
        code) still matches 'United States of America'."""
        return {t for t in norm.split() if not t.isdigit()}

    @classmethod
    def _option_match(cls, want: str, opt: str) -> str | None:  # pragma: no cover
        """Match a wanted value to an option text: 'exact', 'loose' (one's significant
        WORD set is a subset of the other's, OR same decline-intent), or None.
        Token-based so a substring like 'male' does NOT match 'female'; pure-number
        tokens are ignored so a '+1' phone code does not block a country match.
        Punctuation/case-insensitive."""
        w, o = cls._norm_text(want), cls._norm_text(opt)
        if not w or not o:
            return None
        if w == o:
            return "exact"
        wt, ot = cls._significant_tokens(w), cls._significant_tokens(o)
        if wt and ot and (wt <= ot or ot <= wt):
            return "loose"
        if cls._is_decline(want) and cls._is_decline(opt):
            return "loose"
        return None

    def _is_select(self, selector: str) -> bool:  # pragma: no cover
        """True if ``selector`` resolves to a <select> element."""
        try:
            el = self._page.query_selector(selector)
            if el is None:
                return False
            return str(el.evaluate("e => e.tagName")).lower() == "select"
        except Exception:
            return False

    def _select_option(self, selector: str, value: str) -> None:  # pragma: no cover
        """Choose a <select> option matching ``value`` (label, then value, then a
        tolerant text match — substring overlap or same decline-intent). Raises if
        nothing matches so the caller's soft-error path records an unmappable field."""
        for kwargs in ({"label": value}, {"value": value}):
            try:
                self._page.select_option(selector, **kwargs)
                return
            except Exception:
                continue
        el = self._page.query_selector(selector)
        options = el.query_selector_all("option") if el is not None else []
        fallback: str | None = None
        for opt in options:
            try:
                txt = (opt.inner_text() or "").strip()
            except Exception:
                continue
            m = self._option_match(value, txt)
            if m == "exact":
                self._page.select_option(selector, label=txt)
                return
            if m == "loose" and fallback is None:
                fallback = txt
        if fallback is not None:
            self._page.select_option(selector, label=fallback)
            return
        raise ValueError(f"no <option> matching {value!r}")

    @staticmethod
    def _is_combobox(handle) -> bool:  # pragma: no cover
        """True if a handle is an ARIA dropdown — a custom <button> listbox OR a
        typeable combobox input (react-select etc.)."""
        try:
            haspopup = (handle.get_attribute("aria-haspopup") or "").lower()
            role = (handle.get_attribute("role") or "").lower()
            autocomplete = (handle.get_attribute("aria-autocomplete") or "").lower()
            return haspopup == "listbox" or role == "combobox" or autocomplete in ("list", "both")
        except Exception:
            return False

    def _is_listbox_button(self, selector: str) -> bool:  # pragma: no cover
        """True if ``selector`` is a custom dropdown — a button that opens a listbox,
        or an ARIA combobox (incl. a typeable react-select input) — vs a plain input."""
        el = self._page.query_selector(selector)
        return el is not None and self._is_combobox(el)

    def _choose_listbox_option(self, selector: str, value: str) -> None:  # pragma: no cover
        """Open a custom dropdown and click the option matching ``value``.

        Handles BOTH kinds of ARIA dropdown: a <button> listbox (Workday — click opens,
        options are already there) and a TYPEABLE combobox input (react-select, common
        on Greenhouse/Lever). Strategy: open, then match the already-visible options
        FIRST (short lists show all on open, and the match is synonym-aware so a stored
        "prefer not to say" maps to an option labelled "Decline To Self Identify");
        only if that misses AND the trigger is typeable do we type to FILTER a long
        list, then match again. Matching is exact-first, then a loose/decline match.
        """
        trigger = self._page.query_selector(selector)
        if trigger is None:
            raise ValueError(f"dropdown not found: {selector!r}")
        trigger.click()
        # 1. Match the options shown on open (no typing) — catches short lists + the
        #    synonym/decline case, which typing would WRONGLY filter to nothing.
        if self._pick_visible_option(value, 1.5):
            return
        # 2. Typeable combobox with a long/filtered list (e.g. country): type a SHORT
        #    filter query — the first couple of meaningful words — to narrow it down
        #    (typing the full value, e.g. "United States of America", often matches an
        #    option labelled "United States +1" literally → nothing), then match.
        is_input = str(trigger.evaluate("e => e.tagName")).lower() in ("input", "textarea")
        if is_input:
            try:
                trigger.fill("")
            except Exception:
                pass
            self._page.keyboard.type(self._filter_query(value), delay=15)
            if self._pick_visible_option(value, 4.0):
                return
            # Leave no half-typed filter string behind.
            try:
                self._page.keyboard.press("Escape")
                trigger.fill("")
            except Exception:
                pass
        raise ValueError(f"no listbox option matching {value!r}")

    @classmethod
    def _filter_query(cls, value: str) -> str:  # pragma: no cover
        """A short query to FILTER a long combobox list: the first couple of meaningful
        words (skip pure-number tokens). Typing the full value often matches nothing."""
        words = [w for w in value.split() if not cls._norm_text(w).isdigit()]
        return " ".join(words[:2]) if words else value

    def _pick_visible_option(self, value: str, timeout_s: float) -> bool:  # pragma: no cover
        """Poll up to ``timeout_s`` for a VISIBLE ``[role=option]`` matching ``value``
        and click it (exact preferred, else a loose/decline match). Returns True iff
        one was clicked. Visibility scoping skips options of other closed dropdowns."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            fallback = None
            for opt in self._page.query_selector_all("[role='option']"):
                try:
                    if not opt.is_visible():
                        continue
                    txt = (
                        opt.get_attribute("data-automation-label") or opt.inner_text() or ""
                    ).strip()
                except Exception:
                    continue
                if not txt:
                    continue
                m = self._option_match(value, txt)
                if m == "exact":
                    opt.click()
                    return True
                if m == "loose" and fallback is None:
                    fallback = opt
            if fallback is not None:
                fallback.click()
                return True
            time.sleep(0.1)
        return False

    def screenshot(self) -> str:  # pragma: no cover - integration-gated
        # Slugify the URL tail: a raw ``url[-12:]`` can contain ``/ ? :`` which are
        # invalid in a filename. Keep only filename-safe chars.
        slug = _slugify(self._page.url[-32:]) or "page"
        path = f"/tmp/applicant-{id(self)}-{slug}.png"
        self._page.screenshot(path=path)
        return f"file://{path}"

    def advance(self) -> PageState | None:  # pragma: no cover - integration-gated
        # Real multi-page navigation: a "Next"/"Continue" control is a benign
        # navigation (not an irreducible human step). Click the first matching
        # enabled control; if none exists we are at the end of the flow -> None.
        for sel in self._NEXT_SELECTORS:
            try:
                locator = self._page.locator(sel).first
                if locator.count() == 0:
                    continue
                if not locator.is_enabled():
                    continue
            except Exception:
                continue
            before = self._page.url
            try:
                locator.click()
                # Settle navigation/SPA transition before reading the new page.
                try:
                    self._page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    log.warning("advance(): wait_for_load_state timed out after 10 s", exc_info=True)
            except Exception:
                continue
            # Detect end-of-flow: clicking did not move us anywhere new.
            if self._page.url == before and not self._dom_changed():
                continue
            return self.current()
        return None

    def _dom_changed(self) -> bool:  # pragma: no cover - integration-gated
        """Heuristic for SPA flows where the URL stays fixed across pages."""
        try:
            return bool(self._page.locator("form, [data-automation-id]").count())
        except Exception:
            return False

    def is_account_create_page(self) -> bool:  # pragma: no cover
        # Robust: combine URL hints with on-page content/heading/button text so real
        # Workday ``/login`` + ``/register`` are not both swept up by ``"account"``.
        url = self._page.url.lower()
        text = self._heading_and_buttons().lower()
        url_hit = any(m in url for m in ("register", "createaccount", "create-account", "signup", "sign-up"))
        content_hit = any(
            m in text
            for m in ("create account", "create your account", "sign up", "register", "new account")
        )
        # A pure login page must NOT be misclassified as account-create.
        login_only = ("sign in" in text or "log in" in text or "login" in url) and not content_hit
        if login_only:
            return False
        return url_hit or content_hit

    #: Auth-entry controls that mark the account/sign-in GATE (Workday's combined
    #: "Create Account / Sign In" step renders these as buttons before any form field).
    #: Specific enough not to fire on a stray header "Sign In" link or a later form
    #: page. "Sign in with Google/LinkedIn" are OAuth flows the engine cannot drive —
    #: they are hand-offs, the same as the email path is before a stored credential.
    _ACCOUNT_GATE_MARKERS = (
        "sign in with email",
        "sign in with google",
        "sign in with linkedin",
        "sign in manually",
        "use my last application",
        "create account",
    )

    def is_account_gate(self) -> bool:  # pragma: no cover
        """True when the page is the account step — the user (or a stored credential)
        must SIGN IN or CREATE AN ACCOUNT before the application form is reachable.

        Broader than :meth:`is_account_create_page` (create-only): a Workday account
        step often renders sign-in *options* (buttons) before any input, so the loop
        must hand off here instead of mistaking a field-less gate for 'done'."""
        if self.is_account_create_page():
            return True
        text = self._heading_and_buttons().lower()
        return any(m in text for m in self._ACCOUNT_GATE_MARKERS)

    def is_final_submit_page(self) -> bool:  # pragma: no cover
        # Robust: a "review" personal-info page is NOT the final submit. Require a
        # submit-application content/button signal in addition to (or instead of) URL.
        url = self._page.url.lower()
        text = self._heading_and_buttons().lower()
        content_hit = any(
            m in text
            for m in (
                "submit application",
                "submit your application",
                "review and submit",
                "submit and apply",
            )
        )
        url_hit = "review" in url or "submit" in url
        # A "review your personal information" page should not be final-submit.
        review_personal = "review" in text and "personal" in text and not content_hit
        if review_personal:
            return False
        return content_hit or (url_hit and "submit" in text)

    def _heading_and_buttons(self) -> str:  # pragma: no cover - integration-gated
        """Collect heading + button text used by the page predicates."""
        parts: list[str] = []
        try:
            for sel in ("h1", "h2", "button", "[role='button']", "input[type='submit']"):
                for handle in self._page.query_selector_all(sel):
                    try:
                        parts.append(handle.inner_text())
                    except Exception:
                        val = handle.get_attribute("value")
                        if val:
                            parts.append(val)
        except Exception:
            pass
        return " ".join(parts)

    def is_confirmation_page(self) -> bool:  # pragma: no cover - integration-gated
        try:
            body_text = self._page.inner_text("body")
        except Exception:
            body_text = ""
        return detect_confirmation(url=self._page.url, text=body_text)

    def execute(self, plan: "Plan") -> list[dict]:  # pragma: no cover - integration-gated
        """Execute a plan-as-data typed-DSL plan against the live Playwright page."""
        from applicant.core.entities.plan import OpKind, FillOp, SelectOp, GotoOp

        results: list[dict] = []
        for op in plan:
            kind = op.kind
            try:
                if kind == OpKind.GOTO:
                    url = getattr(op, "url", "")
                    assert_navigable_url(url)
                    self._page.goto(url)
                    self._page.wait_for_load_state("networkidle", timeout=10_000)
                    results.append({"op": "goto", "ok": True, "detail": url})
                elif kind == OpKind.FILL:
                    ref = getattr(op, "ref", "")
                    sel = f"[data-applicant-ref='{ref}']"
                    val = getattr(op, "attribute_id", "")
                    self.type_value(sel, val)
                    results.append({"op": "fill", "ok": True, "detail": ref})
                elif kind == OpKind.SELECT:
                    ref = getattr(op, "ref", "")
                    sel = f"[data-applicant-ref='{ref}']"
                    val = getattr(op, "attribute_id", "")
                    self._select_option(sel, val)
                    results.append({"op": "select", "ok": True, "detail": ref})
                elif kind == OpKind.CLICK:
                    ref = getattr(op, "ref", "")
                    sel = f"[data-applicant-ref='{ref}']"
                    self._page.locator(sel).click()
                    results.append({"op": "click", "ok": True, "detail": ref})
                elif kind == OpKind.UPLOAD:
                    ref = getattr(op, "ref", "")
                    doc = getattr(op, "document_id", "")
                    sel = f"[data-applicant-ref='{ref}']"
                    self.set_input_files(sel, doc)
                    results.append({"op": "upload", "ok": True, "detail": ref})
                elif kind == OpKind.WAIT:
                    results.append({"op": "wait", "ok": True, "detail": "stub"})
                elif kind == OpKind.STOP:
                    results.append({"op": "stop", "ok": True, "detail": getattr(op, "reason", "")})
                else:
                    results.append({"op": kind.value, "ok": True, "detail": "stub"})
            except Exception as exc:
                results.append({"op": kind.value, "ok": False, "detail": str(exc)})
                break
        return results

    def close(self) -> None:  # pragma: no cover - integration-gated
        self._safe_teardown()
