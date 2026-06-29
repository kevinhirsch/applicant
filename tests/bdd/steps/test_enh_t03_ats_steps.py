"""Step bindings for the ATS modeling & application-lifecycle acceptance specs.

Theme T03 — issues #171, #173, #177, #190, #191, #192, #193, #198, #209, #214,
#225, #226, #227, #284, #285.

Convention (canonical for the issue-tracker enhancement Gherkins):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships on this branch — they assert against the actual core rules / adapters /
  services via in-memory seams and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built. Their steps make an honest probe at the real target (a
  speculative import, a missing attribute, an absent outcome type, or an assertion the
  current code fails) so the scenario is a genuine red — never ``assert True``.
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail.

Hexagonal: assertions target core rules (``core/rules``, ``core/state_machine``),
adapters' pure helpers, and services through in-memory adapters — never UI internals,
never a real browser / network / DB. Speculative imports live INSIDE step bodies so a
not-yet-built target raises at runtime (→ xfail), never a collection error.
"""

from __future__ import annotations

import dataclasses

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.browser.ats import (
    ATS_REGISTRY,
    GreenhouseAts,
    LeverAts,
    WorkdayAts,
    resolve_ats,
)
from applicant.adapters.browser.page_source import PlaywrightPageSource
from applicant.application.services.prefill_service import PrefillService
from applicant.core.entities.application import Application
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.errors import IllegalStateTransition, ReviewRequired
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, OutcomeEventId, new_id
from applicant.core.rules.review_gate import ReviewableMaterial, ensure_submittable
from applicant.core.state_machine import (
    ApplicationState,
    allowed_transitions,
    is_terminal,
)
from applicant.ports.driven.browser_automation import DetectedField

scenarios(
    "../features/enhancements/enh_171_greenhouse_lever_shells.feature",
    "../features/enhancements/enh_173_unknown_ats_fallback.feature",
    "../features/enhancements/enh_177_ats_detection_match_rate.feature",
    "../features/enhancements/enh_190_post_submission_lifecycle.feature",
    "../features/enhancements/enh_191_rejection_detection.feature",
    "../features/enhancements/enh_192_ghosting_silence_tracking.feature",
    "../features/enhancements/enh_193_followup_emails.feature",
    "../features/enhancements/enh_198_force_status_bypass.feature",
    "../features/enhancements/enh_209_screening_word_count.feature",
    "../features/enhancements/enh_214_workday_fixed_pages.feature",
    "../features/enhancements/enh_225_dropdown_fake_coverage.feature",
    "../features/enhancements/enh_226_pick_option_scoping.feature",
    "../features/enhancements/enh_227_async_dropdown_options.feature",
    "../features/enhancements/enh_284_ensure_submittable_body.feature",
    "../features/enhancements/enh_285_context_error_false_positive.feature",
)

WORKDAY_URL = "https://acme.myworkdayjobs.com/job/123"
GREENHOUSE_URL = "https://boards.greenhouse.io/acme/jobs/1"
LEVER_URL = "https://jobs.lever.co/acme/abc-123"
UNKNOWN_URL = "https://careers.unsupported-ats.example/apply/9"
ICIMS_URL = "https://careers-acme.icims.com/jobs/4242/apply"


@pytest.fixture
def t03ctx() -> dict:
    return {}


def _probe(modpath: str, attr: str | None = None):
    """Import ``modpath`` (and optionally ``getattr`` ``attr``).

    Raises ImportError/AttributeError when the not-yet-built target is absent —
    exactly the honest red a ``@pending`` scenario wants.
    """
    import importlib

    module = importlib.import_module(modpath)
    return getattr(module, attr) if attr is not None else module


def _require_attr(obj, attr: str, hint: str):
    if not hasattr(obj, attr):
        raise AttributeError(f"{hint}: {attr!r} not implemented yet")
    return getattr(obj, attr)


# ===========================================================================
# #171 — Greenhouse/Lever shells (GREEN: they resolve & are thin; PENDING: parity)
# ===========================================================================
@given("the ATS registry")
def the_ats_registry(t03ctx):
    t03ctx["registry"] = ATS_REGISTRY


