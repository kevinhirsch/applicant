"""Step bindings for the pre-fill browser-robustness acceptance specs (T02).

Theme: credential lookup/capture, field-fill error handling, sensitive-field
detection, browser health, session lifecycle, LLM escalation, profile races, and
attribute-priority — issues #202-#224 in this packet.

Convention (see ``tests/bdd/steps/test_enh_research_steps.py`` for the canonical
pattern):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour
  that already ships on this branch. They assert against the actual core rules /
  application services through in-memory adapters and fakes — never a real browser,
  socket, or DB — and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built. Their steps make an honest probe at the intended seam (a
  speculative import, a missing method/attribute, or an assertion the current code
  genuinely fails) so the scenario is a true red. ``conftest.pytest_bdd_apply_tag``
  maps ``@pending`` to a non-strict xfail.

The pre-fill browser is integration-only, so browser-driven behaviour is asserted
either through the pure core rule that underlies it (sensitive-field classification,
attribute lookup, fingerprint coherence) or through the in-memory ``FakePageSource``
and small in-process fakes — no real browser is ever opened.
"""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.browser.ats import AtsAdapter, FakePage
from applicant.adapters.browser.page_source import FakePageSource
from applicant.adapters.browser.stealth import (
    ProfileStore,
    coherent_fingerprint,
    detect_chrome_major,
    fingerprint_is_coherent,
)
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.prefill_service import (
    GOOGLE_CREDENTIAL_KEY,
    PrefillResult,
    PrefillService,
)
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    JobPostingId,
    new_id,
)
from applicant.core.rules.sensitive_fields import is_sensitive_field
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import DetectedField, PageState

scenarios(
    "../features/enhancements/enh_202_credential_tenant_lookup_failure.feature",
    "../features/enhancements/enh_203_credential_scope_retrieve_failure.feature",
    "../features/enhancements/enh_204_capture_credential_silent_loss.feature",
    "../features/enhancements/enh_205_fill_field_audit_trail.feature",
    "../features/enhancements/enh_206_sensitive_attribute_flag.feature",
    "../features/enhancements/enh_207_browser_health_check.feature",
    "../features/enhancements/enh_208_current_state_none_guard.feature",
    "../features/enhancements/enh_210_attribute_match_priority.feature",
    "../features/enhancements/enh_211_llm_unavailable_diagnostic.feature",
    "../features/enhancements/enh_212_settle_timeout_empty_dom.feature",
    "../features/enhancements/enh_213_account_gate_signin_only.feature",
    "../features/enhancements/enh_215_chrome_major_override.feature",
    "../features/enhancements/enh_216_profile_visit_count_race.feature",
    "../features/enhancements/enh_217_browser_session_dispose.feature",
    "../features/enhancements/enh_222_escalation_prompt_redacts_sensitive.feature",
    "../features/enhancements/enh_223_login_error_vs_wrong_password.feature",
    "../features/enhancements/enh_224_page_source_submit_account_protocol.feature",
)


@pytest.fixture
def t02ctx() -> dict:
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


def _attr(cid: CampaignId, name: str, value: str, *, sensitive: bool = False) -> Attribute:
    return Attribute(
        id=AttributeId(new_id()),
        campaign_id=cid,
        name=name,
        value=value,
        is_sensitive=sensitive,
    )


def _service(*, browser, credentials=None, llm=None, storage=None) -> PrefillService:
    return PrefillService(
        storage=storage or InMemoryStorage(),
        browser=browser,
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=credentials,
        llm=llm,
    )


class _SingleFieldBrowser:
    """Minimal browser stub exposing a fixed field list for ``_fill_current_page``."""

    def __init__(self, fields, *, fail_selectors=()):
        self._fields = list(fields)
        self._fail = set(fail_selectors)
        self.filled: dict[str, str] = {}

    def current_state(self, aid):  # noqa: ARG002
        return PageState(url="https://ats.example/form", fields=())

    def detect_fields(self, aid):  # noqa: ARG002
        return list(self._fields)

    def fill_field(self, aid, selector, value):  # noqa: ARG002
        if selector in self._fail:
            raise RuntimeError("element detached")
        self.filled[selector] = value


# ===========================================================================
# #202 — _lookup_credential swallows tenant_of() failures
# ===========================================================================
class _RaisingTenantBrowser:
    def tenant_key(self, aid):  # noqa: ARG002
        raise RuntimeError("browser crashed mid-call")


@given("a credential lookup whose tenant resolver crashes mid-call")
def credential_tenant_crashes(t02ctx):
    d = tempfile.mkdtemp()
    from applicant.adapters.credentials.pg_credential_store import InMemoryCredentialStore

    t02ctx["cid"] = _cid()
    t02ctx["store"] = InMemoryCredentialStore(f"{d}/master.key")
    t02ctx["service"] = _service(
        browser=_RaisingTenantBrowser(), credentials=t02ctx["store"]
    )
    t02ctx["app"] = _app(t02ctx["cid"], ApplicationState.ACCOUNT_PREFILL)


