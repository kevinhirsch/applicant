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
    #: Whether the form marks the field required. ``None`` = unknown (the source did
    #: not determine it) → callers keep the legacy "required by type" behavior; ``True``
    #: / ``False`` come from the real DOM (``required`` / ``aria-required``) so the
    #: engine blocks only on TRULY required unmapped fields and skips optional ones
    #: (universal-ATS support: real forms carry many optional free-text questions).
    required: bool | None = None


@dataclass(frozen=True)
class PageState:
    """A snapshot of the current page during pre-fill.

    Carries the full set of detection-relevant signals so cautious mode can classify
    HTTP-status blocks (403/429), anomalous redirects (``url`` vs ``expected_host``),
    and body markers (Cloudflare/CAPTCHA text) — not just the extracted
    ``detection_signals`` tuple (FR-PREFILL-6).
    """

    url: str
    fields: tuple[DetectedField, ...] = ()
    screenshot_ref: str | None = None
    detection_signals: tuple[str, ...] = field(default_factory=tuple)
    #: HTTP status of the page response (FR-PREFILL-6): 403/429 => blocked.
    status: int | None = None
    #: Raw page body/markup, scanned for challenge markers (FR-PREFILL-6).
    body: str | None = None
    #: The host we expected to land on; a mismatch is an anomalous redirect.
    expected_host: str | None = None


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

    def upload_file(self, application_id: ApplicationId, selector: str, file_path: str) -> None:
        """Attach ``file_path`` to a file ``<input type=file>`` (FR-RESUME-4).

        Uploads the rendered base résumé; a deterministic pre-fill step (no submit),
        so it stays inside the pre-fill-stop boundary.
        """
        ...

    def screenshot(self, application_id: ApplicationId) -> str:
        """Capture and store a per-page screenshot; return its ref (FR-LOG-2)."""
        ...

    def current_state(self, application_id: ApplicationId) -> PageState:
        """Return the current page state (incl. any detection signals)."""
        ...
