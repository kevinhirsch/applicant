"""PrefillService (FR-PREFILL-*, FR-ATTR-5/6).

# STAGE B — owned by Phase 2; flesh out here.

Drives maximal pre-fill via BrowserAutomation, routing every action through the
core pre-fill-stop boundary and sensitive-field policy. Stub until Phase 2.
"""

from __future__ import annotations

from applicant.core.ids import ApplicationId


class PrefillService:
    def __init__(self, storage, browser, detection, sandbox, credentials) -> None:
        self._storage = storage
        self._browser = browser
        self._detection = detection
        self._sandbox = sandbox
        self._credentials = credentials

    def prefill_application(self, application_id: ApplicationId) -> None:
        raise NotImplementedError("STAGE B — Phase 2: maximal pre-fill pipeline.")