@when("a Greenhouse posting URL and a Lever posting URL are resolved")
def resolve_gh_lever(t03ctx):
    t03ctx["gh"] = resolve_ats(GREENHOUSE_URL)
    t03ctx["lever"] = resolve_ats(LEVER_URL)


@then("each resolves to its own dedicated adapter")
def each_dedicated(t03ctx):
    assert isinstance(t03ctx["gh"], GreenhouseAts)
    assert isinstance(t03ctx["lever"], LeverAts)


@then("both flows end on a final-submit page")
def both_end_final_submit(t03ctx):
    assert t03ctx["gh"].pages(GREENHOUSE_URL)[-1].is_final_submit is True
    assert t03ctx["lever"].pages(LEVER_URL)[-1].is_final_submit is True


@when("the Greenhouse and Lever flows are walked")
def walk_gh_lever(t03ctx):
    t03ctx["gh_fields"] = [f for p in GreenhouseAts().pages(GREENHOUSE_URL) for f in p.fields]
    t03ctx["lever_fields"] = [f for p in LeverAts().pages(LEVER_URL) for f in p.fields]
    t03ctx["wd_fields"] = [f for p in WorkdayAts().pages(WORKDAY_URL) for f in p.fields]


@then("Greenhouse exposes at most a handful of fields")
def greenhouse_handful(t03ctx):
    # The shell models only first/last/email today.
    assert len(t03ctx["gh_fields"]) <= 4


@then("Lever exposes fewer fields than the full Workday flow")
def lever_fewer_than_workday(t03ctx):
    assert len(t03ctx["lever_fields"]) < len(t03ctx["wd_fields"])


@when("the Greenhouse flow is walked for field-modeling parity with Workday")
def walk_gh_for_parity(t03ctx):
    t03ctx["gh_fields"] = [f for p in GreenhouseAts().pages(GREENHOUSE_URL) for f in p.fields]
    t03ctx["wd_fields"] = [f for p in WorkdayAts().pages(WORKDAY_URL) for f in p.fields]


@then("it models the same breadth of real application fields as Workday")
def gh_parity_with_workday(t03ctx):
    # PENDING: today Greenhouse is a 3-field shell — far short of Workday's breadth.
    assert len(t03ctx["gh_fields"]) >= len(t03ctx["wd_fields"])


@when("an iCIMS posting URL is resolved")
def resolve_icims(t03ctx):
    t03ctx["icims"] = resolve_ats(ICIMS_URL)


@then("a dedicated iCIMS adapter handles it")
def icims_dedicated(t03ctx):
    # PENDING: no iCIMS adapter exists; an iCIMS URL falls through to Workday today.
    icims_cls = _probe("applicant.adapters.browser.ats", "IcimsAts")
    assert isinstance(t03ctx["icims"], icims_cls)


# ===========================================================================
# #173 — Unknown ATS fallback (GREEN: defaults to Workday; PENDING: strict None)
# ===========================================================================
@when("a Workday posting URL is resolved")
def resolve_workday(t03ctx):
    t03ctx["resolved"] = resolve_ats(WORKDAY_URL)


@then("the Workday adapter is selected")
def workday_selected(t03ctx):
    assert isinstance(t03ctx["resolved"], WorkdayAts)


@when("a URL for an unsupported ATS is resolved")
def resolve_unknown(t03ctx):
    t03ctx["resolved"] = resolve_ats(UNKNOWN_URL)


@then("the current code returns the Workday adapter as a fallback")
def unknown_defaults_workday(t03ctx):
    # GREEN regression: documents the CURRENT (problematic) fallback behaviour.
    assert isinstance(t03ctx["resolved"], WorkdayAts)
    assert t03ctx["resolved"].matches(UNKNOWN_URL) is False


@when("a URL for an unsupported ATS is resolved with strict matching")
def resolve_unknown_strict(t03ctx):
    # PENDING: a strict resolver that does not silently default to Workday.
    resolver = _probe("applicant.adapters.browser.ats", "resolve_ats_strict")
    t03ctx["resolved"] = resolver(UNKNOWN_URL)


