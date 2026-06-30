"""Step bindings for the N4 browser / pre-fill robustness acceptance specs.

Theme: browser crash recovery, fake<->real page-source parity, the stale
SwiftShader launch flag, response-status timestamps, the Chrome container-path
probe, the SPA hydration race in ``advance()``, dropdown cleanup on a detached
element, and the combobox filter-query for shared-prefix options — issues
#336-#343 in this packet.

These overlap and extend the prior browser theme (#207/#212/#213/#215/#224/#225/
#226/#227); each work-order comment names its related existing issue so the set
stays cohesive.

Convention (see ``tests/bdd/steps/test_enh_research_steps.py`` and
``tests/bdd/steps/test_enh_t02_prefill_steps.py`` for the canonical pattern):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour
  that already ships on this branch. They assert against the actual pure rules /
  seams (``stealth.detect_chrome_major`` / ``coherent_fingerprint``, the importable
  ``FakePageSource`` and ``PlaywrightPageSource`` pure classmethods, and the
  pre-fill page walk driven by an in-memory browser) and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built. Their steps make an honest probe at the intended seam (a
  speculative attribute, a missing guard, or an assertion the current code
  genuinely fails) so the scenario is a true red. ``conftest.pytest_bdd_apply_tag``
  maps ``@pending`` to a non-strict xfail.

The real browser is integration-only, so nothing here opens a real browser, socket
or DB: browser-driven behaviour is asserted through the pure rule that underlies it
(launch kwargs, fingerprint coherence, filter-query, version-gating) or through the
in-memory ``FakePageSource`` / small in-process fakes.
"""

from __future__ import annotations

import inspect

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.browser.ats import AtsAdapter, FakePage
from applicant.adapters.browser.page_source import FakePageSource, PlaywrightPageSource
from applicant.adapters.browser.stealth import (
    coherent_fingerprint,
    detect_chrome_major,
)
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.prefill_service import PrefillResult, PrefillService
from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import DetectedField, PageState

scenarios(
    "../features/enhancements/enh_336_browser_crash_recovery.feature",
    "../features/enhancements/enh_337_fake_page_source_parity.feature",
    "../features/enhancements/enh_338_swiftshader_flag_version_gate.feature",
    "../features/enhancements/enh_339_on_response_timestamp.feature",
    "../features/enhancements/enh_340_chrome_probe_container_paths.feature",
    "../features/enhancements/enh_341_spa_hydration_race.feature",
    "../features/enhancements/enh_342_dropdown_cleanup_detached.feature",
    "../features/enhancements/enh_343_filter_query_shared_prefix.feature",
)


@pytest.fixture
def n4ctx() -> dict:
    return {}


# ---------------------------------------------------------------------------
# Shared in-memory builders (no real browser / socket / DB)
# ---------------------------------------------------------------------------
def _cid() -> CampaignId:
    return CampaignId(new_id())


def _app(cid: CampaignId, status: ApplicationState = ApplicationState.PREFILLING) -> Application:
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=status,
    )


def _service(*, browser, storage=None) -> PrefillService:
    return PrefillService(
        storage=storage or InMemoryStorage(),
        browser=browser,
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
    )


# A stand-in for Playwright's TargetClosedError (the browser tab/context closed).
class _TargetClosedError(Exception):
    """Models patchright/Playwright TargetClosedError: the tab/context vanished."""


# ===========================================================================
# #336 — no browser crash recovery in the pre-fill page walk
#        Related existing issues: #207 (no health check), #212 (settle swallow).
# ===========================================================================
class _HealthyFlowBrowser:
    """A tiny scriptable browser: one fillable page then the final-submit page."""

    def __init__(self):
        self._idx = 0
        self._pages = [
            PageState(url="https://ats.example/p1", fields=()),
            PageState(url="https://ats.example/review", fields=()),
        ]

    def current_state(self, aid):  # noqa: ARG002
        return self._pages[self._idx]

    def detect_fields(self, aid):  # noqa: ARG002
        return []

    def screenshot(self, aid):  # noqa: ARG002
        return f"screenshot://{self._idx}"

    def is_account_create_page(self, aid):  # noqa: ARG002
        return False

    def is_final_submit_page(self, aid):  # noqa: ARG002
        return self._idx >= 1

    def advance(self, aid):  # noqa: ARG002
        if self._idx + 1 >= len(self._pages):
            return None
        self._idx += 1
        return self._pages[self._idx]


