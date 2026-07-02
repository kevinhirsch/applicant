"""PrefillService unit tests (FR-PREFILL-2/3/4/6/7, FR-ATTR-5/6, FR-ANSWER-1).

Hermetic: the in-memory FakePageSource drives the Workday flow with NO browser.
These cover the deeper Phase-2 behaviors beyond the BDD anchors:

* missing required attribute → BLOCKED_MISSING_ATTR soft error + reuse after resolve;
* essay screening question → deferred to Phase 3 (recorded, not auto-answered);
* factual screening question → filled from a stored attribute;
* ambiguous non-sensitive mapping → LLM escalation (FR-PREFILL-3);
* sensitive field is NEVER escalated to an LLM guess (FR-ATTR-6);
* emergency data-handoff is opt-in only, after a reported fill failure (FR-PREFILL-7).
"""

from __future__ import annotations

import pytest

from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.prefill_service import PrefillResult, PrefillService
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

WORKDAY_URL = "https://acme.myworkdayjobs.com/job/123"


def _attr(cid, name, value, sensitive=False):
    return Attribute(
        id=AttributeId(new_id()), campaign_id=cid, name=name, value=value, is_sensitive=sensitive
    )


@pytest.mark.unit
def test_optional_unmapped_field_is_skipped_not_blocked():
    """Universal-ATS support: a required-TYPE field the form marks OPTIONAL
    (``required is False``) and that maps to nothing must be SKIPPED, not block the
    whole application — real ATS forms carry many optional free-text questions."""
    from applicant.ports.driven.browser_automation import DetectedField, PageState

    class _OptionalFieldBrowser:
        def current_state(self, aid):
            return PageState(url="https://x/form", fields=())

        def detect_fields(self, aid):
            return [
                DetectedField(
                    selector="#opt", label="Anything else to add?",
                    field_type="text", required=False,
                )
            ]

        def fill_field(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("an unmappable OPTIONAL field must be skipped, not filled")

    cid = CampaignId(new_id())
    svc = PrefillService(
        storage=InMemoryStorage(), browser=_OptionalFieldBrowser(),
        detection=DetectionMonitor(), sandbox=LocalSandbox(), credentials=None, llm=None,
    )
    app = _app(cid)
    result = PrefillResult(application_id=app.id, state=app.status)
    # No value resolves (empty attributes) → the optional field is skipped, no block.
    assert svc._fill_current_page(app, [], result) is None


def _full_answers(cid):
    return [
        _attr(cid, "Email Address", "kevin@kevinhirsch.com"),
        _attr(cid, "Password", "S3cretP@ss"),
        _attr(cid, "Verify Password", "S3cretP@ss"),
        _attr(cid, "First Name", "Kevin"),
        _attr(cid, "Last Name", "Hirsch"),
        _attr(cid, "Phone", "555-0100"),
        _attr(cid, "Address", "1 Main St"),
        _attr(cid, "Current Job Title", "Engineer"),
        _attr(cid, "Years of Experience", "8"),
        _attr(cid, "Are you authorized to work?", "Yes"),
        _attr(cid, "Are you willing to relocate?", "Yes"),
        _attr(cid, "Gender", "Female", sensitive=True),
    ]


def _app(cid):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        root_url=WORKDAY_URL,
    )


def _service(storage, llm=None):
    return PrefillService(
        storage=storage,
        browser=PatchrightBrowser(),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        llm=llm,
    )


class _GoogleBrowser(PatchrightBrowser):
    """A PatchrightBrowser (fake source) whose 'Sign in with Google' returns a fixed
    status, so the Google/2FA routing is exercised hermetically. 'ok' advances the
    fake source past the gate (as a real successful OAuth would)."""

    def __init__(self, status: str) -> None:
        super().__init__()
        self._status = status

    def offers_google_signin(self, application_id) -> bool:  # noqa: ARG002
        return True

    def log_in_with_google(self, application_id, username, password) -> str:  # noqa: ARG002
        if self._status == "ok":
            self._source(application_id).advance()
        return self._status


def _google_service(storage, status, tmp_path):
    from applicant.adapters.credentials.pg_credential_store import (
        Credential,
        InMemoryCredentialStore,
    )
    from applicant.application.services.prefill_service import GOOGLE_CREDENTIAL_KEY

    creds = InMemoryCredentialStore(str(tmp_path / "master.key"))
    return creds, GOOGLE_CREDENTIAL_KEY, PrefillService(
        storage=storage,
        browser=_GoogleBrowser(status),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=creds,
        llm=None,
    ), Credential


def _resume_full(service, app, attrs):
    """Reach + hand off at the account page, then resume the rest of the flow."""
    service.prefill_application(app, WORKDAY_URL, attrs)
    resumed = (
        app.with_status(ApplicationState.SANDBOX_PROVISIONING)
        .with_status(ApplicationState.ACCOUNT_PREFILL)
        .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
    )
    return service.resume_after_account(resumed, attrs)