@when("the engine looks up a stored credential")
def lookup_stored_credential(t02ctx):
    svc = t02ctx["service"]
    try:
        t02ctx["credential"] = svc._lookup_credential(t02ctx["app"])
        t02ctx["crashed"] = False
    except Exception as exc:  # noqa: BLE001 — record so the assertion can check graceful degradation
        t02ctx["crashed"] = True
        t02ctx["error"] = exc


@then("no credential is returned and the loop does not crash")
def no_credential_no_crash(t02ctx):
    assert t02ctx["crashed"] is False
    assert t02ctx["credential"] is None


@then("a diagnostic event records that the tenant lookup failed")
def tenant_failure_diagnostic(t02ctx):
    # Today the failure is swallowed silently (no event / log / notification). A fix
    # surfaces a diagnostic the operator can see — genuine red until it lands.
    events = _collected_diagnostics(t02ctx)
    assert any("tenant" in str(e).lower() for e in events), (
        "no diagnostic surfaced for a crashed tenant lookup"
    )


def _collected_diagnostics(t02ctx) -> list:
    """Diagnostics the prefill service would surface for a credential/LLM failure.

    Today there is no such channel, so this returns an empty list and the @pending
    assertions fail honestly. When the diagnostic seam lands (a method, a pending
    'error'/'diagnostic' action, or a structured event), this resolver finds it.
    """
    svc = t02ctx.get("service")
    out: list = []
    diag = getattr(svc, "diagnostics", None)
    if callable(diag):
        try:
            out.extend(list(diag()))  # speculative future API
        except Exception:  # noqa: BLE001
            pass
    storage = t02ctx.get("store_storage") or getattr(svc, "_storage", None)
    cid = t02ctx.get("cid")
    if storage is not None and cid is not None:
        try:
            for p in storage.pending_actions.list_open(cid):
                if p.kind in ("diagnostic", "credential_error", "llm_unavailable"):
                    out.append(p.title)
        except Exception:  # noqa: BLE001
            pass
    return out


# ===========================================================================
# #203 — per-scope retrieve() exceptions silently skip ALL scopes
# ===========================================================================
class _OkTenantBrowser:
    def __init__(self, tenant_key="workday:acme.example"):
        self._tk = tenant_key

    def tenant_key(self, aid):  # noqa: ARG002
        return self._tk


class _FirstScopeFailsStore:
    """Raises for the first scope queried, then serves a credential for the rest."""

    def __init__(self, credential):
        self._credential = credential
        self._calls = 0

    def retrieve(self, scope, tenant_key):  # noqa: ARG002
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("transient vault timeout")
        return self._credential


class _AllScopesFailStore:
    def retrieve(self, scope, tenant_key):  # noqa: ARG002
        raise RuntimeError("vault unreachable")


@given("a credential vault that fails the first scope but holds a shared credential")
def vault_first_scope_fails(t02ctx):
    from applicant.adapters.credentials.pg_credential_store import Credential

    cred = Credential(tenant_key=GOOGLE_CREDENTIAL_KEY, username="kevin@kevinhirsch.com", secret="s")
    t02ctx["cid"] = _cid()
    t02ctx["service"] = _service(
        browser=_OkTenantBrowser(), credentials=_FirstScopeFailsStore(cred)
    )
    t02ctx["app"] = _app(t02ctx["cid"], ApplicationState.ACCOUNT_PREFILL)
    t02ctx["expected_cred"] = cred


@when("the engine looks up a shared credential across scopes")
def lookup_shared_credential(t02ctx):
    svc = t02ctx["service"]
    t02ctx["credential"] = svc._lookup_credential(t02ctx["app"], tenant_key=GOOGLE_CREDENTIAL_KEY)


@then("the working scope's credential is still returned")
def working_scope_returned(t02ctx):
    assert t02ctx["credential"] is not None
    assert t02ctx["credential"].username == t02ctx["expected_cred"].username


@given("a credential vault that raises for every scope")
def vault_all_scopes_fail(t02ctx):
    t02ctx["cid"] = _cid()
    t02ctx["service"] = _service(browser=_OkTenantBrowser(), credentials=_AllScopesFailStore())
    t02ctx["app"] = _app(t02ctx["cid"], ApplicationState.ACCOUNT_PREFILL)


@when("the engine looks up a stored credential across scopes")
def lookup_credential_all_scopes(t02ctx):
    svc = t02ctx["service"]
    t02ctx["credential"] = svc._lookup_credential(t02ctx["app"], tenant_key=GOOGLE_CREDENTIAL_KEY)


@then("a diagnostic event records that every credential scope failed")
def all_scopes_failure_diagnostic(t02ctx):
    events = _collected_diagnostics(t02ctx)
    assert any("scope" in str(e).lower() or "vault" in str(e).lower() for e in events), (
        "no diagnostic surfaced after every credential scope failed"
    )


# ===========================================================================
# #204 — _capture_credential silent data loss
# ===========================================================================
class _CaptureFailsStore:
    def capture(self, campaign_id, tenant_key, username, secret):  # noqa: ARG002
        raise RuntimeError("vault write failed")