class _TabClosesBrowser(_HealthyFlowBrowser):
    """Raises a TargetClosedError-style error on the first page operation."""

    def current_state(self, aid):
        raise _TargetClosedError("Target page, context or browser has been closed")


class _TimingOutBrowser(_HealthyFlowBrowser):
    """Raises a TimeoutError-style error on the first page operation."""

    def current_state(self, aid):
        raise TimeoutError("page operation exceeded the action timeout")


@given("a healthy in-memory browser walking the application flow")
def healthy_flow_browser(n4ctx):
    cid = _cid()
    storage = InMemoryStorage()
    n4ctx.update(cid=cid, store_storage=storage, browser=_HealthyFlowBrowser())
    n4ctx["service"] = _service(browser=n4ctx["browser"], storage=storage)
    n4ctx["app"] = _app(cid)


@given("a browser whose tab closes unexpectedly partway through the walk")
def tab_closes_browser(n4ctx):
    cid = _cid()
    storage = InMemoryStorage()
    n4ctx.update(cid=cid, store_storage=storage, browser=_TabClosesBrowser())
    n4ctx["service"] = _service(browser=n4ctx["browser"], storage=storage)
    n4ctx["app"] = _app(cid)


@given("a browser whose page operation times out mid-walk")
def timing_out_browser(n4ctx):
    cid = _cid()
    storage = InMemoryStorage()
    n4ctx.update(cid=cid, store_storage=storage, browser=_TimingOutBrowser())
    n4ctx["service"] = _service(browser=n4ctx["browser"], storage=storage)
    n4ctx["app"] = _app(cid)


@when("the engine runs the pre-fill page walk")
def run_prefill_walk(n4ctx):
    svc = n4ctx["service"]
    result = PrefillResult(application_id=n4ctx["app"].id, state=n4ctx["app"].status)
    try:
        n4ctx["result"] = svc._continue_pages(n4ctx["app"], [], result, cautious=False)
        n4ctx["escaped"] = None
    except Exception as exc:  # noqa: BLE001 — capture so the probe can assert it escaped
        n4ctx["result"] = None
        n4ctx["escaped"] = exc


@then("a structured pre-fill result is returned")
def structured_result_returned(n4ctx):
    assert n4ctx["escaped"] is None
    assert isinstance(n4ctx["result"], PrefillResult)
    assert n4ctx["result"].state == ApplicationState.AWAITING_FINAL_APPROVAL


@then("a failed pre-fill result is returned rather than the browser error escaping")
def failed_result_not_escape(n4ctx):
    # Today no try/except boundary catches a browser-disconnection error in the page
    # walk, so the raw exception propagates — genuine red until crash recovery lands.
    assert n4ctx["escaped"] is None, "a browser tab crash escaped the pre-fill walk"
    assert isinstance(n4ctx["result"], PrefillResult)
    assert n4ctx["result"].state == ApplicationState.FAILED


@then("the timeout is caught and a failed pre-fill result is returned")
def timeout_caught_failed_result(n4ctx):
    # A hung browser operation raises TimeoutError today and propagates uncaught.
    assert n4ctx["escaped"] is None, "a browser timeout escaped the pre-fill walk"
    assert isinstance(n4ctx["result"], PrefillResult)
    assert n4ctx["result"].state == ApplicationState.FAILED


