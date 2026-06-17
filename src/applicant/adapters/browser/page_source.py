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

import re
from typing import Protocol, runtime_checkable

from applicant.adapters.browser.ats import AtsAdapter, FakePage, resolve_ats
from applicant.ports.driven.browser_automation import DetectedField, PageState

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

    def screenshot(self) -> str:
        """Capture a per-page screenshot; return its ref (FR-LOG-2)."""
        ...

    def advance(self) -> PageState | None:
        """Move to the next page; ``None`` once past the last page."""
        ...

    def is_account_create_page(self) -> bool:
        ...

    def is_final_submit_page(self) -> bool:
        ...

    def is_confirmation_page(self) -> bool:
        """True if the current page is a post-submission confirmation (FR-LOG-4)."""
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

    def screenshot(self) -> str:
        self._screenshot_seq += 1
        return f"screenshot://fake/{self._index}/{self._screenshot_seq}"

    def advance(self) -> PageState | None:
        if self._index + 1 >= len(self._pages):
            return None
        self._index += 1
        return self.current()

    def is_account_create_page(self) -> bool:
        return self._page.is_account_create

    def is_final_submit_page(self) -> bool:
        return self._page.is_final_submit

    def is_confirmation_page(self) -> bool:
        page = self._page
        # An explicit flag short-circuits; otherwise apply the URL/text heuristics.
        return page.is_confirmation or detect_confirmation(url=page.url, text=page.text)

    # --- test/seam helpers (used by the adapter + tests) -----------------
    def filled(self) -> dict[str, str]:
        return dict(self._page.filled)

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

    def simulate_confirmation(self, *, text: str = "Application submitted") -> None:
        """Seam/test helper: turn the current page into a confirmation page.

        Models what the live driver observes after the user (or authorized engine)
        clicks final submit and the ATS renders its confirmation page.
        """
        from dataclasses import replace

        page = self._page
        self._pages[self._index] = replace(page, is_confirmation=True, text=text)