@given("a newly created account with a generated password")
def new_account_credential(t02ctx):
    from applicant.adapters.credentials.pg_credential_store import InMemoryCredentialStore

    d = tempfile.mkdtemp()
    t02ctx["cid"] = _cid()
    t02ctx["store"] = InMemoryCredentialStore(f"{d}/master.key")
    t02ctx["service"] = _service(browser=_OkTenantBrowser(), credentials=t02ctx["store"])
    t02ctx["app"] = _app(t02ctx["cid"], ApplicationState.ACCOUNT_PREFILL)
    t02ctx["username"] = "kevin@kevinhirsch.com"
    t02ctx["password"] = "generated-strong-pw"


@when("the engine banks the captured credential")
def bank_captured_credential(t02ctx):
    svc = t02ctx["service"]
    svc._capture_credential(t02ctx["app"], t02ctx["username"], t02ctx["password"])


@then("the credential is retrievable for future applications at that tenant")
def credential_retrievable(t02ctx):
    cred = t02ctx["store"].retrieve(t02ctx["app"].campaign_id, "workday:acme.example")
    assert cred is not None
    assert cred.username == t02ctx["username"]
    assert cred.secret == t02ctx["password"]


@given("a credential vault that raises while banking a new account credential")
def vault_capture_raises(t02ctx):
    t02ctx["cid"] = _cid()
    storage = InMemoryStorage()
    t02ctx["store_storage"] = storage
    t02ctx["service"] = _service(
        browser=_OkTenantBrowser(), credentials=_CaptureFailsStore(), storage=storage
    )
    t02ctx["app"] = _app(t02ctx["cid"], ApplicationState.ACCOUNT_PREFILL)


@when("the engine tries to bank the captured credential")
def try_bank_captured_credential(t02ctx):
    svc = t02ctx["service"]
    # Today the failure is swallowed with a bare ``pass`` (it does not crash).
    svc._capture_credential(t02ctx["app"], "kevin@kevinhirsch.com", "lost-pw")


@then("a recovery pending action records the lost credential for the operator")
def recovery_action_recorded(t02ctx):
    storage = t02ctx["store_storage"]
    actions = storage.pending_actions.list_open(t02ctx["cid"])
    # No recovery action is created on a failed capture today — genuine red.
    assert any(
        a.kind in ("credential_recovery", "error", "diagnostic")
        and "credential" in (a.title or "").lower()
        for a in actions
    ), "a failed credential capture left no recovery action"


# ===========================================================================
# #205 — _fill_field exception skips the page-log audit trail
# ===========================================================================
@given("a page where one field fill raises an error")
def page_one_fill_fails(t02ctx):
    cid = _cid()
    fields = [
        DetectedField("#first", "First Name", "text"),
        DetectedField("#last", "Last Name", "text"),
    ]
    storage = InMemoryStorage()
    t02ctx.update(
        cid=cid,
        store_storage=storage,
        browser=_SingleFieldBrowser(fields, fail_selectors={"#first"}),
        attributes=[_attr(cid, "First Name", "Kevin"), _attr(cid, "Last Name", "Hirsch")],
        app=_app(cid),
    )
    t02ctx["service"] = _service(browser=t02ctx["browser"], storage=storage)


@given("a page where a sensitive field fill raises an error")
def page_sensitive_fill_fails(t02ctx):
    cid = _cid()
    # A recognised sensitive label (Gender) whose fill raises.
    fields = [DetectedField("#gender", "Gender", "select", options=("Female", "Male"))]
    storage = InMemoryStorage()
    t02ctx.update(
        cid=cid,
        store_storage=storage,
        browser=_SingleFieldBrowser(fields, fail_selectors={"#gender"}),
        attributes=[_attr(cid, "Gender", "Female", sensitive=True)],
        app=_app(cid),
    )
    t02ctx["service"] = _service(browser=t02ctx["browser"], storage=storage)


@when("the engine fills the page")
def fill_the_page(t02ctx):
    svc = t02ctx["service"]
    result = PrefillResult(application_id=t02ctx["app"].id, state=t02ctx["app"].status)
    t02ctx["block"] = svc._fill_current_page(t02ctx["app"], t02ctx["attributes"], result)
    t02ctx["result"] = result


@then("an error pending action names the failed field and the run continues")
def error_action_and_continue(t02ctx):
    assert t02ctx["block"] is None  # the loop did not crash / hard-block
    actions = t02ctx["store_storage"].pending_actions.list_open(t02ctx["cid"])
    errors = [a for a in actions if a.kind == "error"]
    assert errors, "fill failure produced no error pending action"
    assert any(a.payload.get("field_selector") == "#first" for a in errors)
    # The other (good) field was still filled.
    assert t02ctx["browser"].filled.get("#last") == "Hirsch"


@then("the failed field is recorded in the page log audit trail")
def failed_field_in_page_log(t02ctx):
    # Today the handler ``continue``s before page_log/result updates, so the failed
    # sensitive field appears NOWHERE in the result — genuine red.
    result = t02ctx["result"]
    in_page_log = any("#gender" in page for page in result.filled_by_page.values())
    in_sensitive = (
        "#gender" in result.sensitive_filled_from_explicit
        or "#gender" in result.sensitive_declined
    )
    assert in_page_log or in_sensitive, (
        "a failed sensitive field left no audit-trail entry in the result"
    )