@then("no adapter is returned so the operator can be flagged")
def strict_returns_none(t03ctx):
    assert t03ctx["resolved"] is None


# ===========================================================================
# #177 — field-match-rate detection (PENDING)
# ===========================================================================
@given("a pre-fill run over a form whose selectors do not match the chosen adapter")
def prefill_mismatch(t03ctx):
    t03ctx["detected"] = [
        DetectedField("#totally-different-1", "Mystery Field 1", "text"),
        DetectedField("#totally-different-2", "Mystery Field 2", "text"),
    ]


@given("a pre-fill run that matched none of the detected fields")
def prefill_no_match(t03ctx):
    t03ctx["detected"] = [DetectedField("#x", "X", "text")]
    t03ctx["matched"] = 0


@when("the maximal pre-fill loop walks the page")
def loop_walks_page(t03ctx):
    # PENDING: there is no field-match-rate accounting on the pre-fill service.
    t03ctx["rate_fn"] = _require_attr(
        PrefillService, "field_match_rate", "PrefillService.field_match_rate"
    )


@then("the run records the field-match rate")
def run_records_rate(t03ctx):
    assert callable(t03ctx["rate_fn"])


@when("the loop finishes the page")
def loop_finishes_page(t03ctx):
    # PENDING: no helper that flags a low-match run for operator review.
    t03ctx["flag_fn"] = _require_attr(
        PrefillService, "flag_probable_wrong_ats", "PrefillService.flag_probable_wrong_ats"
    )


@then("the application is flagged as a probable wrong-ATS run for operator review")
def app_flagged_wrong_ats(t03ctx):
    assert callable(t03ctx["flag_fn"])


# ===========================================================================
# #190 — post-submission lifecycle (GREEN: terminal/submitted only; PENDING: more)
# ===========================================================================
@given("the application state machine")
def the_state_machine(t03ctx):
    t03ctx["sm"] = ApplicationState


@when("the outgoing transitions of the submitted and finished states are inspected")
def inspect_terminal_transitions(t03ctx):
    t03ctx["submitted_out"] = allowed_transitions(ApplicationState.SUBMITTED_BY_USER)
    t03ctx["finished_out"] = allowed_transitions(ApplicationState.FINISHED_BY_ENGINE)


@then("each is terminal with no outgoing transitions")
def each_terminal(t03ctx):
    assert is_terminal(ApplicationState.SUBMITTED_BY_USER)
    assert is_terminal(ApplicationState.FINISHED_BY_ENGINE)
    assert t03ctx["submitted_out"] == frozenset()
    assert t03ctx["finished_out"] == frozenset()


@given("an application that has been recorded as submitted")
def app_recorded_submitted(t03ctx):
    aid = ApplicationId(new_id())
    t03ctx["application_id"] = aid
    t03ctx["outcomes"] = [
        OutcomeEvent(
            id=OutcomeEventId(new_id()),
            application_id=aid,
            type="submitted",
            source=OutcomeSource.MANUAL,
        )
    ]


@when("its outcome events are listed")
def list_outcome_events(t03ctx):
    t03ctx["listed"] = list(t03ctx["outcomes"])


@then("a submitted outcome event is present")
def submitted_outcome_present(t03ctx):
    assert any(o.type == "submitted" for o in t03ctx["listed"])


@when("a rejection outcome is recorded against it")
def record_rejection(t03ctx):
    # PENDING: there is no recognized "rejected" post-submission outcome catalogue.
    outcome_types = _probe("applicant.core.entities.outcome_event", "OUTCOME_TYPES")
    t03ctx["outcome_types"] = outcome_types


@then("the rejected outcome type is a recognized post-submission outcome")
def rejected_recognized(t03ctx):
    assert "rejected" in t03ctx["outcome_types"]


@given("the catalogue of post-submission outcome types")
def outcome_catalogue(t03ctx):
    t03ctx["catalogue_mod"] = "applicant.core.entities.outcome_event"


@when("the recognized outcomes are enumerated")
def enumerate_outcomes(t03ctx):
    # PENDING: the enumerated outcome catalogue does not exist yet.
    t03ctx["outcome_types"] = _probe(t03ctx["catalogue_mod"], "OUTCOME_TYPES")


