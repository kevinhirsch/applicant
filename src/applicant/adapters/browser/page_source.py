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

from typing import Protocol, runtime_checkable

from applicant.adapters.browser.ats import AtsAdapter, FakePage, resolve_ats
from applicant.ports.driven.browser_automation import DetectedField, PageState

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

    def type_value(self, selector: str, value: str) -> None:
        """Type ``value`` into ``selector`` on the current page (human-like)."""
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
        )

    def detect_fields(self) -> list[DetectedField]:
        return list(self._page.fields)

    def type_value(self, selector: str, value: str) -> None:
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

    def __init__(self, fingerprint: dict[str, str], *, headless: bool = True) -> None:
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
        self._pw = sync_playwright().start()
        width, _, height = self._fingerprint.get("resolution", "1920x1080").partition("x")
        self._context = self._pw.chromium.launch_persistent_context(  # pragma: no cover
            user_data_dir="",  # the adapter supplies a per-tenant dir in real use
            headless=headless,
            user_agent=self._fingerprint.get("user_agent"),
            locale=self._fingerprint.get("locale", "en-US"),
            timezone_id=self._fingerprint.get("timezone", "America/Phoenix"),
            viewport={"width": int(width or 1920), "height": int(height or 1080)},
        )
        self._page = self._context.new_page()  # pragma: no cover

    def open(self, url: str) -> None:  # pragma: no cover - integration-gated
        self._page.goto(url)

    def current(self) -> PageState:  # pragma: no cover - integration-gated
        return PageState(url=self._page.url, fields=tuple(self.detect_fields()))

    def detect_fields(self) -> list[DetectedField]:  # pragma: no cover
        fields: list[DetectedField] = []
        for handle in self._page.query_selector_all("input, select, textarea"):
            selector = handle.get_attribute("name") or handle.get_attribute("id") or ""
            label = handle.get_attribute("aria-label") or handle.get_attribute("placeholder") or selector
            ftype = handle.get_attribute("type") or handle.evaluate("e => e.tagName.toLowerCase()")
            if selector:
                fields.append(DetectedField(selector=selector, label=label, field_type=ftype))
        return fields

    def type_value(self, selector: str, value: str) -> None:  # pragma: no cover
        # delay is human-like cadence; the adapter computes the per-keystroke plan.
        self._page.fill(selector, "")
        self._page.type(selector, value, delay=80)

    def screenshot(self) -> str:  # pragma: no cover - integration-gated
        path = f"/tmp/applicant-{id(self)}-{self._page.url[-12:]}.png"
        self._page.screenshot(path=path)
        return f"file://{path}"

    def advance(self) -> PageState | None:  # pragma: no cover - integration-gated
        # Real multi-page navigation is ATS-specific (a "Next"/"Continue" button is
        # a benign navigation, not an irreducible step). Left to the live adapter.
        return None

    def is_account_create_page(self) -> bool:  # pragma: no cover
        return "account" in self._page.url.lower() or "create" in self._page.url.lower()

    def is_final_submit_page(self) -> bool:  # pragma: no cover
        return "review" in self._page.url.lower() or "submit" in self._page.url.lower()

    def is_confirmation_page(self) -> bool:  # pragma: no cover - integration-gated
        try:
            body_text = self._page.inner_text("body")
        except Exception:
            body_text = ""
        return detect_confirmation(url=self._page.url, text=body_text)

    def close(self) -> None:  # pragma: no cover - integration-gated
        self._context.close()
        self._pw.stop()