@pytest.mark.unit
class TestMaximalPrefill:
    def test_full_flow_reaches_final_approval(self):
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = _service(storage)
        result = _resume_full(service, _app(cid), _full_answers(cid))
        assert result.state == ApplicationState.AWAITING_FINAL_APPROVAL

    def test_per_page_screenshots_pair_with_page_urls(self):
        # FR-LOG-2: each archived screenshot is paired with the page URL it captured.
        cid = CampaignId(new_id())
        service = _service(InMemoryStorage())
        result = _resume_full(service, _app(cid), _full_answers(cid))
        assert result.screenshots  # at least one per-page screenshot
        assert len(result.screenshots) == len(result.screenshot_pages)
        assert any("application/personal" in u for u in result.screenshot_pages)

    def test_per_page_screenshots_are_archived_to_storage(self):
        # FR-LOG-2: running the pre-fill flow PERSISTS each page screenshot to the
        # storage port as it is captured (not just held in the PrefillResult), so a
        # completed application has its per-page screenshots retrievable via storage.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = _service(storage)
        app = _app(cid)
        result = _resume_full(service, app, _full_answers(cid))
        archived = storage.screenshots.list_for_application(app.id)
        assert archived, "screenshots persisted to storage during pre-fill"
        # At least every shot captured on the resumed pass is archived (the account
        # pass also archives into the same storage), each carrying its page URL.
        assert len(archived) >= len(result.screenshots)
        assert all(s.page_url for s in archived)
        assert any("application/personal" in s.page_url for s in archived)

    def test_factual_screening_question_is_filled(self):
        cid = CampaignId(new_id())
        service = _service(InMemoryStorage())
        result = _resume_full(service, _app(cid), _full_answers(cid))
        questions = next(v for url, v in result.filled_by_page.items() if "questions" in url)
        assert questions["#q-relocate"] == "Yes"

    def test_essay_screening_question_is_deferred_not_answered(self):
        # FR-ANSWER-1: essay questions are deferred to Phase 3, never auto-answered.
        cid = CampaignId(new_id())
        service = _service(InMemoryStorage())
        result = _resume_full(service, _app(cid), _full_answers(cid))
        deferred = [d["selector"] for d in result.deferred_essay_questions]
        assert "#q-why" in deferred
        questions = next(v for url, v in result.filled_by_page.items() if "questions" in url)
        assert "#q-why" not in questions  # not filled

    def test_essay_question_materializes_agent_question_pending_action(self):
        # FR-UI-3: a genuine question requiring the human produces an `agent_question`
        # pending action so it shows in the portal (the kind now HAS a producer).
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = _service(storage)
        _resume_full(service, _app(cid), _full_answers(cid))
        pending = storage.pending_actions.list_open(cid)
        questions = [p for p in pending if p.kind == "agent_question"]
        assert questions, "essay screening question -> agent_question pending action"
        assert any("#q-why" == q.payload.get("field_selector") for q in questions)

    def test_sensitive_eeo_policy_enforced(self):
        cid = CampaignId(new_id())
        service = _service(InMemoryStorage())
        result = _resume_full(service, _app(cid), _full_answers(cid))
        assert "#gender" in result.sensitive_filled_from_explicit
        assert "#race" in result.sensitive_declined
        eeo = next(v for url, v in result.filled_by_page.items() if "voluntary" in url)
        assert eeo["#gender"] == "Female"
        assert eeo["#race"] == DECLINE_TO_SELF_IDENTIFY


