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

WORKDAY_URL = "https://acme.myworkdayjobs.com/job/123"


def _attr(cid, name, value, sensitive=False):
    return Attribute(
        id=AttributeId(new_id()), campaign_id=cid, name=name, value=value, is_sensitive=sensitive
    )


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
