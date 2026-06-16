"""BrowserAutomation port (FR-PREFILL-*, FR-STEALTH-*).

patchright/Playwright primary; browser-use/Skyvern AI fallback. The adapter
performs maximal pre-fill but MUST route every click/submit through the core
pre-fill-stop boundary (``core.rules.prefill_boundary``): it never clicks an
account-creating submit, never solves a CAPTCHA, never completes verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from applicant.core.ids import ApplicationId


@dataclass(frozen=True)
class DetectedField:
    """A fillable field detected on a page."""

    selector: str
    label: str
    field_type: str  # text/select/checkbox/radio/file...
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class PageState:
    """A snapshot of the current page during pre-fill."""

    url: str
    fields: tuple[DetectedField, ...] = ()
    screenshot_ref: str | None = None
    detection_signals: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class BrowserAutomationPort(Protocol):
    """Outbound port for driving the browser during pre-fill."""

    def open(self, application_id: ApplicationId, url: str) -> PageState:
        """Open ``url`` in the application's sandbox and return page state."""
        ...

    def detect_fields(self, application_id: ApplicationId) -> list[DetectedField]:
        """Detect all fillable fields on the current page (FR-PREFILL-2/3)."""
        ...

    def fill_field(self, application_id: ApplicationId, selector: str, value: str) -> None:
        """Fill a single field (a deterministic, idempotent step)."""
        ...

    def screenshot(self, application_id: ApplicationId) -> str:
        """Capture and store a per-page screenshot; return its ref (FR-LOG-2)."""
        ...

    def current_state(self, application_id: ApplicationId) -> PageState:
        """Return the current page state (incl. any detection signals)."""
        ...