@pytest.mark.unit
class TestMissingAttribute:
    def test_missing_required_attribute_blocks_with_soft_error(self):
        # FR-ATTR-5: a missing required field stalls in BLOCKED_MISSING_ATTR.
        cid = CampaignId(new_id())
        attrs = [a for a in _full_answers(cid) if a.name != "Phone"]
        storage = InMemoryStorage()
        service = _service(storage)
        result = _resume_full(service, _app(cid), attrs)
        assert result.state == ApplicationState.BLOCKED_MISSING_ATTR
        assert result.missing_attribute == "Phone"
        pending = storage.pending_actions.list_open(cid)
        assert any(p.kind == "missing_attr" for p in pending)

    def test_missing_required_field_on_account_page_hands_off_not_crash(self):
        # Regression (surfaced by a live Workday run): a required field with no stored
        # value ON THE ACCOUNT-CREATE PAGE must hand off to the human account step, not
        # raise the illegal ACCOUNT_PREFILL -> BLOCKED_MISSING_ATTR transition. The
        # human creates the account and fills anything the engine could not.
        cid = CampaignId(new_id())
        attrs = [a for a in _full_answers(cid) if a.name != "Email Address"]
        service = _service(InMemoryStorage())
        result = service.prefill_application(_app(cid), WORKDAY_URL, attrs)
        assert result.state == ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP

    def test_credential_auto_login_skips_the_human_handoff(self, tmp_path):
        # Automate-by-default: a stored ATS credential makes the engine sign in itself
        # at the account gate and walk the rest of the flow — NO per-application human
        # sign-in. (FR-PREFILL: login from a user-provided credential is the user's
        # intent; the engine drives it.)
        from applicant.adapters.credentials.pg_credential_store import (
            Credential,
            InMemoryCredentialStore,
        )

        cid = CampaignId(new_id())
        creds = InMemoryCredentialStore(str(tmp_path / "master.key"))
        creds.store(
            cid,
            Credential(
                tenant_key="workday:acme.myworkdayjobs.com",
                username="kevin@kevinhirsch.com",
                secret="s3cret",
            ),
        )
        storage = InMemoryStorage()
        service = _service(storage)
        service._credentials = creds  # noqa: SLF001 - inject the seeded vault
        result = service.prefill_application(_app(cid), WORKDAY_URL, _full_answers(cid))
        # Signed in + walked to the end — no account hand-off pending action.
        assert result.state == ApplicationState.AWAITING_FINAL_APPROVAL
        assert not any(
            p.kind == "account_human_step" for p in storage.pending_actions.list_open(cid)
        )

    def test_no_credential_still_hands_off_at_the_gate(self, tmp_path):
        # Without a stored credential the engine hands off at the account gate (the
        # human signs in / creates the account) — unchanged behavior.
        from applicant.adapters.credentials.pg_credential_store import InMemoryCredentialStore

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = _service(storage)
        service._credentials = InMemoryCredentialStore(str(tmp_path / "master.key"))  # empty
        result = service.prefill_application(_app(cid), WORKDAY_URL, _full_answers(cid))
        assert result.state == ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP

    def test_account_creation_when_enabled_creates_and_banks_credential(self, tmp_path):
        # ADR-0004: with ALLOW_AUTOMATED_ACCOUNTS on + a predefined set, the engine
        # creates an account, banks the credential under the tenant key, and continues.
        from applicant.adapters.credentials.pg_credential_store import (
            Credential,
            InMemoryCredentialStore,
        )
        from applicant.application.services.prefill_service import PREDEFINED_CREDENTIAL_KEY

        cid = CampaignId(new_id())
        creds = InMemoryCredentialStore(str(tmp_path / "master.key"))
        creds.store(
            cid, Credential(tenant_key=PREDEFINED_CREDENTIAL_KEY, username="kevin@kevinhirsch.com", secret="")
        )
        storage = InMemoryStorage()
        svc = PrefillService(
            storage=storage,
            browser=PatchrightBrowser(automated_accounts=True),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=creds,
            llm=None,
            allow_automated_accounts=True,
        )
        result = svc.prefill_application(_app(cid), WORKDAY_URL, _full_answers(cid))
        assert result.state == ApplicationState.AWAITING_FINAL_APPROVAL
        banked = creds.retrieve(cid, "workday:acme.myworkdayjobs.com")
        assert banked is not None and banked.username == "kevin@kevinhirsch.com"

    def test_account_creation_disabled_hands_off(self, tmp_path):
        # Default (gate OFF): even with a predefined set, the engine does NOT create an
        # account — it hands off at the gate.
        from applicant.adapters.credentials.pg_credential_store import (
            Credential,
            InMemoryCredentialStore,
        )
        from applicant.application.services.prefill_service import PREDEFINED_CREDENTIAL_KEY

        cid = CampaignId(new_id())
        creds = InMemoryCredentialStore(str(tmp_path / "master.key"))
        creds.store(
            cid, Credential(tenant_key=PREDEFINED_CREDENTIAL_KEY, username="kevin@kevinhirsch.com", secret="")
        )
        storage = InMemoryStorage()
        svc = PrefillService(
            storage=storage,
            browser=PatchrightBrowser(automated_accounts=False),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=creds,
            llm=None,
            allow_automated_accounts=False,
        )
        result = svc.prefill_application(_app(cid), WORKDAY_URL, _full_answers(cid))
        assert result.state == ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP

    def test_google_login_hits_2fa_and_hands_off_with_continue_action(self, tmp_path):
        # "Sign in with Google" that demands 2FA: the engine can't produce the second
        # factor, so it holds the sandbox and emits a `two_factor` pending action (with
        # a continue link) + notification, then pivots. The user approves on-device.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        creds, gkey, svc, Credential = _google_service(storage, "two_factor", tmp_path)
        creds.store(cid, Credential(tenant_key=gkey, username="me@gmail.com", secret="g"))
        result = svc.prefill_application(_app(cid), WORKDAY_URL, _full_answers(cid))
        assert result.state == ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP
        assert any(
            p.kind == "two_factor" for p in storage.pending_actions.list_open(cid)
        )

    def test_google_login_ok_continues_into_the_form(self, tmp_path):
        # A live Google session (or accepted creds) carries through → the engine
        # proceeds into the application form, no hand-off.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        creds, gkey, svc, Credential = _google_service(storage, "ok", tmp_path)
        creds.store(cid, Credential(tenant_key=gkey, username="me@gmail.com", secret="g"))
        result = svc.prefill_application(_app(cid), WORKDAY_URL, _full_answers(cid))
        assert result.state == ApplicationState.AWAITING_FINAL_APPROVAL

    def test_global_google_credential_applies_across_campaigns(self, tmp_path):
        # The Google sign-in is set once (banked under the SYSTEM campaign) and reused
        # everywhere: an application in a DIFFERENT campaign with no per-campaign entry
        # still finds it and continues — "sign in to Google once, reuse it everywhere".
        from applicant.core.ids import SYSTEM_CAMPAIGN_ID

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        creds, gkey, svc, Credential = _google_service(storage, "ok", tmp_path)
        creds.store(
            CampaignId(SYSTEM_CAMPAIGN_ID),
            Credential(tenant_key=gkey, username="me@gmail.com", secret="g"),
        )
        result = svc.prefill_application(_app(cid), WORKDAY_URL, _full_answers(cid))
        assert result.state == ApplicationState.AWAITING_FINAL_APPROVAL

    @staticmethod
    def _held_2fa(base):
        return (
            base.with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.ACCOUNT_PREFILL)
            .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
        )

    def test_resume_two_factor_success_continues_into_form(self, tmp_path):
        # The user tapped "continue" and approved 2FA on-device: the engine re-drives
        # Google (push), the gate clears, and it proceeds into the application form.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        creds, gkey, svc, Credential = _google_service(storage, "ok", tmp_path)
        creds.store(cid, Credential(tenant_key=gkey, username="me@gmail.com", secret="g"))
        base = _app(cid)
        svc._browser.open(base.id, WORKDAY_URL)  # held session is open
        result = svc.resume_two_factor(
            self._held_2fa(base), _full_answers(cid), timeout_s=1.0, poll_s=0.0
        )
        assert result.state == ApplicationState.AWAITING_FINAL_APPROVAL

    def test_resume_two_factor_timeout_emits_retry_notification(self, tmp_path):
        # No approval within the window → re-notify for a retry; the app stays held.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        creds, gkey, svc, Credential = _google_service(storage, "two_factor", tmp_path)
        creds.store(cid, Credential(tenant_key=gkey, username="me@gmail.com", secret="g"))
        base = _app(cid)
        svc._browser.open(base.id, WORKDAY_URL)
        result = svc.resume_two_factor(
            self._held_2fa(base), _full_answers(cid), timeout_s=0.0, poll_s=0.0
        )
        assert result.state == ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP
        retries = [
            p for p in storage.pending_actions.list_open(cid) if p.kind == "two_factor"
        ]
        assert retries and retries[-1].payload.get("retry") is True

    def test_value_reused_after_resolve(self):
        # FR-ATTR-5: once supplied, the value is reused and the loop proceeds.
        cid = CampaignId(new_id())
        partial = [a for a in _full_answers(cid) if a.name != "Phone"]
        storage = InMemoryStorage()
        service = _service(storage)
        blocked = _resume_full(service, _app(cid), partial)
        assert blocked.state == ApplicationState.BLOCKED_MISSING_ATTR
        # User supplies the detail; the engine resumes from PREFILLING.
        full = [*partial, _attr(cid, "Phone", "555-0100")]
        # Re-open the browser session at the stalled page is modeled by a fresh
        # resume on a new service sharing the same browser would be needed in a
        # real run; here we assert the resolved attribute now fills end-to-end.
        service2 = _service(InMemoryStorage())
        done = _resume_full(service2, _app(cid), full)
        assert done.state == ApplicationState.AWAITING_FINAL_APPROVAL