# --- real patchright/Playwright driver (REAL, integration-gated) -------------
class PlaywrightPageSource:
    """REAL :class:`PageSource` backed by patchright (Playwright fork) (FR-PREFILL-1).

    Imports the browser driver LAZILY so importing this module costs nothing and
    needs no browser binary; the default test lane never constructs this class.
    Only an integration-gated smoke test (which skips if no browser is installed)
    drives it. The human-like input cadence (FR-STEALTH-2) and the coherent
    fingerprint (FR-STEALTH-1) are applied via the launch args here.

    NOTE: clicks/submits are NOT performed here — the adapter routes the boundary
    decisions; this driver only navigates + reads + types + screenshots, never
    clicking an account-create or final submit (FR-PREFILL-4/5).
    """

    def __init__(
        self,
        fingerprint: dict[str, str],
        *,
        headless: bool = True,
        proxy: dict[str, str] | None = None,
        user_data_dir: str = "",
    ) -> None:
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

        self._fingerprint = dict(fingerprint)
        # FR-STEALTH-4: the residential-egress proxy (or None for direct egress),
        # threaded into the launch kwargs below.
        self._proxy = dict(proxy) if proxy else None
        self._pw = sync_playwright().start()
        # If context/page construction fails, stop the started Playwright process
        # so the driver does not leak (the old __init__ left the node process running
        # on any error after start()).
        self._context = None
        self._page = None
        # Captured per-navigation main-frame HTTP status + the expected host so
        # current() can populate cautious-mode signals (FR-PREFILL-6).
        self._status: int | None = None
        self._expected_host: str | None = None
        try:  # pragma: no cover - integration-gated
            kwargs = self.launch_kwargs(
                self._fingerprint, headless=headless, proxy=self._proxy, user_data_dir=user_data_dir
            )
            self._context = self._pw.chromium.launch_persistent_context(**kwargs)
            # FR-STEALTH-1: apply the coherent fingerprint (WebGL vendor/renderer +
            # navigator.platform) to every page in the context via an init script so
            # the launched browser actually reports the normalized identity, not the
            # host's real GPU/platform.
            self._apply_fingerprint_overrides(self._context)
            self._page = self._context.new_page()
            self._page.on("response", self._on_response)
        except Exception:
            self._safe_teardown()
            raise

    def _on_response(self, response) -> None:  # pragma: no cover - integration-gated
        """Capture the main-frame document response status for cautious mode."""
        try:
            if response.url == self._page.url or response.request.is_navigation_request():
                self._status = response.status
        except Exception:
            pass

    def _safe_teardown(self) -> None:  # pragma: no cover - integration-gated
        """Best-effort cleanup of a partially-constructed driver."""
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass

    @staticmethod
    def fingerprint_init_script(fingerprint: dict[str, str]) -> str:
        """Build the JS init script that spoofs WebGL vendor/renderer + platform.

        Pure + unit-testable (no browser): the default lane asserts the normalized
        WebGL vendor/renderer and ``navigator.platform`` are baked into the script
        that is injected into every page (FR-STEALTH-1).
        """
        import json as _json

        vendor = fingerprint.get("webgl_vendor", "")
        renderer = fingerprint.get("webgl_renderer", "")
        platform = fingerprint.get("platform", "")
        return (
            "(() => {"
            f"  const vendor = {_json.dumps(vendor)};"
            f"  const renderer = {_json.dumps(renderer)};"
            f"  const platform = {_json.dumps(platform)};"
            "  try {"
            "    Object.defineProperty(navigator, 'platform', {get: () => platform});"
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

    @staticmethod
    def launch_kwargs(
        fingerprint: dict[str, str],
        *,
        headless: bool = True,
        proxy: dict[str, str] | None = None,
        user_data_dir: str = "",
    ) -> dict:
        """Build the ``launch_persistent_context`` kwargs (pure + unit-testable).

        Kept pure (no browser) so the default lane can assert the coherent
        fingerprint (FR-STEALTH-1) AND the residential-egress proxy (FR-STEALTH-4)
        are threaded into the real launch, without constructing a browser.
        """
        width, _, height = fingerprint.get("resolution", "1920x1080").partition("x")
        kwargs: dict = {
            "user_data_dir": user_data_dir,  # the adapter supplies a per-tenant dir
            "headless": headless,
            "user_agent": fingerprint.get("user_agent"),
            "locale": fingerprint.get("locale", "en-US"),
            "timezone_id": fingerprint.get("timezone", "America/Phoenix"),
            "viewport": {"width": int(width or 1920), "height": int(height or 1080)},
        }
        if proxy:
            # FR-STEALTH-4: residential proxy actually used for automation egress.
            kwargs["proxy"] = dict(proxy)
        return kwargs

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

    def open(self, url: str) -> None:  # pragma: no cover - integration-gated
        # Remember the host we expected so an anomalous redirect is detectable.
        self._expected_host = url.split("//", 1)[-1].split("/", 1)[0] or None
        response = self._page.goto(url)
        if response is not None:
            self._status = response.status

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

    def _detection_signals(self, body: str) -> tuple[str, ...]:  # pragma: no cover
        """Extract challenge markers from the page body (Cloudflare/CAPTCHA/etc)."""
        low = (body or "").lower()
        markers = (
            "captcha",
            "recaptcha",
            "hcaptcha",
            "turnstile",
            "cloudflare",
            "checking your browser",
            "datadome",
        )
        return tuple(m for m in markers if m in low)

    def detect_fields(self) -> list[DetectedField]:  # pragma: no cover
        fields: list[DetectedField] = []
        for handle in self._page.query_selector_all("input, select, textarea"):
            # The logical key (name/id) for bookkeeping AND a REAL selector usable by
            # Playwright fill/type. A raw ``name``/``id`` attribute value is NOT a
            # selector — fields never resolved. Build ``[name="..."]`` / ``#id``.
            name = handle.get_attribute("name") or ""
            elem_id = handle.get_attribute("id") or ""
            selector = self._build_selector(name, elem_id, handle)
            label = (
                handle.get_attribute("aria-label")
                or handle.get_attribute("placeholder")
                or name
                or elem_id
            )
            ftype = handle.get_attribute("type") or handle.evaluate("e => e.tagName.toLowerCase()")
            if selector:
                fields.append(DetectedField(selector=selector, label=label, field_type=ftype))
        return fields

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
                    pass
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

    def close(self) -> None:  # pragma: no cover - integration-gated
        self._safe_teardown()