# ===========================================================================
# #206 — sensitive gate keys on label, not attribute.is_sensitive
# ===========================================================================
@given("a form field whose label is a recognised demographic field")
def recognised_demographic_label(t02ctx):
    t02ctx["label"] = "Gender"


@when("the sensitive-field rule classifies the label")
def classify_label(t02ctx):
    t02ctx["is_sensitive"] = is_sensitive_field(t02ctx["label"])


@then("the field is treated as sensitive")
def field_treated_sensitive(t02ctx):
    assert t02ctx["is_sensitive"] is True


@given("an attribute marked sensitive whose label the substring matcher misses")
def sensitive_attr_unrecognised_label(t02ctx):
    cid = _cid()
    # "Caste" is a protected/demographic attribute the substring markers do not cover.
    label = "Caste"
    assert is_sensitive_field(label) is False  # precondition: a false negative on the label
    t02ctx["cid"] = cid
    t02ctx["field"] = DetectedField("#caste", label, "text")
    t02ctx["attributes"] = [_attr(cid, label, "a-demographic-value", sensitive=True)]
    t02ctx["service"] = _service(browser=_SingleFieldBrowser([]))
    t02ctx["app"] = _app(cid)


@when("the engine resolves a value for that field")
def resolve_value_for_field(t02ctx):
    svc = t02ctx["service"]
    result = PrefillResult(application_id=t02ctx["app"].id, state=t02ctx["app"].status)
    t02ctx["resolved"] = svc._resolve_value(t02ctx["field"], t02ctx["attributes"], result)


@then("the value is routed through the sensitive-field policy, not the plain path")
def value_routed_sensitive(t02ctx):
    # Today _resolve_value only consults is_sensitive_field(label); the attribute's own
    # is_sensitive flag is ignored, so this flows through the plain path. Genuine red.
    assert t02ctx["resolved"].is_sensitive is True, (
        "an attribute flagged sensitive was not routed through the sensitive policy"
    )


# ===========================================================================
# #207 — no browser health check; a crash escapes the loop unhandled
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


class _CrashingFlowBrowser(_HealthyFlowBrowser):
    def current_state(self, aid):
        raise RuntimeError("browser process died")


@given("a healthy in-memory browser walking the application flow")
def healthy_flow_browser(t02ctx):
    cid = _cid()
    storage = InMemoryStorage()
    t02ctx.update(cid=cid, store_storage=storage, browser=_HealthyFlowBrowser())
    t02ctx["service"] = _service(browser=t02ctx["browser"], storage=storage)
    t02ctx["app"] = _app(cid)


@given("a browser that crashes partway through the page walk")
def crashing_flow_browser(t02ctx):
    cid = _cid()
    storage = InMemoryStorage()
    t02ctx.update(cid=cid, store_storage=storage, browser=_CrashingFlowBrowser())
    t02ctx["service"] = _service(browser=t02ctx["browser"], storage=storage)
    t02ctx["app"] = _app(cid)


@when("the engine runs the pre-fill loop")
def run_prefill_loop(t02ctx):
    svc = t02ctx["service"]
    result = PrefillResult(application_id=t02ctx["app"].id, state=t02ctx["app"].status)
    try:
        t02ctx["result"] = svc._continue_pages(
            t02ctx["app"], [], result, cautious=False
        )
        t02ctx["escaped"] = None
    except Exception as exc:  # noqa: BLE001 — capture so the @pending probe can assert it escaped
        t02ctx["result"] = None
        t02ctx["escaped"] = exc


@then("a structured pre-fill result is returned")
def structured_result_returned(t02ctx):
    assert t02ctx["escaped"] is None
    assert isinstance(t02ctx["result"], PrefillResult)
    assert t02ctx["result"].state == ApplicationState.AWAITING_FINAL_APPROVAL


@then("a failed pre-fill result is returned rather than the exception escaping")
def failed_result_not_exception(t02ctx):
    # Today the raw exception propagates (no try/except boundary) — genuine red.
    assert t02ctx["escaped"] is None, "a browser crash escaped the pre-fill loop"
    assert isinstance(t02ctx["result"], PrefillResult)
    assert t02ctx["result"].state == ApplicationState.FAILED


# ===========================================================================
# #208 — chained current_state() access crashes when the source returns None
# ===========================================================================
class _RealStateBrowser:
    def current_state(self, aid):  # noqa: ARG002
        return PageState(url="https://ats.example/here", fields=())


class _NoneStateBrowser:
    def current_state(self, aid):  # noqa: ARG002
        return None

    def detect_fields(self, aid):  # noqa: ARG002
        return []


@given("a browser whose current state is a real page snapshot")
def real_state_browser(t02ctx):
    cid = _cid()
    t02ctx["browser"] = _RealStateBrowser()
    t02ctx["service"] = _service(browser=t02ctx["browser"])
    t02ctx["app"] = _app(cid)


@when("the engine reads the current page state")
def read_current_state(t02ctx):
    state = t02ctx["browser"].current_state(t02ctx["app"].id)
    t02ctx["state"] = state


@then("the page url is available")
def page_url_available(t02ctx):
    assert t02ctx["state"].url == "https://ats.example/here"