@pytest.mark.unit
class TestLLMEscalation:
    def test_ambiguous_mapping_escalates_to_llm(self):
        # FR-PREFILL-3: a field with no DIRECT label match escalates to the LLM port,
        # which bridges the "Phone" field to the stored "Mobile Number" attribute.
        cid = CampaignId(new_id())
        attrs = [a for a in _full_answers(cid) if a.name != "Phone"]
        attrs.append(_attr(cid, "Mobile Number", "555-0199"))

        class MapLLM:
            asked: list[str] = []

            def complete(self, messages, **kw):
                MapLLM.asked.append(messages[0].content)
                from applicant.ports.driven.llm import LLMResult

                return LLMResult(text="Mobile Number", tier=1, model="fake")

            def list_models(self):
                return ["fake"]

            def is_configured(self):
                return True

        service = _service(InMemoryStorage(), llm=MapLLM())
        result = _resume_full(service, _app(cid), attrs)
        personal = next(v for url, v in result.filled_by_page.items() if "personal" in url)
        assert personal["#phone"] == "555-0199"
        assert result.state == ApplicationState.AWAITING_FINAL_APPROVAL
        assert any("Phone" in c for c in MapLLM.asked)  # the LLM was consulted

    def test_field_mapping_starts_above_l1(self):
        # FR-LLM-4: the field-mapping escalation passes a per-task start_tier > 1 so
        # the ladder begins at the task-appropriate rung (not the trivial L1).
        cid = CampaignId(new_id())
        attrs = [a for a in _full_answers(cid) if a.name != "Phone"]
        attrs.append(_attr(cid, "Mobile Number", "555-0199"))

        class TierCapturingLLM:
            start_tiers: list[int] = []

            def complete(self, messages, *, start_tier=1, **kw):
                TierCapturingLLM.start_tiers.append(start_tier)
                from applicant.ports.driven.llm import LLMResult

                return LLMResult(text="Mobile Number", tier=start_tier, model="fake")

            def list_models(self):
                return ["fake"]

            def is_configured(self):
                return True

        service = _service(InMemoryStorage(), llm=TierCapturingLLM())
        _resume_full(service, _app(cid), attrs)
        assert TierCapturingLLM.start_tiers, "the LLM was consulted for field mapping"
        assert all(t > 1 for t in TierCapturingLLM.start_tiers)

    def test_low_confidence_llm_falls_back_to_soft_error(self):
        cid = CampaignId(new_id())
        attrs = [a for a in _full_answers(cid) if a.name != "Phone"]

        class UnsureLLM:
            def complete(self, messages, **kw):
                from applicant.ports.driven.llm import LLMResult

                return LLMResult(text="NONE", tier=1, model="fake", low_confidence=True)

            def list_models(self):
                return []

            def is_configured(self):
                return True

        service = _service(InMemoryStorage(), llm=UnsureLLM())
        result = _resume_full(service, _app(cid), attrs)
        assert result.state == ApplicationState.BLOCKED_MISSING_ATTR

    def test_sensitive_field_never_escalated_to_llm(self):
        # FR-ATTR-6: a sensitive field must never be LLM-guessed; it declines.
        cid = CampaignId(new_id())
        attrs = [a for a in _full_answers(cid) if a.name != "Gender"]

        class ShouldNotBeAskedLLM:
            asked_labels: list[str] = []

            def complete(self, messages, **kw):
                ShouldNotBeAskedLLM.asked_labels.append(messages[0].content)
                from applicant.ports.driven.llm import LLMResult

                return LLMResult(text="Female", tier=1, model="fake")

            def list_models(self):
                return []

            def is_configured(self):
                return True

        service = _service(InMemoryStorage(), llm=ShouldNotBeAskedLLM())
        result = _resume_full(service, _app(cid), attrs)
        # Gender had no explicit answer → declines (never the LLM guess "Female").
        eeo = next(v for url, v in result.filled_by_page.items() if "voluntary" in url)
        assert eeo["#gender"] == DECLINE_TO_SELF_IDENTIFY
        assert all("gender" not in c.lower() for c in ShouldNotBeAskedLLM.asked_labels)