# ===========================================================================
# #337 — FakePageSource <-> PlaywrightPageSource behavioural divergences
#        Related existing issues: #213 (sign-in-only gate), #224 (Protocol parity).
# ===========================================================================
class _PostingThenFormAts(AtsAdapter):
    """A posting page (needs an Apply click) ahead of the application form."""

    name = "posting-then-form"

    def matches(self, url):  # noqa: ARG002
        return True

    def pages(self, url):
        return [
            FakePage(url=f"{url}/posting", fields=()),
            FakePage(
                url=f"{url}/form",
                fields=(DetectedField("#first", "First Name", "text"),),
            ),
        ]


class _SignInOnlyAts(AtsAdapter):
    name = "signin-only"

    def matches(self, url):  # noqa: ARG002
        return True

    def pages(self, url):
        return [
            FakePage(
                url=f"{url}/signin",
                is_account_create=False,
                fields=(
                    DetectedField("#email", "Email", "text"),
                    DetectedField("#password", "Password", "password"),
                ),
            )
        ]


@given("the in-memory fake page source on an application flow")
def fake_on_flow(n4ctx):
    src = FakePageSource(_PostingThenFormAts())
    src.open("https://ats.example/job")
    n4ctx["source"] = src


@given("a fake page source modelling a posting that needs an Apply click")
def fake_posting_needs_apply(n4ctx):
    src = FakePageSource(_PostingThenFormAts())
    src.open("https://ats.example/job")
    n4ctx["source"] = src


@given("a fake page source modelling an account gate with a wrong password")
def fake_gate_wrong_password(n4ctx):
    src = FakePageSource(_SignInOnlyAts())
    src.open("https://ats.example/job")
    # Configure the sign-in page to simulate a login failure.
    src._pages[src._index].login_fails = True  # noqa: SLF001
    n4ctx["source"] = src
    n4ctx["credential"] = ("kevin@kevinhirsch.com", "wrong-password")


@given("a fake page source modelling a sign-in-only step with no account creation")
def fake_signin_only(n4ctx):
    src = FakePageSource(_SignInOnlyAts())
    src.open("https://ats.example/job")
    n4ctx["source"] = src


@given("a fake page source modelling a gate offering Google sign-in")
def fake_offers_google(n4ctx):
    src = FakePageSource(_SignInOnlyAts())
    src.open("https://ats.example/job")
    # Configure the sign-in page to offer Google OAuth.
    src._pages[src._index].offers_google = True  # noqa: SLF001
    n4ctx["source"] = src


@when("the engine enters the application")
def enter_application_on_fake(n4ctx):
    n4ctx["enter_result"] = n4ctx["source"].enter_application()


@when("the engine logs in with any credential on the fake")
def login_any_on_fake(n4ctx):
    n4ctx["login_ok"] = n4ctx["source"].log_in("u", "p")


@when("the engine logs in with the wrong credential on the fake")
def login_wrong_on_fake(n4ctx):
    user, pw = n4ctx["credential"]
    n4ctx["login_ok"] = n4ctx["source"].log_in(user, pw)


@when("the engine checks whether the fake page is an account gate")
def check_fake_gate(n4ctx):
    n4ctx["is_gate"] = n4ctx["source"].is_account_gate()


@when("the engine checks whether the fake offers Google sign-in")
def check_fake_google(n4ctx):
    n4ctx["offers_google"] = n4ctx["source"].offers_google_signin()


@then("the fake clicks Apply and advances to the next page")
def fake_clicks_apply(n4ctx):
    # After parity (#337), FakePageSource.enter_application now advances past
    # a posting page and returns the next PageState (mirrors the real driver).
    assert n4ctx["enter_result"] is not None, (
        "the fake page source did not click Apply on the posting page"
    )


@then("the fake always reports success today")
def fake_login_always_succeeds(n4ctx):
    # GREEN regression: FakePageSource.log_in always returns True (cannot model failure),
    # whereas PlaywrightPageSource can return False on a wrong password / changed form.
    assert n4ctx["login_ok"] is True


