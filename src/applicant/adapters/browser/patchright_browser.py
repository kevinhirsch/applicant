"""patchright/Playwright browser-automation adapter (FR-PREFILL-*, FR-STEALTH-*).

# STAGE B — owned by Phase 2; flesh out here.

Performs maximal pre-fill while routing every click/submit through the core
pre-fill-stop boundary (``core.rules.prefill_boundary``) so it can never click an
account-creating submit, solve a CAPTCHA, or complete verification.
"""

from __future__ import annotations

from applicant.core.ids import ApplicationId
from applicant.ports.driven.browser_automation import DetectedField, PageState


class PatchrightBrowser:
    """BrowserAutomationPort adapter (stub until Phase 2)."""

    def open(self, application_id: ApplicationId, url: str) -> PageState:
        raise NotImplementedError("STAGE B — Phase 2: launch patchright + open URL.")

    def detect_fields(self, application_id: ApplicationId) -> list[DetectedField]:
        raise NotImplementedError("STAGE B — Phase 2: field detection.")

    def fill_field(self, application_id: ApplicationId, selector: str, value: str) -> None:
        raise NotImplementedError("STAGE B — Phase 2: human-like fill (FR-STEALTH-2).")

    def screenshot(self, application_id: ApplicationId) -> str:
        raise NotImplementedError("STAGE B — Phase 2: capture + store screenshot (FR-LOG-2).")

    def current_state(self, application_id: ApplicationId) -> PageState:
        raise NotImplementedError("STAGE B — Phase 2: page-state snapshot.")