class _ScreeningBrowser:
    """Minimal browser stub that surfaces ONE field for ``_fill_current_page``."""

    def __init__(self, field):
        self._field = field
        self.filled: dict[str, str] = {}

    def current_state(self, aid):
        from applicant.ports.driven.browser_automation import PageState

        return PageState(url="https://x/form", fields=())

    def detect_fields(self, aid):
        return [self._field]

    def fill_field(self, aid, selector, value):
        self.filled[selector] = value


def _draft_llm(answer: str):
    class _L:
        def complete(self, messages, **kw):
            from applicant.ports.driven.llm import LLMResult

            return LLMResult(text=answer, tier=2, model="fake")

        def list_models(self):
            return ["fake"]

        def is_configured(self):
            return True

    return _L()


def _screening_svc(browser, llm):
    return PrefillService(
        storage=InMemoryStorage(), browser=browser, detection=DetectionMonitor(),
        sandbox=LocalSandbox(), credentials=None, llm=llm,
    )


@pytest.mark.unit
class TestScreeningAnswerGeneration:
    def test_drafts_truthful_answer_and_records_for_review(self):
        # FR-ANSWER-1: a free-text screening question we can't map is DRAFTED from the
        # profile, filled, and recorded for the user's review (FR-RESUME-8).
        from applicant.ports.driven.browser_automation import DetectedField

        cid = CampaignId(new_id())
        fld = DetectedField(
            selector="#q", label="Why do you want this role?",
            field_type="textarea", required=False,
        )
        browser = _ScreeningBrowser(fld)
        svc = _screening_svc(browser, _draft_llm("I am genuinely excited about this opportunity."))
        app = _app(cid)
        result = PrefillResult(application_id=app.id, state=app.status)
        assert svc._fill_current_page(app, [_attr(cid, "current_title", "Engineer")], result) is None
        assert browser.filled["#q"] == "I am genuinely excited about this opportunity."
        assert result.generated_answers and result.generated_answers[0]["label"] == "Why do you want this role?"

    def test_insufficient_facts_asks_the_user(self):
        # The LLM reports it cannot answer truthfully from the profile → the engine does
        # NOT fabricate; a required question blocks for the user (FR-ATTR-5).
        from applicant.ports.driven.browser_automation import DetectedField

        cid = CampaignId(new_id())
        fld = DetectedField(
            selector="#q", label="Do you have an active security clearance?",
            field_type="text", required=True,
        )
        browser = _ScreeningBrowser(fld)
        svc = _screening_svc(browser, _draft_llm("INSUFFICIENT"))
        app = (
            _app(cid)
            .with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.PREFILLING)
        )
        result = PrefillResult(application_id=app.id, state=app.status)
        out = svc._fill_current_page(app, [_attr(cid, "current_title", "Engineer")], result)
        assert out is not None and out.state == ApplicationState.BLOCKED_MISSING_ATTR
        assert "#q" not in browser.filled
        assert result.generated_answers == []

    def test_fabricated_answer_is_rejected_not_filled(self):
        # FR-RESUME-2: a draft that invents a fact (an employer not in the profile) is
        # rejected by the fabrication guard → not filled; the user is asked instead.
        from applicant.ports.driven.browser_automation import DetectedField

        cid = CampaignId(new_id())
        fld = DetectedField(
            selector="#q", label="Describe your most relevant experience.",
            field_type="textarea", required=False,
        )
        browser = _ScreeningBrowser(fld)
        svc = _screening_svc(browser, _draft_llm("I led the engineering team at Tesla for five years."))
        app = _app(cid)
        result = PrefillResult(application_id=app.id, state=app.status)
        assert svc._fill_current_page(app, [_attr(cid, "current_title", "Engineer")], result) is None
        assert "#q" not in browser.filled
        assert result.generated_answers == []


@pytest.mark.unit
class TestErrorProducer:
    def test_fill_failure_materializes_error_pending_action(self):
        # FR-UI-3: a soft fill-failure produces an `error` pending action (the kind
        # now HAS a producer) without crashing the run.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()

        class FlakyBrowser:
            """Delegates to a real PatchrightBrowser but fails one field fill."""

            def __init__(self):
                self._inner = PatchrightBrowser()

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def fill_field(self, aid, selector, value):
                if selector == "#first-name":
                    raise RuntimeError("element detached")
                return self._inner.fill_field(aid, selector, value)

        service = PrefillService(
            storage=storage,
            browser=FlakyBrowser(),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
        )
        _resume_full(service, _app(cid), _full_answers(cid))
        pending = storage.pending_actions.list_open(cid)
        errors = [p for p in pending if p.kind == "error"]
        assert errors, "fill failure -> error pending action"
        assert errors[0].payload.get("field_selector") == "#first-name"


