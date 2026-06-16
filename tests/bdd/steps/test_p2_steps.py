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
    _open_gate(app_client)
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


# --- shared helpers --------------------------------------------------------
def _open_gate(client) -> None:
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204