@given("a browser whose current state returns nothing")
def none_state_browser(t02ctx):
    cid = _cid()
    t02ctx["browser"] = _NoneStateBrowser()
    t02ctx["service"] = _service(browser=t02ctx["browser"])
    t02ctx["app"] = _app(cid)


@when("the engine inspects the current page state during detection")
def inspect_state_during_detection(t02ctx):
    svc = t02ctx["service"]
    try:
        # _check_detection chains state.url / state.detection_signals — with a None
        # state this raises AttributeError today.
        t02ctx["event"] = svc._check_detection(t02ctx["app"].id)
        t02ctx["raised"] = None
    except Exception as exc:  # noqa: BLE001
        t02ctx["event"] = None
        t02ctx["raised"] = exc


@then("the engine handles the missing state rather than raising an attribute error")
def missing_state_handled(t02ctx):
    # Today this is an unguarded AttributeError — genuine red until a None guard lands.
    assert t02ctx["raised"] is None, (
        f"a None page state raised instead of being handled: {t02ctx.get('raised')!r}"
    )


# ===========================================================================
# #210 — _lookup priority: exact name > alias > loose (issue #210)
# ===========================================================================
@given("two attributes that both match a field label")
def two_matching_attributes(t02ctx):
    cid = _cid()
    # Both match the label "Phone": the first by alias, the second by exact name.
    alt = _attr(cid, "phone_alternate", "555-9999")
    object.__setattr__(alt, "aliases", ("Phone",))
    primary = _attr(cid, "Phone", "555-0001")
    t02ctx["cid"] = cid
    t02ctx["label"] = "Phone"
    t02ctx["attrs_alt_first"] = [alt, primary]
    t02ctx["attrs_primary_first"] = [primary, alt]


@when("the engine looks up a value for that label")
def lookup_value_for_label(t02ctx):
    t02ctx["value_alt_first"] = PrefillService._lookup(
        t02ctx["label"], t02ctx["attrs_alt_first"]
    )
    t02ctx["value_primary_first"] = PrefillService._lookup(
        t02ctx["label"], t02ctx["attrs_primary_first"]
    )

@then("a matching value is returned deterministically by list order")
def deterministic_by_order(t02ctx):
    # With priority tiers (exact name > alias), exact name match wins regardless of order.
    assert t02ctx["value_alt_first"] == "555-0001",
        "exact name match should beat alias match even when alt is first in list"
    assert t02ctx["value_primary_first"] == "555-0001",
        "exact name match should beat alias match when primary is first"


@given('a field labelled "Phone" with both a primary phone and an aliased alternate')
def phone_primary_and_alternate(t02ctx):
    cid = _cid()
    alt = _attr(cid, "phone_alternate", "555-9999")
    object.__setattr__(alt, "aliases", ("Phone",))
    primary = _attr(cid, "Phone", "555-0001")
    t02ctx["label"] = "Phone"
    # Order the ALTERNATE first so a naive first-match returns the wrong value.
    t02ctx["attributes"] = [alt, primary]


@then("the primary phone value wins over the alternate")
def primary_phone_wins(t02ctx):
    # An exact name match should beat a mere alias regardless of order. Today _lookup
    # returns the first by order (the alternate) — genuine red until priority lands.
    value = PrefillService._lookup(t02ctx["label"], t02ctx["attributes"])
    assert value == "555-0001", (
        f"exact name match did not win over the aliased alternate (got {value!r})"
    )


# ===========================================================================
# #211 — LLM escalation failure has no diagnostic
# ===========================================================================
class _RaisingLLM:
    def complete(self, messages, **kwargs):  # noqa: ARG002
        raise RuntimeError("rate limited / bad api key")

    def list_models(self):
        return ["model"]

    def is_configured(self):
        return True


@given("a configured LLM that raises on every mapping call")
def configured_raising_llm(t02ctx):
    cid = _cid()
    storage = InMemoryStorage()
    t02ctx.update(cid=cid, store_storage=storage, llm=_RaisingLLM())
    t02ctx["service"] = _service(browser=_SingleFieldBrowser([]), llm=t02ctx["llm"], storage=storage)
    t02ctx["field"] = DetectedField("#q", "Some ambiguous custom question label", "text")
    t02ctx["attributes"] = [_attr(cid, "current_title", "Engineer")]


@when("the engine escalates an ambiguous field to the LLM")
def escalate_ambiguous_field(t02ctx):
    svc = t02ctx["service"]
    try:
        t02ctx["mapped"] = svc._escalate_mapping(t02ctx["field"], t02ctx["attributes"])
        t02ctx["raised"] = None
    except Exception as exc:  # noqa: BLE001
        t02ctx["mapped"] = None
        t02ctx["raised"] = exc


@then("the mapping returns nothing and the loop does not crash")
def mapping_returns_nothing(t02ctx):
    assert t02ctx["raised"] is None
    assert t02ctx["mapped"] is None


@then('a single diagnostic event reports the LLM was unavailable')
def llm_unavailable_diagnostic(t02ctx):
    events = _collected_diagnostics(t02ctx)
    assert any("llm" in str(e).lower() or "unavailable" in str(e).lower() for e in events), (
        "no 'LLM unavailable' diagnostic surfaced after the mapping failure"
    )