@pytest.mark.unit
class TestEmergencyHandoff:
    def test_handoff_offers_prefilled_values(self):
        # FR-PREFILL-7: emergency copy/paste handoff, opt-in after a fill failure.
        cid = CampaignId(new_id())
        attrs = _full_answers(cid)
        storage = InMemoryStorage()
        service = _service(storage)
        app = _app(cid)
        # Open a session and land on the personal page (simulating a stall there).
        service.prefill_application(app, WORKDAY_URL, attrs)
        service._browser.advance(app.id)  # account -> personal
        resumed = (
            app.with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.ACCOUNT_PREFILL)
            .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
            .with_status(ApplicationState.PREFILLING)
        )
        result = service.emergency_handoff(resumed, attrs)
        assert result.state == ApplicationState.EMERGENCY_DATA_HANDOFF
        assert result.handoff_values  # values to paste
        assert result.handoff_values["First Name"] == "Kevin"
        pending = storage.pending_actions.list_open(cid)
        assert any(p.kind == "emergency_handoff" for p in pending)

    def test_handoff_is_not_the_default_path(self):
        # The default pre-fill never enters EMERGENCY_DATA_HANDOFF.
        cid = CampaignId(new_id())
        service = _service(InMemoryStorage())
        result = _resume_full(service, _app(cid), _full_answers(cid))
        assert result.state != ApplicationState.EMERGENCY_DATA_HANDOFF


@pytest.mark.unit
class TestStealthWiring:
    def test_returning_visitor_after_two_opens_same_tenant(self):
        # FR-STEALTH-3: same per-tenant profile across sessions.
        browser = PatchrightBrowser()
        a1 = ApplicationId(new_id())
        a2 = ApplicationId(new_id())
        browser.open(a1, WORKDAY_URL)
        assert browser.is_returning_visitor(a1) is False
        browser.open(a2, WORKDAY_URL)  # same tenant host
        assert browser.is_returning_visitor(a2) is True

    def test_caveat_is_surfaced(self):
        # FR-STEALTH-5: the honest best-effort caveat is available to the UX.
        assert "best-effort" in PatchrightBrowser().caveat


# === FR-PREFILL-6: full detection-signal forwarding ========================
@pytest.mark.unit
class TestDetectionSignalForwarding:
    def _reach_first_app_page(self, service, app, attrs):
        """Run to the account hand-off, then resume onto the first app page."""
        service.prefill_application(app, WORKDAY_URL, attrs)
        return (
            app.with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.ACCOUNT_PREFILL)
            .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
        )

    def test_http_403_triggers_cautious_pause(self):
        # FR-PREFILL-6: a 403 status (not in detection_signals) pauses cautiously.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = _service(storage)
        app = _app(cid)
        service.prefill_application(app, WORKDAY_URL, _full_answers(cid))
        service._browser.advance(app.id)  # account -> first app page
        service._browser.inject_page_signals(app.id, status=403)
        resumed = (
            app.with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.ACCOUNT_PREFILL)
            .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
            .with_status(ApplicationState.PREFILLING)
        )
        result = service._continue_pages(
            resumed, _full_answers(cid), service_result(app), cautious=True
        )
        assert result.state == ApplicationState.BLOCKED_DETECTION
        assert result.detection_signal == "blocked_403"

    def test_anomalous_redirect_triggers_cautious_pause(self):
        # FR-PREFILL-6: url vs expected_host mismatch pauses cautiously.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = _service(storage)
        app = _app(cid)
        service.prefill_application(app, WORKDAY_URL, _full_answers(cid))
        service._browser.advance(app.id)
        service._browser.inject_page_signals(
            app.id, expected_host="acme.myworkdayjobs.com", url="https://phish.evil/x"
        )
        resumed = (
            app.with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.ACCOUNT_PREFILL)
            .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
            .with_status(ApplicationState.PREFILLING)
        )
        result = service._continue_pages(
            resumed, _full_answers(cid), service_result(app), cautious=True
        )
        assert result.state == ApplicationState.BLOCKED_DETECTION
        assert result.detection_signal == "anomalous_redirect"

    def test_body_marker_triggers_cautious_pause(self):
        # FR-PREFILL-6: a Cloudflare/CAPTCHA body marker pauses cautiously.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = _service(storage)
        app = _app(cid)
        service.prefill_application(app, WORKDAY_URL, _full_answers(cid))
        service._browser.advance(app.id)
        service._browser.inject_page_signals(
            app.id, body="Checking your browser before accessing — Cloudflare"
        )
        resumed = (
            app.with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.ACCOUNT_PREFILL)
            .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
            .with_status(ApplicationState.PREFILLING)
        )
        result = service._continue_pages(
            resumed, _full_answers(cid), service_result(app), cautious=True
        )
        assert result.state == ApplicationState.BLOCKED_DETECTION
        assert result.detection_signal == "cloudflare"

    def test_detection_on_account_page_pauses_instead_of_filling(self):
        # FR-PREFILL-6: a detection signal on the account page (step 3) pauses + hands
        # off; it must NOT fill the account-creation form.
        cid = CampaignId(new_id())
        storage2 = InMemoryStorage()
        app2 = _app(cid)

        class _CaptchaAccountBrowser:
            def __init__(self):
                self._inner = PatchrightBrowser()
                self._filled = False

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def open(self, aid, url):
                state = self._inner.open(aid, url)
                self._inner.inject_page_signals(aid, body="Please complete the captcha")
                return state

            def fill_field(self, aid, selector, value):
                self._filled = True
                return self._inner.fill_field(aid, selector, value)

        browser = _CaptchaAccountBrowser()
        svc = PrefillService(
            storage=storage2,
            browser=browser,
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
        )
        out = svc.prefill_application(app2, WORKDAY_URL, _full_answers(cid), cautious=True)
        # Pauses + hands off (the user takes over to clear the challenge + create the
        # account); crucially the account page is NOT filled (FR-PREFILL-6).
        assert out.state == ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP
        assert out.detection_signal == "captcha"
        assert browser._filled is False, "account page must NOT be filled under detection"