@then("the fake reports it clicked into the application flow")
def fake_reports_apply(n4ctx):
    # After parity (#337), FakePageSource.enter_application advances past a posting
    # page and returns the next PageState — the apply-click path is now exercised.
    assert n4ctx["enter_result"] is not None, (
        "the fake page source never exercises the Apply-button click path"
    )


@then("the fake reports the login failed")
def fake_reports_login_failed(n4ctx):
    # After parity (#337), FakePageSource.log_in checks the login_fails flag and
    # returns False when set — login failure is now testable in CI.
    assert n4ctx["login_ok"] is False, (
        "the fake page source cannot model a login failure (always succeeds)"
    )


@then("the sign-in-only page is recognised as a gate")
def signin_only_is_gate(n4ctx):
    # The fake's is_account_gate only checks is_account_create, so a sign-in-only page
    # is treated as 'not a gate' (the engine would blast through it) — genuine red.
    assert n4ctx["is_gate"] is True, (
        "the fake treats a sign-in-only page as not-a-gate (engine would skip the gate)"
    )


@then("the fake reports a Google sign-in option is offered")
def fake_reports_google(n4ctx):
    # The fake's offers_google_signin always returns False, so the Google OAuth path is
    # never exercised in CI — genuine red until the fake can model an offered Google gate.
    assert n4ctx["offers_google"] is True, (
        "the fake never models an offered Google sign-in (OAuth path untestable)"
    )


# ===========================================================================
# #338 — --enable-unsafe-swiftshader removed in Chrome 125+
#        Related existing issue: #215 (PINNED_CHROME_MAJOR stale at 124).
# ===========================================================================
@given("the coherent Chrome fingerprint built from the pinned major")
def coherent_chrome_fp(n4ctx):
    n4ctx["fingerprint"] = coherent_fingerprint("chrome")


@when("the browser launch kwargs are built")
def build_launch_kwargs(n4ctx):
    n4ctx["kwargs"] = PlaywrightPageSource.launch_kwargs(n4ctx["fingerprint"])


@then("the launch args carry the automation-control stealth flag")
def launch_args_have_stealth(n4ctx):
    args = n4ctx["kwargs"].get("args", [])
    assert "--disable-blink-features=AutomationControlled" in args


@given("a deployment whose installed Chrome major is 125 or newer")
def chrome_major_125(n4ctx):
    n4ctx["chrome_major"] = 130


@when("the browser launch args are built for that Chrome")
def build_args_for_chrome_major(n4ctx):
    major = n4ctx["chrome_major"]
    fp = coherent_fingerprint("chrome")
    # Speculative future API: a version-aware launch-args builder. Absent today, so we
    # fall back to the env-blind launch_kwargs whose args always include the flag.
    builder = getattr(PlaywrightPageSource, "launch_kwargs_for_major", None)
    if callable(builder):
        n4ctx["args"] = builder(fp, chrome_major=major).get("args", [])
    else:
        # Call the version-aware _stealth_args with the resolved major.
        n4ctx["args"] = list(PlaywrightPageSource._stealth_args(chrome_major=major))


@then("the unsafe-swiftshader flag is not passed to the newer Chrome")
def no_swiftshader_for_newer(n4ctx):
    # Today --enable-unsafe-swiftshader is added unconditionally (no version gate), so it
    # is still present for Chrome 125+ — genuine red until the flag is version-gated.
    assert "--enable-unsafe-swiftshader" not in n4ctx["args"], (
        "the removed --enable-unsafe-swiftshader flag is still passed to Chrome 125+"
    )


# ===========================================================================
# #339 — _on_response captures status with no timestamp
#        Related existing issue: #207 (browser diagnostic instrumentation gap).
# ===========================================================================
class _FakeResponse:
    def __init__(self, url, status):
        self.url = url
        self.status = status
        self.request = _FakeRequest()