# ===========================================================================
# #212 — _settle swallows the load-state timeout
# ===========================================================================
class _RenderedAts(AtsAdapter):
    name = "rendered"

    def matches(self, url):  # noqa: ARG002
        return True

    def pages(self, url):
        return [
            FakePage(
                url=f"{url}/form",
                fields=(
                    DetectedField("#first", "First Name", "text"),
                    DetectedField("#email", "Email", "text"),
                ),
            )
        ]


@given("a fully rendered application page")
def fully_rendered_page(t02ctx):
    src = FakePageSource(_RenderedAts())
    src.open("https://ats.example/job")
    t02ctx["source"] = src


@when("the engine detects fields on the page")
def detect_fields_on_page(t02ctx):
    t02ctx["fields"] = t02ctx["source"].detect_fields()


@then("the expected fields are returned")
def expected_fields_returned(t02ctx):
    selectors = {f.selector for f in t02ctx["fields"]}
    assert {"#first", "#email"} <= selectors


@given("a page whose load-state wait times out")
def settle_times_out(t02ctx):
    class _TimeoutPage:
        def wait_for_load_state(self, state, timeout):  # noqa: ARG002
            raise TimeoutError("networkidle never reached")

    t02ctx["fake_self"] = SimpleNamespace(_page=_TimeoutPage())


@when("the engine settles the page before inspecting it")
def settle_the_page(t02ctx):
    from applicant.adapters.browser.page_source import PlaywrightPageSource

    # Drive the real _settle against a timing-out fake page (no browser launched).
    t02ctx["settle_return"] = PlaywrightPageSource._settle(t02ctx["fake_self"])


@then("the timeout is surfaced rather than swallowed by a bare pass")
def settle_timeout_surfaced(t02ctx):
    # Today _settle swallows the timeout (returns None, records nothing) — genuine red.
    surfaced = bool(t02ctx.get("settle_return")) or getattr(
        t02ctx["fake_self"], "last_settle_timed_out", False
    )
    assert surfaced, "a settle timeout was swallowed silently (empty DOM risk)"


# ===========================================================================
# #213 — FakePageSource.is_account_gate() ignores a sign-in-only gate
# ===========================================================================
class _AccountCreateAts(AtsAdapter):
    name = "create-only"

    def matches(self, url):  # noqa: ARG002
        return True

    def pages(self, url):
        return [FakePage(url=f"{url}/create", is_account_create=True, fields=())]


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


@given("a fake page modelling an account-creation step")
def fake_account_create_page(t02ctx):
    src = FakePageSource(_AccountCreateAts())
    src.open("https://ats.example/job")
    t02ctx["source"] = src


@given("a fake page modelling a sign-in step with no account creation")
def fake_signin_only_page(t02ctx):
    src = FakePageSource(_SignInOnlyAts())
    src.open("https://ats.example/job")
    t02ctx["source"] = src


@when("the engine checks whether the page is an account gate")
def check_account_gate(t02ctx):
    t02ctx["is_gate"] = t02ctx["source"].is_account_gate()


@then("the page is recognised as a gate")
def page_is_gate(t02ctx):
    # GREEN for the account-create page (True today); RED for the sign-in-only page
    # (the fake only checks is_account_create, so it returns False until parity lands).
    assert t02ctx["is_gate"] is True


# ===========================================================================
# #215 — PINNED_CHROME_MAJOR stale; no env override
# ===========================================================================
@given("the coherent Chrome fingerprint built from the pinned major")
def coherent_chrome_fingerprint(t02ctx):
    t02ctx["fingerprint"] = coherent_fingerprint("chrome")


@when("the fingerprint is checked for internal consistency")
def check_fingerprint_coherence(t02ctx):
    t02ctx["coherent"] = fingerprint_is_coherent(t02ctx["fingerprint"])


@then("the user-agent, platform and client hints all agree")
def fingerprint_agrees(t02ctx):
    assert t02ctx["coherent"] is True


@given("a deployment where Chrome is not probeable on PATH")
def chrome_not_on_path(t02ctx, monkeypatch):
    import applicant.adapters.browser.stealth as stealth_mod

    monkeypatch.setattr(stealth_mod.shutil, "which", lambda name: None)
    t02ctx["monkeypatch"] = monkeypatch
    # Sanity: with no Chrome on PATH the probe returns None today.
    assert detect_chrome_major("chrome") is None


@when("the Chrome major is resolved with an environment override set")
def resolve_chrome_major_with_override(t02ctx, monkeypatch):
    monkeypatch.setenv("APPLICANT_CHROME_MAJOR", "128")
    # Speculative: a future env-aware resolver. Absent today → the probe falls through
    # to the @then which fails honestly.
    import applicant.adapters.browser.stealth as stealth_mod

    resolver = getattr(stealth_mod, "resolve_chrome_major", None)
    if callable(resolver):
        t02ctx["resolved_major"] = resolver("chrome")
    else:
        # No env-aware resolver exists; the only path is the env-blind detect probe.
        t02ctx["resolved_major"] = detect_chrome_major("chrome")