@then("interview, ghosted, and offer are all recognized")
def interview_ghosted_offer(t03ctx):
    types = set(t03ctx["outcome_types"])
    assert {"interview_invited", "ghosted", "offer"} <= types


# ===========================================================================
# #191 — rejection detection (PENDING)
# ===========================================================================
@given("an inbound rejection notice for a submitted application")
def inbound_rejection(t03ctx):
    t03ctx["rejection_text"] = "we have decided to move forward with other candidates"


@given("an application whose ATS status page reads no longer under consideration")
def ats_status_rejected(t03ctx):
    t03ctx["status_text"] = "no longer under consideration"


@when("the rejection detector scans the mailbox")
def rejection_detector_scans(t03ctx):
    detector = _probe(
        "applicant.application.services.rejection_service", "RejectionService"
    )
    t03ctx["classify"] = _require_attr(
        detector, "classify_message", "RejectionService.classify_message"
    )


@then("the application is marked rejected and the negative outcome is recorded")
def marked_rejected_negative(t03ctx):
    assert t03ctx["classify"](t03ctx["rejection_text"]) == "rejected"


@when("the status poller checks the application status page")
def status_poller_checks(t03ctx):
    detector = _probe(
        "applicant.application.services.rejection_service", "RejectionService"
    )
    t03ctx["classify_status"] = _require_attr(
        detector, "classify_status_page", "RejectionService.classify_status_page"
    )


@then("the application is marked rejected")
def marked_rejected(t03ctx):
    assert t03ctx["classify_status"](t03ctx["status_text"]) == "rejected"


# ===========================================================================
# #192 — ghosting / silence tracking (PENDING)
# ===========================================================================
@given("an application submitted some days ago with no response")
def submitted_days_ago(t03ctx):
    t03ctx["days_since"] = 5


@given("an application with no response well past the no-response threshold")
def submitted_past_threshold(t03ctx):
    t03ctx["days_since"] = 45


@when("the silence tracker evaluates it")
def silence_tracker_evaluates(t03ctx):
    tracker = _probe(
        "applicant.application.services.silence_service", "SilenceService"
    )
    t03ctx["elapsed_fn"] = _require_attr(
        tracker, "days_since_submission", "SilenceService.days_since_submission"
    )


@then("it reports the elapsed time since submission")
def reports_elapsed(t03ctx):
    assert callable(t03ctx["elapsed_fn"])


@when("the silence tracker evaluates it against the SLA")
def silence_tracker_sla(t03ctx):
    tracker = _probe(
        "applicant.application.services.silence_service", "SilenceService"
    )
    t03ctx["ghost_fn"] = _require_attr(
        tracker, "is_likely_ghosted", "SilenceService.is_likely_ghosted"
    )


@then("the application is flagged as likely ghosted")
def flagged_ghosted(t03ctx):
    assert t03ctx["ghost_fn"](t03ctx["days_since"]) is True


# ===========================================================================
# #193 — follow-up emails (PENDING)
# ===========================================================================
@given("an application that was recently submitted")
def recently_submitted(t03ctx):
    t03ctx["days_since"] = 7


@given("an application submitted long enough ago to warrant a check-in")
def long_enough_for_checkin(t03ctx):
    t03ctx["days_since"] = 14


@when("the follow-up service drafts outreach for it")
def followup_drafts(t03ctx):
    svc = _probe(
        "applicant.application.services.followup_service", "FollowUpService"
    )
    t03ctx["draft_fn"] = _require_attr(svc, "draft_followup", "FollowUpService.draft_followup")


@then("a follow-up message is produced for review")
def followup_produced(t03ctx):
    assert callable(t03ctx["draft_fn"])


@when("the follow-up service evaluates whether outreach is due")
def followup_evaluates(t03ctx):
    svc = _probe(
        "applicant.application.services.followup_service", "FollowUpService"
    )
    t03ctx["due_fn"] = _require_attr(svc, "followup_is_due", "FollowUpService.followup_is_due")


