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
    coherent_fingerprint,
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
        source_factory=None,
        channel: str = "chrome",
        engine: str = "camoufox",
        egress_timezone: str = "",
        egress_locale: str = "",
        persona: str = "linux",
        automated_accounts: bool = False,
        profiles_dir: str = "profiles",
    ) -> None:
        # FR-STEALTH-1: a single coherent REAL Linux + Google Chrome identity for
        # every session. The Chrome major is version-pinned to the installed Chrome
        # for the selected channel (so UA <-> CH-UA <-> engine all agree); a caller
        # may still inject an explicit fingerprint (tests).
        self._channel = channel or "chrome"
        # The browser engine every outbound request routes through (FR-STEALTH-1,
        # FR-PREFILL-1): ``camoufox`` (default) is the Firefox anti-detect browser;
        # ``chromium`` is the patchright/Chrome path. The CDP/native backend always
        # uses chromium (a remote real Chrome), regardless of this value.
        self._engine = (engine or "camoufox").strip().lower()
        # FR-STEALTH-1: ``linux`` = apply the coherent honest spoof (the default for
        # the local backend). ``native`` = use the browser's REAL identity with NO
        # fingerprint override (the Proxmox Windows backend: real Windows + real
        # Chrome already coherent). The persona is threaded into the real driver so a
        # CDP-connected Windows Chrome is never re-fingerprinted.
        self._persona = persona or "linux"
        self.fingerprint = dict(fingerprint or coherent_fingerprint(self._channel))
        # FR-STEALTH-1 <-> FR-STEALTH-4: tz/locale pinned to the residential egress
        # geolocation so tz/locale <-> exit IP stay consistent.
        if egress_timezone:
            self.fingerprint["timezone"] = egress_timezone
        if egress_locale:
            self.fingerprint["locale"] = egress_locale
        # FR-STEALTH-4: residential egress only — refuse a datacenter exit up front.
        self.egress = egress or EgressPolicy()
        self.egress.validate()
        self._use_real_browser = use_real_browser
        # ADR-0004: server-derived gate for automated account creation (default OFF).
        self._automated_accounts = bool(automated_accounts)
        self._rng = rng or random.Random()
        # FR-STEALTH-3: per-tenant profiles inherit the tz/locale-pinned coherent
        # identity so a returning user is consistent with the residential egress. The
        # root dir is configurable so the deploy persists sessions on a named volume
        # (a signed-in session is reused across applications + restarts).
        self._profiles = profiles or ProfileStore(
            root_dir=profiles_dir, fingerprint=self.fingerprint
        )
        # Optional page-source factory seam (tests): called as
        # ``factory(ats, fingerprint, user_data_dir=...)`` so the resolved per-tenant
        # ``user_data_dir`` (FR-STEALTH-3) can be asserted without a real browser.
        self._source_factory = source_factory
        self._sessions: dict[str, _Session] = {}

    # --- BrowserAutomationPort -------------------------------------------
    def open(
        self, application_id: ApplicationId, url: str, *, cdp_endpoint: str | None = None
    ) -> PageState:
        """Open ``url`` in the application's sandbox; return the first page state.

        ``cdp_endpoint`` (the native Proxmox Windows backend) makes the engine
        CONNECT to a remote Windows VM's Chrome over CDP instead of launching a local
        browser (FR-SANDBOX-1, FR-STEALTH-1). ``None`` keeps the local-launch path.
        """
        ats = resolve_ats(url)
        tenant_key = ats.tenant_key(url)
        # FR-STEALTH-3: a persistent per-tenant profile (same identity on return).
        profile = self._profiles.for_tenant(tenant_key)
        source = self._make_source(
            ats,
            profile.fingerprint,
            user_data_dir=profile.user_data_dir,
            cdp_endpoint=cdp_endpoint,
        )
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
        # Compute the per-keystroke cadence (FR-STEALTH-2) and ACTUALLY apply it: the
        # plan was previously computed then discarded, so the real driver typed at a
        # constant 80ms. Thread the dwell plan into the page source so believable,
        # per-character timing reaches Playwright's type API.
        plan = session.human.type_cadence(value)  # advances the per-session logical clock
        cadence_ms = [k.delay_ms for k in plan]
        session.source.type_value(selector, value, cadence_ms=cadence_ms)

    def upload_file(self, application_id: ApplicationId, selector: str, file_path: str) -> None:
        """Attach the rendered base résumé to a file input (FR-RESUME-4).

        Routes through the boundary as an ``UPLOAD_DOCUMENT`` step (always allowed —
        a deterministic pre-fill, never a submit), then hands the path to the page
        source's ``set_input_files`` (Playwright's native file-chooser drive).
        """
        ensure_action_allowed(StepKind.UPLOAD_DOCUMENT)
        session = self._session(application_id)
        session.human.think_delay()
        session.source.set_input_files(selector, file_path)

    def screenshot(self, application_id: ApplicationId) -> str:
        """Capture and store a per-page screenshot; return its ref (FR-LOG-2)."""
        ensure_action_allowed(StepKind.SCREENSHOT)
        return self._source(application_id).screenshot()

    def current_state(self, application_id: ApplicationId) -> PageState:
        """Return the current page state (incl. any detection signals)."""
        return self._source(application_id).current()

    # --- pre-fill loop helpers (used by PrefillService) -------------------
    def enter_application(self, application_id: ApplicationId) -> PageState | None:
        """Move from the job posting/landing page INTO the application flow by clicking
        the ATS "Apply" entry (FR-PREFILL-1). A benign navigation; ``None`` when no
        entry is needed (the URL already lands inside the flow)."""
        ensure_action_allowed(StepKind.NAVIGATE)
        return self._source(application_id).enter_application()

    def advance(self, application_id: ApplicationId) -> PageState | None:
        """Move to the next page in the ATS flow; ``None`` past the last page."""
        ensure_action_allowed(StepKind.NAVIGATE)
        return self._source(application_id).advance()

    def is_account_create_page(self, application_id: ApplicationId) -> bool:
        return self._source(application_id).is_account_create_page()

    def is_account_gate(self, application_id: ApplicationId) -> bool:
        """True at the account step — sign-in OR create-account (FR-PREFILL-4)."""
        return self._source(application_id).is_account_gate()

    def log_in(self, application_id: ApplicationId, username: str, password: str) -> bool:
        """Attempt an email/password sign-in from a stored credential; return success.

        A benign navigation/fill (NAVIGATE) — the engine drives login from a credential
        the user provided (automate-by-default). OAuth ("Sign in with Google") is NOT
        driven here."""
        ensure_action_allowed(StepKind.NAVIGATE)
        return self._source(application_id).log_in(username, password)

    def offers_google_signin(self, application_id: ApplicationId) -> bool:
        """True when the account gate offers OAuth 'Sign in with Google'."""
        return self._source(application_id).offers_google_signin()

    def log_in_with_google(self, application_id: ApplicationId, username: str, password: str) -> str:
        """Drive 'Sign in with Google' from a stored Google credential; return
        'ok' | 'two_factor' | 'failed' (a benign NAVIGATE/fill)."""
        ensure_action_allowed(StepKind.NAVIGATE)
        return self._source(application_id).log_in_with_google(username, password)

    def tenant_key(self, application_id: ApplicationId) -> str:
        """The credential-store key for the application's ATS host (e.g.
        ``workday:acme.wd5.myworkdayjobs.com``)."""
        return self._session(application_id).tenant_key

    def is_final_submit_page(self, application_id: ApplicationId) -> bool:
        return self._source(application_id).is_final_submit_page()

    def is_confirmation_page(self, application_id: ApplicationId) -> bool:
        """Auto-detect a post-submission confirmation page (FR-LOG-4)."""
        return self._source(application_id).is_confirmation_page()

    def submit_account(self, application_id: ApplicationId) -> None:
        """Click the account-creating submit — gated by ADR-0004.

        With ``ALLOW_AUTOMATED_ACCOUNTS`` OFF (the default) this raises
        ``PrefillBoundaryViolation`` (the boundary holds; the human creates the account
        in the live session). With it ON, the engine is permitted to create the account.
        """
        ensure_action_allowed(
            StepKind.ACCOUNT_CREATE_SUBMIT,
            automated_accounts_enabled=self._automated_accounts,
        )
        create = getattr(self._source(application_id), "submit_account", None)
        if callable(create):
            create()

    def create_account(self, application_id: ApplicationId, username: str, password: str) -> str:
        """Create an account from a predefined credential (ADR-0004, gated). Fills the
        create-account form, submits (boundary-checked), and reports the outcome:
        'ok' | 'email_verify' | 'failed'. With the gate OFF this raises before any
        action (the caller then hands off)."""
        ensure_action_allowed(
            StepKind.ACCOUNT_CREATE_SUBMIT,
            automated_accounts_enabled=self._automated_accounts,
        )
        return self._source(application_id).create_account(username, password)

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

    def inject_page_signals(self, application_id: ApplicationId, **kwargs) -> None:
        """Test/seam helper: set status/body/expected_host on the current page."""
        source = self._source(application_id)
        if isinstance(source, FakePageSource):
            source.inject_page_signals(**kwargs)

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
    def _make_source(
        self,
        ats,
        fingerprint: dict[str, str],
        *,
        user_data_dir: str = "",
        cdp_endpoint: str | None = None,
    ) -> PageSource:
        # Test seam: an injected factory receives the resolved per-tenant profile dir
        # AND (when it accepts it) the CDP endpoint, so the mode selection + endpoint
        # wiring is unit-tested with a fake (no real browser). The cdp_endpoint kwarg
        # is only passed when the factory declares it, so older factory signatures
        # ``(ats, fp, *, user_data_dir="")`` keep working unchanged.
        if self._source_factory is not None:
            import inspect

            kwargs: dict = {"user_data_dir": user_data_dir}
            try:
                params = inspect.signature(self._source_factory).parameters
                accepts = "cdp_endpoint" in params or any(
                    p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
                )
            except (TypeError, ValueError):  # pragma: no cover - exotic callables
                accepts = False
            if accepts:
                kwargs["cdp_endpoint"] = cdp_endpoint
            return self._source_factory(ats, fingerprint, **kwargs)
        if self._use_real_browser:  # pragma: no cover - integration-gated
            from applicant.adapters.browser.page_source import PlaywrightPageSource

            if cdp_endpoint:
                # Native Proxmox Windows backend: CONNECT to the remote Windows VM's
                # Chrome over CDP. Persona ``native`` -> NO fingerprint override (it
                # IS real Windows + real Chrome). No local profile/proxy/channel.
                return PlaywrightPageSource(
                    fingerprint,
                    cdp_endpoint=cdp_endpoint,
                    persona="native",
                )
            # FR-STEALTH-3: thread the persistent per-tenant profile dir into the real
            # browser launch so per-tenant persistence (same identity on return) works.
            # FR-STEALTH-4: thread the (validated) residential-egress proxy in too, so
            # a configured proxy is ACTUALLY used for egress. ``engine`` selects the
            # launch path (camoufox by default); both honor the proxy + profile dir.
            return PlaywrightPageSource(
                fingerprint,
                proxy=self.egress.launch_proxy(),
                user_data_dir=user_data_dir,
                channel=self._channel,
                persona=self._persona,
                engine=self._engine,
            )
        return FakePageSource(ats)

    def _session(self, application_id: ApplicationId) -> _Session:
        session = self._sessions.get(str(application_id))
        if session is None:
            raise KeyError(f"no open page for application {application_id}; call open() first")
        return session

    def _source(self, application_id: ApplicationId) -> PageSource:
        return self._session(application_id).source
