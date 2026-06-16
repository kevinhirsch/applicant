"""patchright/Playwright browser-automation adapter (FR-PREFILL-*, FR-STEALTH-*).

Performs maximal pre-fill while routing every click/submit through the core
pre-fill-stop boundary (``core.rules.prefill_boundary``) so it can never click an
account-creating submit, solve a CAPTCHA, or complete verification.

Composition (the real boundaries the work package asks for):

* :class:`~applicant.adapters.browser.page_source.PageSource` — the swappable
  page-driver. The DEFAULT lane uses :class:`FakePageSource` (in-memory, NO
  browser). The REAL :class:`PlaywrightPageSource` (patchright/Playwright) drops in
  with no other change (FR-PREFILL-1); it is integration-gated.
* :mod:`~applicant.adapters.browser.ats` — the ATS abstraction + Workday adapter
  (FR-PREFILL-2). New ATS = new subclass, no core change.
* :mod:`~applicant.adapters.browser.stealth` — coherent honest fingerprint
  (FR-STEALTH-1), human-like interaction (FR-STEALTH-2), persistent per-tenant
  profile (FR-STEALTH-3), and the residential-egress seam (FR-STEALTH-4).

The default lane needs NO browser binary; ``use_real_browser=True`` (integration
only) swaps in the Playwright driver.
"""

from __future__ import annotations

import random

# Backwards-compatible re-exports (contract tests / BDD import these from here).
from applicant.adapters.browser.ats import (
    WorkdayAts,  # noqa: E402,F401  (re-export)
    resolve_ats,
)
from applicant.adapters.browser.page_source import (
    FakePageSource,
    PageSource,
)
from applicant.adapters.browser.stealth import (
    NORMALIZED_FINGERPRINT,
    STEALTH_CAVEAT,
    EgressPolicy,
    HumanInteraction,
    ProfileStore,
    fingerprint_is_coherent,
)
from applicant.core.ids import ApplicationId
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed
from applicant.ports.driven.browser_automation import DetectedField, PageState

__all__ = [
    "PatchrightBrowser",
    "WorkdayAts",
    "NORMALIZED_FINGERPRINT",
    "STEALTH_CAVEAT",
    "fingerprint_is_coherent",
]


class _Session:
    """Per-application browser session: a page source + its stealth context."""

    def __init__(self, source: PageSource, human: HumanInteraction, tenant_key: str) -> None:
        self.source = source
        self.human = human
        self.tenant_key = tenant_key