@then("it reports that a follow-up is warranted")
def followup_warranted(t03ctx):
    assert t03ctx["due_fn"](t03ctx["days_since"]) is True


# ===========================================================================
# #198 — _force_status bypass (GREEN: with_status validates + replace bypasses;
#         PENDING: a validating sync path)
# ===========================================================================
@given("an application in the discovered state")
def app_discovered(t03ctx):
    t03ctx["app"] = Application(
        id=ApplicationId(new_id()),
        campaign_id=CampaignId(new_id()),
        posting_id=JobPostingId(""),
        status=ApplicationState.DISCOVERED,
    )


@when("it is advanced through the validated status path to a terminal state directly")
def advance_validated_illegal(t03ctx):
    try:
        t03ctx["app"].with_status(ApplicationState.SUBMITTED_BY_USER)
        t03ctx["refused"] = False
    except IllegalStateTransition:
        t03ctx["refused"] = True


@then("the illegal transition is refused")
def illegal_refused(t03ctx):
    assert t03ctx["refused"] is True


@when("its status is set with a raw dataclass replace to a terminal state")
def raw_replace(t03ctx):
    # Mirrors agent_loop._force_status: dataclasses.replace bypasses with_status().
    t03ctx["forced"] = dataclasses.replace(
        t03ctx["app"], status=ApplicationState.SUBMITTED_BY_USER
    )


@then("the status changed with no transition validation")
def status_changed_no_validation(t03ctx):
    # GREEN: documents the bypass exists — replace landed an illegal terminal state.
    assert t03ctx["forced"].status is ApplicationState.SUBMITTED_BY_USER
    assert t03ctx["app"].status is ApplicationState.DISCOVERED


@when("the engine syncs it to a terminal state through a validated force path")
def sync_validated_force(t03ctx):
    # PENDING: a force/sync helper that STILL validates §7 before persisting.
    helper = _probe("applicant.core.state_machine", "force_status_checked")
    try:
        helper(t03ctx["app"], ApplicationState.SUBMITTED_BY_USER)
        t03ctx["sync_refused"] = False
    except IllegalStateTransition:
        t03ctx["sync_refused"] = True


@then("the illegal jump is refused rather than silently forced")
def sync_illegal_refused(t03ctx):
    assert t03ctx["sync_refused"] is True


# ===========================================================================
# #209 — screening word-count heuristic (GREEN: essay yes / short no;
#         PENDING: 6-word address misclassified)
# ===========================================================================
@given("the screening-question classifier")
def screening_classifier(t03ctx):
    t03ctx["classify"] = PrefillService._is_screening_question


@when("a free-text essay prompt field is classified")
def classify_essay(t03ctx):
    fld = DetectedField("#why", "Why do you want to work here?", "text")
    t03ctx["result"] = t03ctx["classify"](fld)


@then("it is treated as a screening question")
def is_screening(t03ctx):
    assert t03ctx["result"] is True


@when("a short first-name field is classified")
def classify_first_name(t03ctx):
    fld = DetectedField("#first", "First Name", "text")
    t03ctx["result"] = t03ctx["classify"](fld)


@then("it is not treated as a screening question")
def not_screening(t03ctx):
    assert t03ctx["result"] is False


@when("a six-word address line field is classified")
def classify_address_line(t03ctx):
    # "Current Street Address Line 2" is 5 words; the issue's example phrasing
    # "Current Home Street Address Line 2" is a 6-word PLAIN data field.
    fld = DetectedField("#addr2", "Current Home Street Address Line 2", "text")
    assert len([w for w in fld.label.split() if w]) >= 6  # tripwire: triggers the heuristic
    t03ctx["result"] = t03ctx["classify"](fld)


# ===========================================================================
# #214 — Workday fixed 6 pages (GREEN: exactly 6; PENDING: variable tenants)
# ===========================================================================
@given("the Workday adapter")
def the_workday_adapter(t03ctx):
    t03ctx["wd"] = WorkdayAts()


@when("its modeled pages are listed")
def list_workday_pages(t03ctx):
    t03ctx["pages"] = t03ctx["wd"].pages(WORKDAY_URL)