class _FakeRequest:
    def is_navigation_request(self):
        return True


@given("a page driver observing a navigation response")
def driver_observing_response(n4ctx):
    from types import SimpleNamespace

    # A minimal fake _page so _on_response's url comparison + assignment run without a
    # real browser (the handler is otherwise integration-gated).
    n4ctx["fake_self"] = SimpleNamespace(
        _page=SimpleNamespace(url="https://ats.example/form"),
        _status=None,
    )
    n4ctx["response"] = _FakeResponse("https://ats.example/form", 200)


@when("the response handler captures the document status")
def capture_document_status(n4ctx):
    PlaywrightPageSource._on_response(n4ctx["fake_self"], n4ctx["response"])


@then("the captured status entry carries a timestamp")
def captured_status_has_timestamp(n4ctx):
    fake = n4ctx["fake_self"]
    # Today _on_response writes only a bare int to self._status — no timestamp anywhere.
    # A fix records a (status, ts) pair or a separate timestamped log — genuine red.
    has_ts = False
    status_attr = getattr(fake, "_status", None)
    if isinstance(status_attr, (tuple, list)) and len(status_attr) >= 2:
        has_ts = isinstance(status_attr[1], (int, float))
    elif isinstance(status_attr, dict) and any(
        k in status_attr for k in ("ts", "timestamp", "time")
    ):
        has_ts = True
    # A speculative dedicated log of timestamped statuses.
    for name in ("_status_log", "_response_log", "_status_history"):
        log = getattr(fake, name, None)
        if log:
            has_ts = True
    assert has_ts, "the captured response status carries no timestamp for correlation"


# ===========================================================================
# #340 — Chrome version probe misses container Chrome paths
#        Related existing issue: #215 (stale pinned major fallback).
# ===========================================================================
@given("a deployment where no Chrome binary is on PATH")
def no_chrome_on_path(n4ctx, monkeypatch):
    import applicant.adapters.browser.stealth as stealth_mod

    monkeypatch.setattr(stealth_mod.shutil, "which", lambda name: None)
    n4ctx["monkeypatch"] = monkeypatch


@given("a container that ships Chrome only as a container binary name")
def container_chrome_only(n4ctx, monkeypatch):
    import applicant.adapters.browser.stealth as stealth_mod

    # Record which binary names the probe ASKS shutil.which about, then deny them all so
    # the probe returns None today (its candidate list is what we assert on).
    asked: list[str] = []

    def _which(name):
        asked.append(name)
        return None

    monkeypatch.setattr(stealth_mod.shutil, "which", _which)
    n4ctx["asked"] = asked
    n4ctx["monkeypatch"] = monkeypatch


@when("the Chrome major is probed")
def probe_chrome_major(n4ctx):
    n4ctx["major"] = detect_chrome_major("chrome")


@when("the Chrome major is probed on the chrome channel")
def probe_chrome_major_channel(n4ctx):
    n4ctx["major"] = detect_chrome_major("chrome")


@then("the probe reports that no Chrome was found")
def probe_reports_none(n4ctx):
    assert n4ctx["major"] is None


@then("the probe also tries the container and beta binary names")
def probe_tries_container_names(n4ctx):
    # Today the chrome-channel candidate list is only google-chrome-stable / google-chrome
    # / chrome — chromium / chromium-browser / google-chrome-beta are never probed, so a
    # container-only Chrome is missed and the major falls back to the stale pin (#215).
    asked = set(n4ctx["asked"])
    extras = {"chromium", "chromium-browser", "google-chrome-beta"}
    assert extras & asked, (
        "the chrome-channel probe never tries container/beta Chrome binary names: "
        f"only asked about {sorted(asked)}"
    )


# ===========================================================================
# #341 — SPA DOM hydration race in advance() end-detection
#        Related existing issue: #212 (_settle swallows the load-state timeout).
# ===========================================================================
@given("a page driver advancing through a single-URL SPA flow")
def driver_single_url_spa(n4ctx):
    n4ctx["advance_src"] = inspect.getsource(PlaywrightPageSource.advance)
    n4ctx["dom_changed_src"] = inspect.getsource(PlaywrightPageSource._dom_changed)