# === FR-PREFILL-4: a mid-flow account-creation page hands off ==============
@pytest.mark.unit
def test_mid_flow_account_creation_triggers_handoff():
    from applicant.adapters.browser.ats import FakePage
    from applicant.ports.driven.browser_automation import DetectedField

    cid = CampaignId(new_id())
    storage = InMemoryStorage()

    class _MidAccountAts:
        name = "midacct"

        def tenant_key(self, url):
            return "midacct:host"

        def pages(self, url):
            return [
                FakePage(url=f"{url}/p1", fields=(
                    DetectedField(selector="#first-name", label="First Name", field_type="text"),
                )),
                # An account-creation step appears MID-FLOW (not the first page).
                FakePage(url=f"{url}/create-account", is_account_create=True, fields=(
                    DetectedField(selector="#email", label="Email Address", field_type="text"),
                )),
                FakePage(url=f"{url}/review", is_final_submit=True),
            ]

    def factory(ats, fingerprint, *, user_data_dir=""):
        from applicant.adapters.browser.page_source import FakePageSource

        return FakePageSource(_MidAccountAts())

    browser = PatchrightBrowser(source_factory=factory)
    service = PrefillService(
        storage=storage,
        browser=browser,
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
    )
    app = _app(cid)
    attrs = [
        _attr(cid, "First Name", "Kevin"),
        _attr(cid, "Email Address", "kevin@kevinhirsch.com"),
    ]
    # First page is NOT account-create, so prefill proceeds, then hits the mid-flow
    # account page and must hand off (AWAITING_ACCOUNT_HUMAN_STEP), not fill past it.
    result = service.prefill_application(app, "https://midacct.example/job/1", attrs)
    assert result.state == ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP
    assert result.account_handoff is True


def service_result(app):
    """Build a fresh PrefillResult for a continue-pages call."""
    return PrefillResult(application_id=app.id, state=app.status)


# === Regression: cautious-mode / blocked-detection notifications actually send,
# === and urgency is scoped correctly (CRITICAL for blocking waits, NORMAL for
# === queued portal items). ==================================================
class _NotifySpy:
    """Spy for the raw NotificationPort (``notify``/``expire``/``is_configured``).

    Only implements the REAL port methods — if a caller regressed to a
    nonexistent ``notify_pending(...)`` (the old bug), it would raise
    ``AttributeError`` right through to the caller (these sites don't swallow
    it the way ``send_scheduled_follow_ups`` does), which pytest reports as a
    test failure/error.
    """

    def __init__(self):
        self.calls: list = []

    def notify(self, notification):
        self.calls.append(notification)
        return "handle"

    def expire(self, dedup_key):
        pass

    def is_configured(self):
        return True


@pytest.mark.unit
class TestCautiousModeDetectionNotification:
    def test_blocked_detection_constructs_valid_pending_action(self):
        # Regression: the PendingAction constructed for the cautious-mode pause
        # used to pass a wrong kwarg (`data=` instead of `payload=`) and omit
        # `title=`, raising TypeError. It must now construct cleanly with both.
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = PrefillService(
            storage=storage,
            browser=PatchrightBrowser(),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
            notification=spy,
        )
        app = _app(cid)
        service.prefill_application(app, WORKDAY_URL, _full_answers(cid))
        service._browser.advance(app.id)  # account -> first app page
        service._browser.inject_page_signals(
            app.id, body="Checking your browser before accessing — Cloudflare"
        )
        resumed = (
            app.with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.ACCOUNT_PREFILL)
            .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
            .with_status(ApplicationState.PREFILLING)
        )
        result = service._continue_pages(
            resumed, _full_answers(cid), service_result(app), cautious=True
        )
        assert result.state == ApplicationState.BLOCKED_DETECTION
        pending = storage.pending_actions.list_open(cid)
        blockers = [p for p in pending if p.kind == "detection_blocker"]
        assert blockers, "cautious-mode pause -> a real pending action, not a TypeError"
        assert blockers[0].title  # title= was populated (not omitted)
        assert blockers[0].payload.get("signal_type") == "cloudflare"
        assert blockers[0].application_id == app.id

    def test_blocked_detection_calls_the_real_notify_method(self):
        # Regression: this path used to call a nonexistent `notify_pending(...)`.
        # It must call the real NotificationPort.notify(...) with a Notification.
        from applicant.ports.driven.notification import Notification

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = PrefillService(
            storage=storage,
            browser=PatchrightBrowser(),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
            notification=spy,
        )
        app = _app(cid)
        service.prefill_application(app, WORKDAY_URL, _full_answers(cid))
        service._browser.advance(app.id)
        service._browser.inject_page_signals(app.id, status=403)
        resumed = (
            app.with_status(ApplicationState.SANDBOX_PROVISIONING)
            .with_status(ApplicationState.ACCOUNT_PREFILL)
            .with_status(ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP)
            .with_status(ApplicationState.PREFILLING)
        )
        spy.calls.clear()  # drop the earlier account-hand-off notification
        service._continue_pages(
            resumed, _full_answers(cid), service_result(app), cautious=True
        )
        assert len(spy.calls) == 1
        assert isinstance(spy.calls[0], Notification)