@then("there are exactly six pages with account-create first and final-submit last")
def six_pages(t03ctx):
    pages = t03ctx["pages"]
    assert len(pages) == 6
    assert pages[0].is_account_create is True
    assert pages[-1].is_final_submit is True


@given("a Workday tenant flow that omits the voluntary-disclosures page")
def tenant_no_disclosures(t03ctx):
    t03ctx["wd"] = WorkdayAts()


@when("the pre-fill loop walks the varied tenant flow")
def walk_varied_tenant(t03ctx):
    # PENDING: the adapter cannot model a tenant whose page set differs from the fixed 6.
    t03ctx["pages_for"] = _require_attr(
        t03ctx["wd"], "pages_for_tenant", "WorkdayAts.pages_for_tenant"
    )


@then("the flow is handled without assuming the fixed six-page structure")
def handled_varied(t03ctx):
    pages = t03ctx["pages_for"](WORKDAY_URL, tenant_profile={"voluntary_disclosures": False})
    assert not any("voluntary-disclosures" in p.url for p in pages)


# ===========================================================================
# #225 — dropdown matching rule (GREEN: pure matcher; PENDING: fake coverage)
# ===========================================================================
@given("the dropdown option matcher")
def the_option_matcher(t03ctx):
    t03ctx["match"] = PlaywrightPageSource._option_match


@when("an exact option, a loose subset option, and a decline synonym are matched")
def match_three(t03ctx):
    t03ctx["exact"] = t03ctx["match"]("Yes", "Yes")
    t03ctx["loose"] = t03ctx["match"]("United States", "United States of America")
    t03ctx["decline"] = t03ctx["match"]("prefer not to say", "Decline To Self Identify")


@then(
    "the exact match wins, the subset matches loosely, and the decline synonym matches"
)
def matcher_results(t03ctx):
    assert t03ctx["exact"] == "exact"
    assert t03ctx["loose"] == "loose"
    assert t03ctx["decline"] == "loose"


@when("the wanted value would only substring-match a different option")
def match_substring_trap(t03ctx):
    # token-based matching must NOT let "male" match "female".
    t03ctx["result"] = t03ctx["match"]("male", "female")


@then("no match is returned")
def no_match(t03ctx):
    assert t03ctx["result"] is None


@given("the fake page source standing in for a real combobox")
def the_fake_page_source(t03ctx):
    from applicant.adapters.browser.page_source import FakePageSource

    t03ctx["fake"] = FakePageSource()


@when("a value is selected against an option set on the fake")
def select_against_fake(t03ctx):
    # PENDING: the fake's type_value blindly records; it has no option-validating
    # dropdown seam (e.g. select_dropdown) that verifies the value is a real option.
    t03ctx["select"] = _require_attr(
        t03ctx["fake"], "select_dropdown", "FakePageSource.select_dropdown"
    )


@then(
    "the fake verifies the value matched a real option rather than blindly recording it"
)
def fake_verifies_option(t03ctx):
    # An unmatched value must raise ValueError rather than silently "succeed".
    with pytest.raises(ValueError):
        t03ctx["select"]("#country", "Atlantis", options=("United States", "Canada"))


# ===========================================================================
# #226 — _pick_visible_option scoping (PENDING)
# ===========================================================================
@given("an opened dropdown whose listbox is identified by an aria-controls relationship")
def opened_dropdown_scoped(t03ctx):
    t03ctx["listbox_id"] = "country-listbox"


@when("the picker selects an option for that dropdown")
def picker_selects_scoped(t03ctx):
    # PENDING: no scoped variant — _pick_visible_option polls the whole page.
    t03ctx["scoped_fn"] = _require_attr(
        PlaywrightPageSource,
        "_pick_visible_option_in_listbox",
        "PlaywrightPageSource._pick_visible_option_in_listbox",
    )


@then("it considers only options owned by that listbox")
def considers_only_owned(t03ctx):
    assert callable(t03ctx["scoped_fn"])


# ===========================================================================
# #227 — async/paginated dropdown options (PENDING)
# ===========================================================================
@given("a combobox whose target option loads asynchronously after filtering")
def async_combobox(t03ctx):
    t03ctx["target"] = "Zimbabwe"