class PatchrightBrowser:
    """BrowserAutomationPort adapter (FR-PREFILL-*, FR-STEALTH-*).

    Every click/submit is routed through ``ensure_action_allowed`` so the
    pre-fill-stop boundary (FR-PREFILL-4) cannot be bypassed by this adapter.
    """

    #: Honest best-effort caveat copy for the UX (FR-STEALTH-5).
    caveat = STEALTH_CAVEAT

    def __init__(
        self,
        fingerprint: dict[str, str] | None = None,
        *,
        use_real_browser: bool = False,
        egress: EgressPolicy | None = None,
        rng: random.Random | None = None,
        profiles: ProfileStore | None = None,
    ) -> None:
        # FR-STEALTH-1: normalized, coherent identity for every session.
        self.fingerprint = dict(fingerprint or NORMALIZED_FINGERPRINT)
        # FR-STEALTH-4: residential egress only — refuse a datacenter exit up front.
        self.egress = egress or EgressPolicy()
        self.egress.validate()
        self._use_real_browser = use_real_browser
        self._rng = rng or random.Random()
        self._profiles = profiles or ProfileStore()
        self._sessions: dict[str, _Session] = {}

    # --- BrowserAutomationPort -------------------------------------------
    def open(self, application_id: ApplicationId, url: str) -> PageState:
        """Open ``url`` in the application's sandbox; return the first page state."""
        ats = resolve_ats(url)
        tenant_key = ats.tenant_key(url)
        # FR-STEALTH-3: a persistent per-tenant profile (same identity on return).
        profile = self._profiles.for_tenant(tenant_key)
        source = self._make_source(ats, profile.fingerprint)
        source.open(url)
        # FR-STEALTH-2: a per-session human-interaction model (deterministic rng).
        human = HumanInteraction(random.Random(self._rng.random()))
        self._sessions[str(application_id)] = _Session(source, human, tenant_key)
        return source.current()

    def detect_fields(self, application_id: ApplicationId) -> list[DetectedField]:
        """Detect all fillable fields on the current page (FR-PREFILL-2/3)."""
        return list(self._source(application_id).detect_fields())

    def fill_field(self, application_id: ApplicationId, selector: str, value: str) -> None:
        """Fill a single field (a deterministic, idempotent step).

        Filling routes through the boundary as a ``FILL_FIELD`` step (always
        allowed). Before typing, a human-like cadence/think-delay is computed
        (FR-STEALTH-2) so the real driver feeds believable timing into the page.
        """
        ensure_action_allowed(StepKind.FILL_FIELD)
        session = self._session(application_id)
        session.human.think_delay()
        session.human.type_cadence(value)  # advances the per-session logical clock
        session.source.type_value(selector, value)

    def screenshot(self, application_id: ApplicationId) -> str:
        """Capture and store a per-page screenshot; return its ref (FR-LOG-2)."""
        ensure_action_allowed(StepKind.SCREENSHOT)
        return self._source(application_id).screenshot()

    def current_state(self, application_id: ApplicationId) -> PageState:
        """Return the current page state (incl. any detection signals)."""
        return self._source(application_id).current()

    # --- pre-fill loop helpers (used by PrefillService) -------------------
    def advance(self, application_id: ApplicationId) -> PageState | None:
        """Move to the next page in the ATS flow; ``None`` past the last page."""
        ensure_action_allowed(StepKind.NAVIGATE)
        return self._source(application_id).advance()

    def is_account_create_page(self, application_id: ApplicationId) -> bool:
        return self._source(application_id).is_account_create_page()

    def is_final_submit_page(self, application_id: ApplicationId) -> bool:
        return self._source(application_id).is_final_submit_page()

    def is_confirmation_page(self, application_id: ApplicationId) -> bool:
        """Auto-detect a post-submission confirmation page (FR-LOG-4)."""
        return self._source(application_id).is_confirmation_page()

    def submit_account(self, application_id: ApplicationId) -> None:
        """The engine must NEVER call this without violating the boundary.

        It exists so the boundary is provable: any attempt raises
        ``PrefillBoundaryViolation`` (FR-PREFILL-4). The human does this in VNC.
        """
        ensure_action_allowed(StepKind.ACCOUNT_CREATE_SUBMIT)

    def click_final_submit(
        self, application_id: ApplicationId, *, engine_submit_authorized: bool = False
    ) -> None:
        """Click the final submit — only when the user authorized it (FR-PREFILL-5)."""
        ensure_action_allowed(
            StepKind.FINAL_SUBMIT, engine_submit_authorized=engine_submit_authorized
        )
        # In the fake model a permitted final submit is a no-op success.

    def filled_values(self, application_id: ApplicationId) -> dict[str, str]:
        """All values filled on the current page (introspection for tests/logs)."""
        source = self._source(application_id)
        if isinstance(source, FakePageSource):
            return source.filled()
        return {}

    def inject_detection_signal(self, application_id: ApplicationId, signal: str) -> None:
        """Test/seam helper: simulate a detection signal on the current page."""
        source = self._source(application_id)
        if isinstance(source, FakePageSource):
            source.inject_detection_signal(signal)

    def simulate_confirmation(
        self, application_id: ApplicationId, *, text: str = "Application submitted"
    ) -> None:
        """Test/seam helper: render a confirmation page (post-submit) (FR-LOG-4)."""
        source = self._source(application_id)
        if isinstance(source, FakePageSource):
            source.simulate_confirmation(text=text)

    def is_returning_visitor(self, application_id: ApplicationId) -> bool:
        """Whether the per-tenant profile has been seen before (FR-STEALTH-3)."""
        return self._profiles.is_returning(self._session(application_id).tenant_key)

    # --- internals -------------------------------------------------------
    def _make_source(self, ats, fingerprint: dict[str, str]) -> PageSource:
        if self._use_real_browser:  # pragma: no cover - integration-gated
            from applicant.adapters.browser.page_source import PlaywrightPageSource

            return PlaywrightPageSource(fingerprint)
        return FakePageSource(ats)

    def _session(self, application_id: ApplicationId) -> _Session:
        session = self._sessions.get(str(application_id))
        if session is None:
            raise KeyError(f"no open page for application {application_id}; call open() first")
        return session

    def _source(self, application_id: ApplicationId) -> PageSource:
        return self._session(application_id).source