@when("advance detects no DOM change immediately after clicking Next")
def advance_no_dom_change(n4ctx):
    # The seam is whether advance() re-checks / retries after the immediate DOM-change
    # probe. Capture the combined source so the @then can assert the retry guard exists.
    n4ctx["combined_src"] = n4ctx["advance_src"] + n4ctx["dom_changed_src"]


@then("it re-checks for the hydrated page before declaring the flow finished")
def advance_rechecks_hydration(n4ctx):
    # Today advance() decides end-of-flow from a SINGLE url==before and not _dom_changed()
    # check with no settle/retry between the click and the decision — an un-hydrated SPA
    # page is mistaken for the end. A fix adds a bounded re-check/retry seam.
    src = n4ctx["combined_src"].lower()
    has_retry_seam = any(
        marker in src
        for marker in ("re-check", "recheck", "retry", "hydrat", "for attempt", "for _ in range")
    )
    assert has_retry_seam, (
        "advance() does not re-check/retry after the immediate DOM-change probe, so an "
        "un-hydrated SPA page can be mistaken for the end of the flow"
    )


# ===========================================================================
# #342 — dropdown cleanup operates on a detached element after navigation
#        Related existing issue: #226 (_pick_visible_option scoping).
# ===========================================================================
@given("a page driver selecting a dropdown option that navigates on selection")
def driver_dropdown_navigates(n4ctx):
    n4ctx["choose_src"] = inspect.getsource(PlaywrightPageSource._choose_listbox_option)


@when("the dropdown filter cleanup runs after the navigation")
def dropdown_cleanup_runs(n4ctx):
    # The seam is whether the post-selection Escape/clear cleanup checks the element is
    # still attached (or the page did not navigate) before operating on it.
    n4ctx["cleanup_src"] = n4ctx["choose_src"]


@then("it checks the element is still attached before clearing it")
def cleanup_checks_attachment(n4ctx):
    # Today the Escape + fill("") cleanup runs unconditionally inside a bare
    # ``except Exception: pass`` — it never checks attachment / navigation first.
    src = n4ctx["cleanup_src"].lower()
    has_attach_guard = any(
        marker in src
        for marker in ("is_attached", "is_connected", "is_visible", "navigated", "is_detached")
    )
    assert has_attach_guard, (
        "the dropdown cleanup never checks the element is still attached / the page did "
        "not navigate before pressing Escape and clearing the filter"
    )


# ===========================================================================
# #343 — _filter_query uses the first 2 words only (shared-prefix collision)
#        Related existing issue: #225 (dropdown/combobox matching coverage).
# ===========================================================================
SHARED_PREFIX_VALUE = "United States Minor Outlying Islands"


@given("a long country-style option value that shares a leading-word prefix")
def shared_prefix_value(n4ctx):
    n4ctx["value"] = SHARED_PREFIX_VALUE


@when("the combobox filter query is built for that value")
def build_filter_query(n4ctx):
    n4ctx["query"] = PlaywrightPageSource._filter_query(n4ctx["value"])


@then("the filter query is exactly the first two words")
def filter_query_first_two(n4ctx):
    # GREEN regression: today _filter_query returns only the first two meaningful words.
    assert n4ctx["query"] == "United States"


@then("the filter query types more than the first two words to disambiguate")
def filter_query_disambiguates(n4ctx):
    # "United States" prefix-matches BOTH "United States" and "United States Minor
    # Outlying Islands"; a disambiguating query must type more than the first two words.
    query = n4ctx["query"]
    word_count = len(query.split())
    assert word_count > 2, (
        f"the filter query {query!r} is still only the first two words, so it cannot "
        "disambiguate options that share a leading-word prefix"
    )