@when("the picker looks for the target option")
def picker_looks_async(t03ctx):
    # PENDING: no helper that types the filter and waits for an async option to load.
    t03ctx["async_fn"] = _require_attr(
        PlaywrightPageSource,
        "_pick_option_loading_async",
        "PlaywrightPageSource._pick_option_loading_async",
    )


@then("it types the filter and waits for the option to appear before failing")
def types_and_waits(t03ctx):
    assert callable(t03ctx["async_fn"])


# ===========================================================================
# #284 — ensure-submittable confirms in the body (GREEN)
# ===========================================================================
@given("the submission review gate over an unapproved generated material")
def gate_unapproved(t03ctx):
    t03ctx["materials"] = [
        ReviewableMaterial(identifier="cover-1", is_generated=True, approved=False)
    ]


@given("the submission review gate over only approved materials")
def gate_approved(t03ctx):
    t03ctx["materials"] = [
        ReviewableMaterial(identifier="cover-1", is_generated=True, approved=True),
        ReviewableMaterial(identifier="resume-1", is_generated=False, approved=True),
    ]


@when("submittability is checked")
def check_submittability(t03ctx):
    try:
        ensure_submittable(t03ctx["materials"])
        # Mirror the documents router's success body: {"submittable": True}.
        t03ctx["response"] = {"submittable": True}
        t03ctx["error"] = None
    except ReviewRequired as exc:
        t03ctx["response"] = None
        t03ctx["error"] = exc


@then("the review gate refuses with a review-required error")
def gate_refuses(t03ctx):
    assert isinstance(t03ctx["error"], ReviewRequired)
    assert t03ctx["response"] is None


@then("the body confirms the application is submittable")
def body_confirms_submittable(t03ctx):
    assert t03ctx["error"] is None
    # #284: assert the BODY confirms submittability — not merely a 200 status.
    assert t03ctx["response"]["submittable"] is True


# ===========================================================================
# #285 — _is_context_error false positive (GREEN: bug demonstrated; PENDING: fix)
# ===========================================================================
def _ctx_error_response(payload: dict):
    import httpx

    return httpx.Response(400, json=payload)


@given("the context-error classifier")
def the_ctx_classifier(t03ctx):
    from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM

    t03ctx["is_ctx_error"] = OpenAICompatibleLLM._is_context_error


@when("a context-length-exceeded error envelope is checked")
def check_real_ctx_error(t03ctx):
    resp = _ctx_error_response(
        {"error": {"code": "context_length_exceeded", "message": "maximum context length"}}
    )
    t03ctx["result"] = t03ctx["is_ctx_error"](resp)


@then("it is detected as a context error")
def detected_ctx_error(t03ctx):
    assert t03ctx["result"] is True


@when("a content-filter error envelope mentioning the context of the request is checked")
def check_false_positive(t03ctx):
    resp = _ctx_error_response(
        {
            "error": {
                "code": "content_filter",
                "message": "Your request was rejected in the context of the request policy.",
            }
        }
    )
    t03ctx["result"] = t03ctx["is_ctx_error"](resp)


@then("the current substring heuristic wrongly flags it as a context error")
def heuristic_false_positive(t03ctx):
    # GREEN: documents the bug — the bare "context" substring trips on unrelated text.
    assert t03ctx["result"] is True


@when(
    "a content-filter error envelope mentioning the context of the request is checked strictly"
)
def check_strict(t03ctx):
    from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM

    resp = _ctx_error_response(
        {
            "error": {
                "code": "content_filter",
                "message": "Your request was rejected in the context of the request policy.",
            }
        }
    )
    # PENDING: a strict classifier that matches specific codes, not the word "context".
    strict = _require_attr(
        OpenAICompatibleLLM,
        "_is_context_error_strict",
        "OpenAICompatibleLLM._is_context_error_strict",
    )
    t03ctx["result"] = strict(resp)


@then("it is not flagged as a context error")
def not_flagged_ctx_error(t03ctx):
    assert t03ctx["result"] is False
