"""patchright/Playwright browser-automation adapter (FR-PREFILL-*, FR-STEALTH-*).

# STAGE B — owned by Phase 2; fleshed out as a thin scaffold.

Performs maximal pre-fill while routing every click/submit through the core
pre-fill-stop boundary (``core.rules.prefill_boundary``) so it can never click an
account-creating submit, solve a CAPTCHA, or complete verification.

Scope note: this is a **thin scaffold**, NOT real browser automation. The real
patchright/Playwright driver is replaced with an in-memory **fake page model**
(:class:`FakePage`) so the whole shape — open, detect fields, fill, screenshot,
state snapshots, the prefill-boundary, fingerprint normalization (FR-STEALTH-1),
and the ATS abstraction with a Workday adapter — is exercised and contract-tested
WITH NO BROWSER INSTALLED. Swapping ``FakePage`` for a real patchright page is the
only change required to make this live.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from applicant.core.ids import ApplicationId
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed
from applicant.ports.driven.browser_automation import DetectedField, PageState

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
    if "mac os" in ua and "win" in platform:
        return False
    return bool(fp.get("locale") and fp.get("timezone") and fp.get("resolution"))


# --- in-memory fake page model (stands in for a real patchright page) --------
@dataclass
class FakePage:
    """An in-memory model of a single rendered page (NO real browser)."""

    url: str
    fields: tuple[DetectedField, ...] = ()
    detection_signals: tuple[str, ...] = ()
    #: selector -> filled value (mutated by :meth:`fill`).
    filled: dict[str, str] = field(default_factory=dict)
    #: whether this page is an account-creation form (boundary applies).
    is_account_create: bool = False
    #: whether this page is the final-submit step (boundary applies).
    is_final_submit: bool = False


# --- ATS abstraction --------------------------------------------------------
class AtsAdapter:
    """Base ATS abstraction (FR-PREFILL-2): an ATS knows its page sequence.

    Concrete ATS adapters (Workday first) model the pages an application walks
    through and the fields each exposes, so the maximal-pre-fill loop is ATS
    agnostic. This is the swappable seam: new ATS = new subclass, no core change.
    """

    name = "generic"

    def pages(self, url: str) -> list[FakePage]:  # pragma: no cover - overridden
        raise NotImplementedError


class WorkdayAts(AtsAdapter):
    """Workday ATS adapter shape (FR-PREFILL-2: MVP-1 MUST work on Workday).

    Models the canonical Workday flow: an account-creation page (per-tenant),
    then the personal-info / experience / voluntary-EEO pages, then final submit.
    Fields include sensitive EEO fields so the sensitive-field policy is exercised.
    """

    name = "workday"

    def __init__(self, tenant_key: str = "acme.workday") -> None:
        self.tenant_key = tenant_key

    def pages(self, url: str) -> list[FakePage]:
        return [
            FakePage(
                url=f"{url}/account/create",
                is_account_create=True,
                fields=(
                    DetectedField("#email", "Email Address", "text"),
                    DetectedField("#password", "Password", "password"),
                    DetectedField("#verify-password", "Verify Password", "password"),
                ),
            ),
            FakePage(
                url=f"{url}/application/personal",
                fields=(
                    DetectedField("#first-name", "First Name", "text"),
                    DetectedField("#last-name", "Last Name", "text"),
                    DetectedField("#phone", "Phone", "text"),
                    DetectedField("#address", "Address", "text"),
                ),
            ),
            FakePage(
                url=f"{url}/application/experience",
                fields=(
                    DetectedField("#current-title", "Current Job Title", "text"),
                    DetectedField("#years-exp", "Years of Experience", "text"),
                    DetectedField(
                        "#work-auth",
                        "Are you authorized to work?",
                        "select",
                        options=("Yes", "No"),
                    ),
                ),
            ),
            FakePage(
                # Voluntary self-identification (EEO) — sensitive fields here.
                url=f"{url}/application/voluntary-disclosures",
                fields=(
                    DetectedField(
                        "#gender",
                        "Gender",
                        "select",
                        options=("Male", "Female", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "#race",
                        "Race/Ethnicity",
                        "select",
                        options=("...", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "#veteran",
                        "Protected Veteran Status",
                        "select",
                        options=("Yes", "No", "Decline to self-identify"),
                    ),
                ),
            ),
            FakePage(
                url=f"{url}/application/review-submit",
                is_final_submit=True,
                fields=(),
            ),
        ]


#: Registry of ATS adapters keyed by name (extensible — FR-PREFILL-2 abstraction).
_ATS_REGISTRY: dict[str, type[AtsAdapter]] = {WorkdayAts.name: WorkdayAts}


def resolve_ats(url: str) -> AtsAdapter:
    """Pick an ATS adapter from a URL (Workday default for MVP-1)."""
    if "workday" in url.lower() or "myworkdayjobs" in url.lower():
        return WorkdayAts()
    return WorkdayAts()  # MVP-1 ships only Workday; others follow as adapters.


@dataclass
class _Session:
    ats: AtsAdapter
    pages: list[FakePage]
    index: int = 0
    screenshot_seq: int = 0

    @property
    def page(self) -> FakePage:
        return self.pages[self.index]


class PatchrightBrowser:
    """BrowserAutomationPort adapter backed by an in-memory fake page model.

    Every click/submit is routed through ``ensure_action_allowed`` so the
    pre-fill-stop boundary (FR-PREFILL-4) cannot be bypassed by this adapter.
    """

    def __init__(self, fingerprint: dict[str, str] | None = None) -> None:
        # FR-STEALTH-1: normalized, coherent identity for every session.
        self.fingerprint = dict(fingerprint or NORMALIZED_FINGERPRINT)
        self._sessions: dict[str, _Session] = {}

    # --- BrowserAutomationPort -------------------------------------------
    def open(self, application_id: ApplicationId, url: str) -> PageState:
        """Open ``url`` in the application's sandbox; return the first page state."""
        ats = resolve_ats(url)
        session = _Session(ats=ats, pages=ats.pages(url))
        self._sessions[str(application_id)] = session
        return self._state(session)

    def detect_fields(self, application_id: ApplicationId) -> list[DetectedField]:
        """Detect all fillable fields on the current page (FR-PREFILL-2/3)."""
        return list(self._session(application_id).page.fields)

    def fill_field(self, application_id: ApplicationId, selector: str, value: str) -> None:
        """Fill a single field (a deterministic, idempotent step).

        Filling routes through the boundary as a ``FILL_FIELD`` step (always
        allowed) — the human-like cadence (FR-STEALTH-2) is a real-driver detail.
        """
        ensure_action_allowed(StepKind.FILL_FIELD)
        self._session(application_id).page.filled[selector] = value

    def screenshot(self, application_id: ApplicationId) -> str:
        """Capture and store a per-page screenshot; return its ref (FR-LOG-2)."""
        session = self._session(application_id)
        session.screenshot_seq += 1
        return f"screenshot://{application_id}/{session.index}/{session.screenshot_seq}"

    def current_state(self, application_id: ApplicationId) -> PageState:
        """Return the current page state (incl. any detection signals)."""
        return self._state(self._session(application_id))

    # --- pre-fill loop helpers (used by PrefillService) -------------------
    def advance(self, application_id: ApplicationId) -> PageState | None:
        """Move to the next page in the ATS flow; ``None`` past the last page."""
        session = self._session(application_id)
        if session.index + 1 >= len(session.pages):
            return None
        session.index += 1
        return self._state(session)

    def is_account_create_page(self, application_id: ApplicationId) -> bool:
        return self._session(application_id).page.is_account_create

    def is_final_submit_page(self, application_id: ApplicationId) -> bool:
        return self._session(application_id).page.is_final_submit

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
        return dict(self._session(application_id).page.filled)

    def inject_detection_signal(self, application_id: ApplicationId, signal: str) -> None:
        """Test/seam helper: simulate a detection signal on the current page."""
        session = self._session(application_id)
        page = session.page
        session.pages[session.index] = replace(
            page, detection_signals=(*page.detection_signals, signal)
        )

    # --- internals -------------------------------------------------------
    def _session(self, application_id: ApplicationId) -> _Session:
        session = self._sessions.get(str(application_id))
        if session is None:
            raise KeyError(f"no open page for application {application_id}; call open() first")
        return session

    def _state(self, session: _Session) -> PageState:
        page = session.page
        return PageState(
            url=page.url,
            fields=page.fields,
            screenshot_ref=None,
            detection_signals=page.detection_signals,
        )