@then("the override value is used instead of the stale pinned default")
def override_value_used(t02ctx):
    # No env override exists today (detect_chrome_major ignores the env var and the
    # caller falls back to the hardcoded 124) — genuine red.
    assert t02ctx["resolved_major"] == 128, (
        "no environment override pinned the Chrome major to the installed browser"
    )


# ===========================================================================
# #216 — ProfileStore.for_tenant visit_count race
# ===========================================================================
@given("a fresh profile store")
def fresh_profile_store(t02ctx):
    t02ctx["profiles"] = ProfileStore()
    t02ctx["tenant"] = "workday:acme.example"


@when("the same tenant is visited twice in sequence")
def visit_tenant_twice(t02ctx):
    t02ctx["profiles"].for_tenant(t02ctx["tenant"])
    t02ctx["profiles"].for_tenant(t02ctx["tenant"])


@then("the second visit marks the tenant as returning")
def tenant_is_returning(t02ctx):
    assert t02ctx["profiles"].is_returning(t02ctx["tenant"]) is True


@when("the same tenant is visited from many threads at once")
def visit_tenant_concurrently(t02ctx):
    # ``for_tenant`` does a read-modify-write on a shared dict with NO synchronization.
    # A thread race is non-deterministic (CPython's GIL often masks the lost update), so
    # rather than a flaky timing test we record the concurrency-safety SEAM the fix must
    # provide. A correct fix guards the increment with a lock / atomic step; that guard
    # is absent today, so the @then assertion is a genuine, deterministic red.
    profiles = t02ctx["profiles"]
    t02ctx["has_guard"] = any(
        _looks_like_lock(getattr(profiles, name, None))
        for name in vars(profiles)
    ) or _looks_like_lock(getattr(profiles, "_lock", None))


def _looks_like_lock(obj) -> bool:
    """True if ``obj`` is a usable mutual-exclusion primitive (lock/semaphore)."""
    if obj is None:
        return False
    enter = getattr(obj, "__enter__", None)
    acquire = getattr(obj, "acquire", None)
    return callable(enter) and callable(acquire)


@then("the visit count equals the number of visits with no lost updates")
def visit_count_exact(t02ctx):
    # No synchronization guards the read-modify-write today, so concurrent visits can
    # lose an increment — genuine (deterministic) red until a lock / atomic step lands.
    assert t02ctx["has_guard"], (
        "ProfileStore.for_tenant increments visit_count without any lock, so it can "
        "lose updates under the default sandbox concurrency"
    )


# ===========================================================================
# #217 — PatchrightBrowser._sessions never evicted; no close()
# ===========================================================================
def _open_one_session():
    from applicant.adapters.browser.patchright_browser import PatchrightBrowser

    browser = PatchrightBrowser()
    aid = ApplicationId(new_id())
    browser.open(aid, "https://acme.myworkdayjobs.com/job/1")
    return browser, aid


@given("a browser adapter with one opened application session")
def adapter_with_session(t02ctx):
    browser, aid = _open_one_session()
    t02ctx["browser"] = browser
    t02ctx["aid"] = aid


@when("the application's session is looked up")
def lookup_session(t02ctx):
    t02ctx["found_state"] = t02ctx["browser"].current_state(t02ctx["aid"])


@then("the session is found")
def session_found(t02ctx):
    assert t02ctx["found_state"] is not None
    assert t02ctx["found_state"].url


@when("the application's session is closed")
def close_session(t02ctx):
    browser = t02ctx["browser"]
    # Speculative: a close()/dispose() that evicts the session. Absent today.
    closer = getattr(browser, "close", None) or getattr(browser, "dispose", None)
    if callable(closer):
        try:
            closer(t02ctx["aid"])
        except TypeError:
            closer()
    t02ctx["closer_existed"] = callable(closer)


@then("the session is no longer retained by the adapter")
def session_evicted(t02ctx):
    # No close()/dispose() exists, so the session stays in _sessions forever — red.
    assert t02ctx["closer_existed"], "the adapter has no close()/dispose() to evict a session"
    assert str(t02ctx["aid"]) not in t02ctx["browser"]._sessions


# ===========================================================================
# #222 — escalation prompt leaks sensitive attribute names
# ===========================================================================
class _PromptCapturingLLM:
    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, messages, **kwargs):  # noqa: ARG002
        from applicant.ports.driven.llm import LLMResult

        self.prompts.append(" ".join(m.content for m in messages))
        return LLMResult(text="NONE", tier=2, model="fake")

    def list_models(self):
        return ["fake"]

    def is_configured(self):
        return True


@given("a configured LLM and a sensitive form field")
def llm_and_sensitive_field(t02ctx):
    cid = _cid()
    t02ctx["llm"] = _PromptCapturingLLM()
    t02ctx["service"] = _service(browser=_SingleFieldBrowser([]), llm=t02ctx["llm"])
    t02ctx["field"] = DetectedField("#gender", "Gender", "select")
    t02ctx["attributes"] = [_attr(cid, "Gender", "Female", sensitive=True)]


@when("the engine considers escalating the field's mapping")
def consider_escalating_sensitive(t02ctx):
    svc = t02ctx["service"]
    t02ctx["mapped"] = svc._escalate_mapping(t02ctx["field"], t02ctx["attributes"])


