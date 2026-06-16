"""Step bindings for the Phase 2 acceptance scenarios (master spec §10).

Maps the §10 anchors — Maximal pre-fill (stop at irreducible human steps; Workday
account creation), cautious-mode takeover, and the credential vault (both banking
modes) — to the real Phase 2 services + adapters + core rules so the scenarios
genuinely pass with NO browser installed. Phase-local fixtures live here, not in
the shared conftest.

Every scenario maps to >=1 requirement ID (cited in the feature files):
FR-PREFILL-2/3/4/5/6, FR-ATTR-6, FR-SANDBOX-2/3, FR-NOTIF-2, FR-VAULT-1/2/3.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.credentials.pg_credential_store import PgCredentialStore
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.prefill_service import PrefillService
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    JobPostingId,
    new_id,
)
from applicant.core.rules.sensitive_fields import DECLINE_TO_SELF_IDENTIFY
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.credential_store import Credential

scenarios(
    "../features/p2_prefill_workday_account.feature",
    "../features/p2_cautious_mode_takeover.feature",
    "../features/p2_credential_vault.feature",
    "../features/p2_conversion_capture.feature",
)

WORKDAY_URL = "https://acme.myworkdayjobs.com/job/123"


# --- phase-local fixtures --------------------------------------------------
@pytest.fixture
def p2ctx() -> dict:
    return {}


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def prefill(storage) -> PrefillService:
    return PrefillService(
        storage=storage,
        browser=PatchrightBrowser(),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=PgCredentialStore("/tmp/p2-master.key"),
        notification=AppriseNotifier(discord_webhook_url="https://discord.test/wh"),
    )


def _stored_answers(cid: CampaignId) -> list[Attribute]:
    """A small attribute cloud incl. one explicit sensitive answer (FR-ATTR-6)."""
    def a(name: str, value: str, sensitive: bool = False) -> Attribute:
        return Attribute(
            id=AttributeId(new_id()),
            campaign_id=cid,
            name=name,
            value=value,
            is_sensitive=sensitive,
        )

    return [
        a("Email Address", "kevin@kevinhirsch.com"),
        a("Password", "S3cretP@ss"),
        a("Verify Password", "S3cretP@ss"),
        a("First Name", "Kevin"),
        a("Last Name", "Hirsch"),
        a("Phone", "555-0100"),
        a("Address", "1 Main St"),
        a("Current Job Title", "Engineer"),
        a("Years of Experience", "8"),
        a("Are you authorized to work?", "Yes"),
        # Factual screening question (the essay one is deferred to Phase 3).
        a("Are you willing to relocate?", "Yes"),
        # Exactly one EEO answer is explicitly provided; the rest must decline.
        a("Gender", "Female", sensitive=True),
    ]


def _new_application(cid: CampaignId) -> Application:
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        root_url=WORKDAY_URL,
    )


# === Maximal pre-fill / Workday account creation ===========================
@given("an approved role on a Workday tenant requiring an account")
def approved_workday_role(p2ctx):
    cid = CampaignId(new_id())
    p2ctx["campaign_id"] = cid
    p2ctx["application"] = _new_application(cid)


@given("the campaign attribute cloud holds the user's stored answers")
def attribute_cloud(p2ctx):
    p2ctx["attributes"] = _stored_answers(p2ctx["campaign_id"])


@when("the engine reaches the account-creation form")
def reach_account_form(p2ctx, prefill):
    p2ctx["result"] = prefill.prefill_application(
        p2ctx["application"], WORKDAY_URL, p2ctx["attributes"]
    )


@then("it pre-fills every fillable field on the account form")
def account_fully_prefilled(p2ctx):
    result = p2ctx["result"]
    # The account page is the first page; its three fields must all be filled.
    account_pages = [v for url, v in result.filled_by_page.items() if "account/create" in url]
    assert account_pages, "account page was not filled"
    assert set(account_pages[0]) == {"#email", "#password", "#verify-password"}


@then("it does not click the account-creating submit")
def no_account_submit(p2ctx):
    # Reaching the waiting state without raising proves the submit was not clicked;
    # the adapter contract test proves submit_account() always raises.
    assert p2ctx["result"].account_handoff is True


@then("it notifies the user with a one-click VNC link to complete the human step")
def vnc_handoff_notification(p2ctx, prefill, storage):
    result = p2ctx["result"]
    assert result.sandbox_session_url  # one-click live-session URL
    # FR-SANDBOX-2: the live-session URL is a one-click, token-bearing deep link.
    assert "token=" in result.sandbox_session_url
    # The notification carried the deep link (FR-NOTIF-2 / FR-PREFILL-4).
    notifier: AppriseNotifier = prefill._notification  # phase-local introspection
    dedup = f"{result.application_id}:account_human_step"
    assert notifier.is_active(dedup)
    # And a pending action landed in the portal.
    pending = storage.pending_actions.list_open(p2ctx["campaign_id"])
    assert any(p.kind == "account_human_step" for p in pending)


@then("the application is awaiting the account human step")
def awaiting_account(p2ctx):
    assert p2ctx["result"].state == ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP


@when("the engine pre-fills the full application after the account step")
def prefill_full_application(p2ctx, prefill):
    # First reach + hand off at the account page (engine never submits it)...
    prefill.prefill_application(p2ctx["application"], WORKDAY_URL, p2ctx["attributes"])
    # ...then the user completes the account step and the engine resumes.
    app = p2ctx["application"].with_status(ApplicationState.SANDBOX_PROVISIONING)
    app = app.with_status(ApplicationState.ACCOUNT_PREFILL)
    app = app.with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
    p2ctx["result"] = prefill.resume_after_account(app, p2ctx["attributes"])


@then("every fillable application field is pre-filled")
def all_app_fields_filled(p2ctx):
    result = p2ctx["result"]
    # Personal + experience pages each contributed filled values.
    assert any("personal" in url for url in result.filled_by_page)
    assert any("experience" in url for url in result.filled_by_page)


@then("sensitive EEO fields are filled only from explicit stored answers")
def eeo_from_explicit(p2ctx):
    result = p2ctx["result"]
    # The one explicit EEO answer (Gender) was filled from the stored value.
    assert "#gender" in result.sensitive_filled_from_explicit
    eeo = next(v for url, v in result.filled_by_page.items() if "voluntary" in url)
    assert eeo["#gender"] == "Female"


@then("unanswered sensitive fields default to decline to self-identify")
def eeo_declined(p2ctx):
    result = p2ctx["result"]
    assert "#race" in result.sensitive_declined
    assert "#veteran" in result.sensitive_declined
    eeo = next(v for url, v in result.filled_by_page.items() if "voluntary" in url)
    assert eeo["#race"] == DECLINE_TO_SELF_IDENTIFY
    assert eeo["#veteran"] == DECLINE_TO_SELF_IDENTIFY


@then("the application is awaiting final approval")
def awaiting_final(p2ctx):
    assert p2ctx["result"].state == ApplicationState.AWAITING_FINAL_APPROVAL


# === Missing-attribute soft error (FR-ATTR-5) ==============================
@given("the campaign attribute cloud is missing a required detail")
def attribute_cloud_missing(p2ctx):
    # Drop "Phone" — a required personal-info field — to trigger the soft error.
    p2ctx["attributes"] = [a for a in _stored_answers(p2ctx["campaign_id"]) if a.name != "Phone"]


@then("pre-fill pauses with a missing-detail soft error")
def paused_missing_attr(p2ctx):
    assert p2ctx["result"].state == ApplicationState.BLOCKED_MISSING_ATTR
    assert p2ctx["result"].missing_attribute == "Phone"


@then("a provide-missing-detail pending action is created")
def missing_attr_pending(p2ctx, storage):
    pending = storage.pending_actions.list_open(p2ctx["campaign_id"])
    assert any(p.kind == "missing_attr" for p in pending)


@when("the user supplies the missing detail")
def user_supplies_detail(p2ctx, prefill):
    # FR-ATTR-5: the supplied value is stored + reused; the engine resumes.
    phone = next(a for a in _stored_answers(p2ctx["campaign_id"]) if a.name == "Phone")
    full = [*p2ctx["attributes"], phone]
    app = (
        p2ctx["application"]
        .with_status(ApplicationState.SANDBOX_PROVISIONING)
        .with_status(ApplicationState.ACCOUNT_PREFILL)
        .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
    )
    # Re-run from the account step with the now-complete cloud (fresh session).
    prefill.prefill_application(p2ctx["application"], WORKDAY_URL, full)
    p2ctx["result"] = prefill.resume_after_account(app, full)


@then("pre-fill resumes and reaches awaiting final approval")
def resumed_to_final(p2ctx):
    assert p2ctx["result"].state == ApplicationState.AWAITING_FINAL_APPROVAL


# === Screening-question routing (FR-ANSWER-1) ==============================
@then("factual screening questions are filled from stored answers")
def factual_filled(p2ctx):
    result = p2ctx["result"]
    questions = next(v for url, v in result.filled_by_page.items() if "questions" in url)
    assert questions["#q-relocate"] == "Yes"


@then("essay screening questions are deferred to material generation")
def essay_deferred(p2ctx):
    result = p2ctx["result"]
    deferred = [d["selector"] for d in result.deferred_essay_questions]
    assert "#q-why" in deferred
    questions = next(v for url, v in result.filled_by_page.items() if "questions" in url)
    assert "#q-why" not in questions  # never auto-answered (FR-ANSWER-1)


# === Cautious mode + takeover ==============================================
@given("an approved role being pre-filled in a sandbox")
def role_being_prefilled(p2ctx):
    cid = CampaignId(new_id())
    p2ctx["campaign_id"] = cid
    p2ctx["application"] = _new_application(cid)
    p2ctx["attributes"] = _stored_answers(cid)


@given("cautious mode is enabled")
def cautious_enabled(p2ctx):
    p2ctx["cautious"] = True


@when("an automation-detection signal appears on the page")
def detection_signal_appears(p2ctx, prefill):
    app = p2ctx["application"]
    # Open + provision, inject a Turnstile signal on the first page, then run.
    sandbox = prefill._sandbox
    browser = prefill._browser
    session = sandbox.provision(app.id)
    p2ctx["session_url"] = session.remote_view_url
    browser.open(app.id, WORKDAY_URL)
    browser.inject_detection_signal(app.id, "turnstile")
    # Drive the continuation loop directly so the seeded session/page is reused.
    from applicant.application.services.prefill_service import PrefillResult

    result = PrefillResult(
        application_id=app.id, state=ApplicationState.PREFILLING, sandbox_session_url=session.remote_view_url
    )
    p2ctx["result"] = prefill._continue_pages(
        app.with_status(ApplicationState.SANDBOX_PROVISIONING).with_status(ApplicationState.PREFILLING),
        p2ctx["attributes"],
        result,
        cautious=True,
    )


@then("pre-fill pauses in a detection-blocked state")
def paused_blocked_detection(p2ctx):
    assert p2ctx["result"].state == ApplicationState.BLOCKED_DETECTION
    assert p2ctx["result"].detection_signal == "turnstile"


@then("a take-over pending action with a live-session link is created")
def takeover_pending_action(p2ctx, storage):
    pending = storage.pending_actions.list_open(p2ctx["campaign_id"])
    blocker = next((p for p in pending if p.kind == "detection_blocker"), None)
    assert blocker is not None
    assert blocker.payload.get("session_url")


@then("the engine never solves the challenge")
def never_solves(p2ctx):
    # No fields were filled on the blocked page — the engine paused, never bypassed.
    assert p2ctx["result"].filled_by_page == {}


@given("an application awaiting final approval in a live session")
def app_awaiting_final(p2ctx, app_client):
    from tests.conftest import open_automated_work_gate

    # The remote submit paths are automated work behind the automated-work gate
    # (FR-ONBOARD-2/FR-OOBE-3) in addition to the LLM gate.
    open_automated_work_gate(app_client)
    p2ctx["client"] = app_client
    p2ctx["application_id"] = new_id()
    r = app_client.post("/api/remote/sessions", json={"application_id": p2ctx["application_id"]})
    assert r.status_code == 201
    p2ctx["session"] = r.json()


@when("the user authorizes the engine to finish")
def user_authorizes_engine(p2ctx):
    p2ctx["resp"] = p2ctx["client"].post(
        f"/api/remote/applications/{p2ctx['application_id']}/authorize-engine-finish"
    )


@then("the engine finishes friction-free and a submitted outcome is recorded")
def engine_finished(p2ctx, app_client):
    assert p2ctx["resp"].status_code == 201
    body = p2ctx["resp"].json()
    assert body["result"] == "finished_by_engine"
    outcomes = app_client.app.state.container.storage.outcomes.list_for_application(
        p2ctx["application_id"]
    )
    assert any(o.type == "submitted" and o.source.value == "auto" for o in outcomes)


@when("the user submits themselves in the live session")
def user_submits_self(p2ctx):
    p2ctx["resp"] = p2ctx["client"].post(
        f"/api/remote/applications/{p2ctx['application_id']}/submit-self"
    )


@then("a user-submitted outcome is recorded")
def user_submitted(p2ctx, app_client):
    assert p2ctx["resp"].status_code == 201
    body = p2ctx["resp"].json()
    assert body["result"] == "submitted_by_user"
    outcomes = app_client.app.state.container.storage.outcomes.list_for_application(
        p2ctx["application_id"]
    )
    assert any(o.type == "submitted" and o.source.value == "manual" for o in outcomes)


# === Credential vault ======================================================
@given("a campaign with no stored credentials for a Workday tenant")
def campaign_no_creds(p2ctx, credential_store):
    p2ctx["campaign_id"] = CampaignId(new_id())
    p2ctx["vault"] = credential_store
    p2ctx["tenant"] = "acme.workday"
    assert p2ctx["vault"].retrieve(p2ctx["campaign_id"], p2ctx["tenant"]) is None


@when("the user manually banks a credential set for the tenant")
def manually_bank(p2ctx):
    # FR-VAULT-2: manual entry in the vault UI (preferred upfront).
    p2ctx["vault"].store(
        p2ctx["campaign_id"],
        Credential(tenant_key=p2ctx["tenant"], username="kevin", secret="hunter2"),
    )


@when("credentials entered during live account creation are auto-captured")
def auto_capture(p2ctx):
    # FR-VAULT-2: auto-capture of credentials entered during human account creation.
    p2ctx["vault"].store(
        p2ctx["campaign_id"],
        Credential(tenant_key=p2ctx["tenant"], username="kevin", secret="captured-secret"),
    )


@then("the credential set is sealed and retrievable for that tenant")
def creds_retrievable(p2ctx):
    got = p2ctx["vault"].retrieve(p2ctx["campaign_id"], p2ctx["tenant"])
    assert got is not None and got.username == "kevin"


@then("the tenant is listed among the campaign's credential tenants")
def tenant_listed(p2ctx):
    assert p2ctx["tenant"] in p2ctx["vault"].list_tenants(p2ctx["campaign_id"])


@then("the stored secret is never returned in plaintext logs")
def secret_sealed_at_rest(p2ctx):
    # The internal sealed record must not equal the plaintext secret (NFR-PRIV-1).
    sealed = p2ctx["vault"]._store[(str(p2ctx["campaign_id"]), p2ctx["tenant"])]
    assert sealed["secret"] != "captured-secret"


# === Conversion capture (auto-detected or marked) (FR-LOG-1/2/4, FR-LEARN-2) ===
@given("an application awaiting final approval in a controlled sandbox session")
def app_awaiting_in_session(p2ctx, storage):
    from applicant.adapters.browser.patchright_browser import PatchrightBrowser
    from applicant.application.services.submission_service import SubmissionService

    cid = CampaignId(new_id())
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.AWAITING_FINAL_APPROVAL,
        role_name="Senior Engineer",
        work_mode="remote",
        root_url=WORKDAY_URL,
    )
    browser = PatchrightBrowser()
    browser.open(app.id, WORKDAY_URL)
    p2ctx["campaign_id"] = cid
    p2ctx["application"] = app
    p2ctx["browser"] = browser
    p2ctx["storage"] = storage
    p2ctx["submission"] = SubmissionService(storage, browser)


@when("the user submits and the ATS shows a confirmation page")
def ats_shows_confirmation(p2ctx):
    # The user clicks submit in the live session; the ATS renders its confirmation.
    p2ctx["browser"].simulate_confirmation(
        p2ctx["application"].id, text="Application submitted. Thank you for applying."
    )


@then("the engine auto-detects the submission")
def engine_auto_detects(p2ctx):
    svc = p2ctx["submission"]
    assert svc.detect_submission(p2ctx["application"].id) is True
    # Record it from the controlled session (auto source -> engine-finished).
    from applicant.core.entities.outcome_event import OutcomeSource

    p2ctx["event"] = svc.record_submission(
        p2ctx["application"],
        source=OutcomeSource.AUTO,
        attributes_used={"Email Address": "kevin@kevinhirsch.com"},
        screenshots=["screenshot://1", "screenshot://2"],
        screenshot_pages=[f"{WORKDAY_URL}/personal", f"{WORKDAY_URL}/experience"],
    )


@then("a submitted outcome event is recorded for conversion learning")
def submitted_outcome_recorded(p2ctx):
    outcomes = p2ctx["storage"].outcomes.list_for_application(p2ctx["application"].id)
    assert any(o.type == "submitted" for o in outcomes)


@then("the application detail and per-page screenshots are logged")
def detail_and_screenshots_logged(p2ctx):
    storage = p2ctx["storage"]
    logged = storage.applications.get(p2ctx["application"].id)
    # FR-LOG-1: role/work-mode/root-url + attributes used are logged.
    assert logged.role_name == "Senior Engineer"
    assert logged.work_mode == "remote"
    assert logged.root_url == WORKDAY_URL
    assert logged.attributes_used.get("Email Address") == "kevin@kevinhirsch.com"
    # FR-LOG-2: per-page screenshots archived.
    shots = storage.screenshots.list_for_application(p2ctx["application"].id)
    assert len(shots) == 2


@given("an application in emergency data-handoff")
def app_in_emergency(p2ctx, storage):
    from applicant.application.services.submission_service import SubmissionService

    cid = CampaignId(new_id())
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.EMERGENCY_DATA_HANDOFF,
        role_name="Senior Engineer",
        root_url=WORKDAY_URL,
    )
    p2ctx["campaign_id"] = cid
    p2ctx["application"] = app
    p2ctx["storage"] = storage
    p2ctx["submission"] = SubmissionService(storage)


@when("the user taps mark-submitted")
def user_taps_mark_submitted(p2ctx):
    p2ctx["event"] = p2ctx["submission"].mark_submitted(p2ctx["application"])


@then("the application is logged as submitted by the user")
def logged_submitted_by_user(p2ctx):
    logged = p2ctx["storage"].applications.get(p2ctx["application"].id)
    assert logged.status == ApplicationState.SUBMITTED_BY_USER


# --- shared helpers --------------------------------------------------------
def _open_gate(client) -> None:
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204