@pytest.mark.unit
class TestNotificationUrgencyScoping:
    """urgency must be scoped: CRITICAL for blocking hand-offs the agent is
    frozen on, NORMAL for queued portal items the agent keeps working past."""

    def test_emit_waiting_uses_critical_urgency(self):
        # _emit_waiting backs 2FA / detection / account-handoff / emergency —
        # the agent is frozen mid-flow, so this must be CRITICAL (never
        # deferred by quiet hours).
        from applicant.ports.driven.notification import NotificationUrgency

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = PrefillService(
            storage=storage,
            browser=PatchrightBrowser(),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
            notification=spy,
        )
        app = _app(cid)
        service.prefill_application(app, WORKDAY_URL, _full_answers(cid))
        assert spy.calls, "account hand-off emits a notification via _emit_waiting"
        assert spy.calls[0].urgency == NotificationUrgency.CRITICAL

    def test_emit_pending_uses_normal_urgency_not_critical(self):
        # Regression: _emit_pending (backs agent_question/error — a queued
        # Portal item, not a frozen-agent wait) must be NORMAL, NOT CRITICAL.
        # An earlier draft of the fix incorrectly applied CRITICAL here too.
        from applicant.ports.driven.notification import NotificationUrgency

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = PrefillService(
            storage=storage,
            browser=PatchrightBrowser(),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
            notification=spy,
        )
        _resume_full(service, _app(cid), _full_answers(cid))
        # The essay screening question ("#q-why") drives an agent_question
        # pending action via _emit_pending/_emit_agent_question.
        agent_question_calls = [
            n for n in spy.calls if "Question needs your input" in n.title
        ]
        assert agent_question_calls, "agent_question notification was sent"
        assert all(
            n.urgency == NotificationUrgency.NORMAL for n in agent_question_calls
        )
        assert all(
            n.urgency != NotificationUrgency.CRITICAL for n in agent_question_calls
        )

    def test_emit_error_uses_normal_urgency_not_critical(self):
        # Same regression as above, exercised via the `error` pending-action
        # producer (a soft fill failure), not `agent_question`.
        from applicant.ports.driven.notification import NotificationUrgency

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()

        class FlakyBrowser:
            def __init__(self):
                self._inner = PatchrightBrowser()

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def fill_field(self, aid, selector, value):
                if selector == "#first-name":
                    raise RuntimeError("element detached")
                return self._inner.fill_field(aid, selector, value)

        service = PrefillService(
            storage=storage,
            browser=FlakyBrowser(),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
            notification=spy,
        )
        _resume_full(service, _app(cid), _full_answers(cid))
        error_calls = [n for n in spy.calls if "Could not fill field" in n.title]
        assert error_calls, "error-producer notification was sent"
        assert all(n.urgency == NotificationUrgency.NORMAL for n in error_calls)

    def test_planner_path_blocked_detection_uses_critical_urgency(self):
        # The CAPTCHA/oauth detection-block site in the planner op-execution
        # path (kind="blocked_detection") is also a frozen-agent hand-off, so
        # it must be CRITICAL like _emit_waiting, not NORMAL like _emit_pending.
        from applicant.core.entities.plan import Plan, StopOp
        from applicant.ports.driven.browser_automation import PageState
        from applicant.ports.driven.notification import NotificationUrgency

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        spy = _NotifySpy()
        service = PrefillService(
            storage=storage,
            browser=PatchrightBrowser(),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
            notification=spy,
        )
        app = _app(cid)
        state = PageState(url=f"{WORKDAY_URL}/apply", fields=())
        plan = Plan(ops=(StopOp(reason="captcha"),))
        result = service_result(app)

        terminal, reflection, _steps = service._run_plan_ops(app, state, plan, {}, result)

        assert reflection is None
        assert terminal is not None
        assert terminal.state == ApplicationState.BLOCKED_DETECTION
        assert terminal.detection_signal == "captcha"
        assert len(spy.calls) == 1
        assert spy.calls[0].urgency == NotificationUrgency.CRITICAL


# === #7: prefill blocked-state pings use a ref NotificationService can expire =
@pytest.mark.unit
def test_resolving_prefill_block_expires_its_ping():
    """#7: a prefill blocked-state ping uses the consistent ``decision:prefill:...``
    key so resolving the block via NotificationService.acted expires it. The old
    un-prefixed ``{app}:{kind}`` key could never be expired by ``acted``."""
    from applicant.adapters.notification.apprise_notifier import AppriseNotifier
    from applicant.application.services.notification_service import NotificationService
    from applicant.application.services.prefill_service import ping_dedup_key, ping_ref

    storage = InMemoryStorage()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    service = PrefillService(
        storage=storage,
        browser=PatchrightBrowser(),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        notification=notifier,
    )
    cid = CampaignId(new_id())
    app = _app(cid)
    # Drive to the account-creation hand-off -> emits an account_human_step ping.
    service.prefill_application(app, WORKDAY_URL, _full_answers(cid))

    key = ping_dedup_key(app.id, "account_human_step")
    assert notifier.is_active(key)  # the blocked-state ping is pending

    # Resolving the block expires the SAME ping via the shared decision: ref.
    NotificationService(notifier).acted(ping_ref(app.id, "account_human_step"))
    assert not notifier.is_active(key)