@then("no LLM call is made for the sensitive field")
def no_llm_call_for_sensitive(t02ctx):
    # FR-ATTR-6: a sensitive field is never escalated to an LLM guess — shipped behaviour.
    assert t02ctx["mapped"] is None
    assert t02ctx["llm"].prompts == []


@given("a configured LLM and an attribute cloud containing a demographic attribute")
def llm_and_demographic_cloud(t02ctx):
    cid = _cid()
    t02ctx["llm"] = _PromptCapturingLLM()
    t02ctx["service"] = _service(browser=_SingleFieldBrowser([]), llm=t02ctx["llm"])
    # A non-sensitive field that DOES escalate, with a demographic attr in the cloud.
    t02ctx["field"] = DetectedField("#q", "Some custom screening question here please", "text")
    t02ctx["attributes"] = [
        _attr(cid, "current_title", "Engineer"),
        _attr(cid, "Gender", "Female", sensitive=True),
    ]


@when("the engine builds the escalation prompt for a non-sensitive field")
def build_escalation_prompt(t02ctx):
    svc = t02ctx["service"]
    svc._escalate_mapping(t02ctx["field"], t02ctx["attributes"])


@then("the demographic attribute name does not appear in the prompt")
def prompt_excludes_demographic(t02ctx):
    # Today the prompt joins ALL attribute names, including "Gender" — genuine red until
    # sensitive names are filtered out of the escalation prompt (defence in depth).
    assert t02ctx["llm"].prompts, "the non-sensitive field did not escalate as expected"
    joined = " ".join(t02ctx["llm"].prompts).lower()
    assert "gender" not in joined, "a demographic attribute name leaked into the LLM prompt"


# ===========================================================================
# #223 — _try_log_in conflates browser crash with wrong password
# ===========================================================================
class _LoginFailsBrowser:
    def log_in(self, aid, username, secret):  # noqa: ARG002
        return False


class _LoginCrashesBrowser:
    def log_in(self, aid, username, secret):  # noqa: ARG002
        raise RuntimeError("CDP disconnected mid-login")


@given("a browser whose login attempt reports failure")
def browser_login_fails(t02ctx):
    t02ctx["service"] = _service(browser=_LoginFailsBrowser())
    t02ctx["aid"] = ApplicationId(new_id())
    t02ctx["credential"] = SimpleNamespace(username="u", secret="s")


@given("a browser whose login attempt crashes the session")
def browser_login_crashes(t02ctx):
    storage = InMemoryStorage()
    t02ctx["cid"] = _cid()
    t02ctx["store_storage"] = storage
    t02ctx["service"] = _service(browser=_LoginCrashesBrowser(), storage=storage)
    t02ctx["aid"] = ApplicationId(new_id())
    t02ctx["credential"] = SimpleNamespace(username="u", secret="s")


@when("the engine tries to log in with a stored credential")
def try_log_in(t02ctx):
    svc = t02ctx["service"]
    t02ctx["login_ok"] = svc._try_log_in(t02ctx["aid"], t02ctx["credential"])


@then("the login is reported as unsuccessful and the flow hands off")
def login_unsuccessful_handoff(t02ctx):
    assert t02ctx["login_ok"] is False


@then("the transient browser error is surfaced as a diagnostic distinct from auth failure")
def transient_error_surfaced(t02ctx):
    # _try_log_in returns False for BOTH a crash and a wrong password today, with no
    # diagnostic to tell them apart — genuine red.
    assert t02ctx["login_ok"] is False  # still degrades to hand-off
    events = _collected_diagnostics(t02ctx)
    assert any("browser" in str(e).lower() or "login" in str(e).lower() for e in events), (
        "a browser crash during login was indistinguishable from a wrong password"
    )


# ===========================================================================
# #224 — PageSource Protocol missing submit_account
# ===========================================================================
@given("the in-memory page source")
def the_in_memory_page_source(t02ctx):
    t02ctx["source_cls"] = FakePageSource


@when("its account-submit capability is inspected")
def inspect_fake_submit_account(t02ctx):
    t02ctx["has_submit_account"] = hasattr(t02ctx["source_cls"], "submit_account")


@then("a submit_account method is present")
def submit_account_present(t02ctx):
    assert t02ctx["has_submit_account"] is True


@given("the page-source port contract")
def the_page_source_contract(t02ctx):
    from applicant.adapters.browser.page_source import PageSource

    t02ctx["protocol"] = PageSource


@when("the contract's declared members are inspected")
def inspect_protocol_members(t02ctx):
    proto = t02ctx["protocol"]
    members = set(getattr(proto, "__protocol_attrs__", set()))
    members |= {name for name in dir(proto) if not name.startswith("_")}
    t02ctx["protocol_members"] = members


@then("submit_account is one of the declared members")
def protocol_declares_submit_account(t02ctx):
    # The Protocol does not declare submit_account today, so the contract is not enforced
    # across implementations — genuine red until it is added to the Protocol.
    assert "submit_account" in t02ctx["protocol_members"], (
        "the PageSource Protocol does not declare submit_account"
    )
