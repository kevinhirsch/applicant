"""Step bindings for the "spirit-of-product" enhancement specs (issues #367-#372).

These six issues are untracked, in-the-spirit safety/quality holes filed against the
autonomous applier. They follow the canonical issue-tracker enhancement pattern:

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships on this branch — they assert against the actual core rules / ports /
  services through in-memory adapters and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for the residual gap each
  issue identifies. Their steps make an honest probe at the real intended seam (a
  speculative import, a missing attribute, an absent service method, or an assertion
  the current code fails) so the scenario is a genuine red — never ``assert True``.
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail, so the
  spec is collected and tracked without breaking the green gate. When the feature
  lands, drop the tag and the scenario becomes a hard regression gate.

Hexagonal: assertions target core rules (``core/rules``), driving/driven ports, and
application services through in-memory adapters — never UI internals, never a real
socket / DB / browser. Speculative imports for not-yet-built targets live INSIDE the
step body so absence → runtime error → xfail, never a collection error.
"""

from __future__ import annotations

import importlib

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.services.prefill_service import PrefillResult
from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP, clamp_throughput
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id

scenarios(
    "../features/enhancements/enh_367_scam_ghost_job_guard.feature",
    "../features/enhancements/enh_368_reapply_cooldown_guard.feature",
    "../features/enhancements/enh_369_work_auth_eligibility_filter.feature",
    "../features/enhancements/enh_370_ats_parseability_selfcheck.feature",
    "../features/enhancements/enh_371_per_company_volume_cap.feature",
    "../features/enhancements/enh_372_submission_snapshot.feature",
)


@pytest.fixture
def spiritctx() -> dict:
    return {}


def _probe(modpath: str, attr: str | None = None):
    """Import ``modpath`` (and optionally ``getattr`` ``attr``).

    Raises ImportError/AttributeError when the not-yet-built target is absent —
    exactly the honest red a ``@pending`` scenario wants.
    """
    module = importlib.import_module(modpath)
    return getattr(module, attr) if attr is not None else module


# ===========================================================================
# #367 — scam / ghost-job risk check before applying (entirely new capability)
# ===========================================================================
@given("a posting carrying scam / ghost-job signals")
def posting_with_scam_signals(spiritctx):
    spiritctx["posting"] = {
        "title": "Remote Data Entry — $9,500/week, no experience",
        "company": "Quick Cash LLC",
        "description": (
            "Pay is well above market. Contact us on Telegram only. Provide your SSN, "
            "bank account, and a scan of your ID to get started immediately."
        ),
    }


@given("an ordinary posting with no scam signals")
def ordinary_posting(spiritctx):
    spiritctx["posting"] = {
        "title": "Senior Backend Engineer",
        "company": "Acme Corp",
        "description": "Build and operate our payments platform. Competitive salary, benefits.",
    }


@when("the posting-risk rule scores it before apply")
def score_posting_risk(spiritctx):
    # Probe the intended core seam: a pure posting-risk rule. Absent today → xfail.
    spiritctx["assess"] = _probe("applicant.core.rules.posting_risk", "assess_posting_risk")


@then("it is flagged high-risk and routed to human confirmation instead of auto-apply")
def scam_held_for_confirmation(spiritctx):
    risk = spiritctx["assess"](spiritctx["posting"])
    # The intended contract: a high-risk posting must NOT be auto-appliable.
    assert getattr(risk, "auto_apply_allowed", True) is False
    assert getattr(risk, "requires_human_confirmation", False) is True


@then("it is cleared and the apply flow proceeds unchanged")
def clean_posting_cleared(spiritctx):
    risk = spiritctx["assess"](spiritctx["posting"])
    assert getattr(risk, "auto_apply_allowed", False) is True
    assert getattr(risk, "requires_human_confirmation", True) is False


# ===========================================================================
# #368 — duplicate-application / re-apply cooldown guard
# ===========================================================================
def _posting(cid, title, company, url):
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title=title,
        company=company,
        source_url=url,
        work_mode="remote",
        description="python backend",
        source_key="jobspy:indeed",
    )


@given("two near-identical postings surface in one discovery run")
def two_near_identical_listings(spiritctx):
    cid = CampaignId(new_id())
    spiritctx["raw"] = [
        _posting(cid, "Senior Python Engineer", "Acme", "https://acme.test/a"),
        _posting(cid, "Senior Python Engineer", "Acme", "https://acme.test/b"),
    ]


@when("the discovery results are deduplicated")
def dedup_listings(spiritctx):
    # GREEN: the real within-run embedding dedup seam (#196), no discovery adapter needed.
    svc = DiscoveryService(storage=None, discovery=None, embedding=LocalEmbedding())
    spiritctx["kept"] = svc._dedup(spiritctx["raw"])


@then("only one of the near-identical listings survives")
def one_listing_survives(spiritctx):
    assert len(spiritctx["kept"]) == 1


@given("the user already applied to a company and role")
def already_applied(spiritctx):
    spiritctx["history"] = [{"company": "Acme", "role": "Senior Python Engineer", "days_ago": 3}]
    spiritctx["candidate"] = {"company": "Acme", "role": "Senior Python Engineer"}


@given("the user applied to a company and role long enough ago to clear the cooldown")
def applied_long_ago(spiritctx):
    spiritctx["history"] = [{"company": "Acme", "role": "Senior Python Engineer", "days_ago": 365}]
    spiritctx["candidate"] = {"company": "Acme", "role": "Senior Python Engineer"}


@when("the same company and role is considered again within the cooldown window")
def consider_within_cooldown(spiritctx):
    spiritctx["guard"] = _probe(
        "applicant.core.rules.reapply_guard", "is_duplicate_application"
    )


@when("the same company and role is considered again after the cooldown window")
def consider_after_cooldown(spiritctx):
    spiritctx["guard"] = _probe(
        "applicant.core.rules.reapply_guard", "is_duplicate_application"
    )


@then("the application-history guard skips or holds it instead of re-applying")
def guard_skips_duplicate(spiritctx):
    dup = spiritctx["guard"](spiritctx["candidate"], spiritctx["history"], cooldown_days=30)
    assert dup is True


@then("the application-history guard treats it as eligible to apply")
def guard_allows_after_cooldown(spiritctx):
    dup = spiritctx["guard"](spiritctx["candidate"], spiritctx["history"], cooldown_days=30)
    assert dup is False


# ===========================================================================
# #369 — work-auth / sponsorship eligibility pre-filter
# ===========================================================================
@given("the onboarding intake model")
def onboarding_intake_model(spiritctx):
    from applicant.ports.driving.onboarding import REQUIRED_SECTIONS

    spiritctx["required_sections"] = REQUIRED_SECTIONS


@when("the required sections are listed")
def list_required_sections(spiritctx):
    spiritctx["section_values"] = {s.value for s in spiritctx["required_sections"]}


@then("work authorization is one of the captured sections")
def work_auth_section_present(spiritctx):
    from applicant.ports.driving.onboarding import IntakeSection

    assert IntakeSection.WORK_AUTHORIZATION in spiritctx["required_sections"]
    assert "work_authorization" in spiritctx["section_values"]


@given("the material-policy sponsorship lexicon")
def sponsorship_lexicon(spiritctx):
    # P2-7 moved the sponsorship/visa phrasing out of the FACTUAL cues into the
    # dedicated work-auth lane (never LLM-drafted): the locale work-auth cues,
    # consumed by ``is_work_auth_question`` / ``classify_screening_question``.
    from applicant.core.locale_config import DEFAULT_LOCALE

    spiritctx["lexicon"] = (
        DEFAULT_LOCALE.work_auth_cues + DEFAULT_LOCALE.work_auth_weak_markers
    )


@when("a sponsorship-requirement phrase is checked against it")
def check_sponsorship_phrase(spiritctx):
    phrase = "Do you require sponsorship now or in the future?".lower()
    spiritctx["matched"] = any(cue in phrase for cue in spiritctx["lexicon"])


@then("the phrase is recognized by the lexicon")
def phrase_recognized(spiritctx):
    assert spiritctx["matched"] is True
    # The lexicon genuinely carries sponsorship/visa phrasing today.
    assert "require sponsorship" in spiritctx["lexicon"]
    assert "visa" in spiritctx["lexicon"]


@given("a user whose captured work-authorization does not allow sponsorship")
def user_no_sponsorship(spiritctx):
    spiritctx["work_auth"] = {"can_be_sponsored": False, "needs_sponsorship": True}
    spiritctx["posting_text"] = "Visa sponsorship is available for this role."


@given("a user whose captured work-authorization needs no sponsorship")
def user_needs_no_sponsorship(spiritctx):
    spiritctx["work_auth"] = {"can_be_sponsored": True, "needs_sponsorship": False}
    spiritctx["posting_text"] = "Join our growing engineering team in a remote role."


@when("a posting requiring visa sponsorship is scored against that work-authorization")
def score_sponsorship_posting(spiritctx):
    spiritctx["filter"] = _probe(
        "applicant.core.rules.eligibility", "assess_work_auth_eligibility"
    )


@when("a posting with no sponsorship requirement is scored against that work-authorization")
def score_eligible_posting(spiritctx):
    spiritctx["filter"] = _probe(
        "applicant.core.rules.eligibility", "assess_work_auth_eligibility"
    )


@then("the eligibility filter excludes or flags it and surfaces the reason")
def sponsorship_excluded(spiritctx):
    verdict = spiritctx["filter"](spiritctx["posting_text"], spiritctx["work_auth"])
    assert getattr(verdict, "eligible", True) is False
    assert getattr(verdict, "reason", "")


@then("the eligibility filter leaves the posting unaffected")
def eligible_unaffected(spiritctx):
    verdict = spiritctx["filter"](spiritctx["posting_text"], spiritctx["work_auth"])
    assert getattr(verdict, "eligible", False) is True


# ===========================================================================
# #370 — ATS-parseability self-check of the GENERATED résumé
# ===========================================================================
_CLEAN_RESUME = """Jane Doe
jane.doe@example.com | +1 415 555 0199

Experience
Senior Backend Engineer, Acme Corp    Jan 2020 - Present

Skills
Python, PostgreSQL, Kubernetes, FastAPI
"""


@given("a clean single-column résumé text")
def clean_resume_text(spiritctx, tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text(_CLEAN_RESUME, encoding="utf-8")
    spiritctx["resume_path"] = str(path)


@when("the résumé parser extracts it")
def parse_resume(spiritctx):
    from applicant.adapters.resume_parser.resume_parser import ResumeParser

    spiritctx["parsed"] = ResumeParser().parse(spiritctx["resume_path"])


@then("the contact email and the listed skills are recoverable")
def contact_and_skills_recoverable(spiritctx):
    parsed = spiritctx["parsed"]
    assert parsed.email == "jane.doe@example.com"
    skills_lower = {s.lower() for s in parsed.skills}
    assert "python" in skills_lower
    assert "postgresql" in skills_lower


@given("a freshly rendered single-column résumé")
def rendered_clean_resume(spiritctx):
    spiritctx["render"] = {"format": "pdf", "extractable_text": _CLEAN_RESUME}


@given("a rendered résumé whose text is not recoverable (e.g. text-as-image)")
def rendered_unparseable_resume(spiritctx):
    spiritctx["render"] = {"format": "pdf", "extractable_text": ""}


@when("the ATS-parseability self-check runs on the render")
def run_parseability_selfcheck(spiritctx):
    spiritctx["check"] = _probe(
        "applicant.core.rules.ats_parseability", "check_render_parseability"
    )


@then("the self-check reports it as machine-readable")
def render_machine_readable(spiritctx):
    report = spiritctx["check"](spiritctx["render"]["extractable_text"])
    assert getattr(report, "parseable", False) is True


@then("the self-check flags it for review or regeneration and it is not submitted")
def render_flagged(spiritctx):
    report = spiritctx["check"](spiritctx["render"]["extractable_text"])
    assert getattr(report, "parseable", True) is False
    assert getattr(report, "requires_review", False) is True


# ===========================================================================
# #371 — per-company application volume cap (campaign cap ships; per-company new)
# ===========================================================================
@given("a campaign throughput far above the allowed ceiling")
def throughput_above_ceiling(spiritctx):
    spiritctx["requested"] = THROUGHPUT_HARD_CAP + 1000


@when("the throughput is clamped")
def clamp_the_throughput(spiritctx):
    spiritctx["clamped"] = clamp_throughput(spiritctx["requested"])


@then("the applied value never exceeds the campaign hard cap")
def throughput_within_cap(spiritctx):
    assert spiritctx["clamped"] == THROUGHPUT_HARD_CAP
    assert spiritctx["clamped"] <= THROUGHPUT_HARD_CAP


@given("a per-company application cap for a window")
def per_company_cap(spiritctx):
    spiritctx["company"] = "Acme"
    spiritctx["cap"] = 2
    spiritctx["already_sent"] = 2  # company already at its cap this window


@when("more applications to the same company are attempted than the cap allows")
def attempt_over_company_cap(spiritctx):
    spiritctx["guard"] = _probe(
        "applicant.core.rules.company_cap", "admit_company_application"
    )


@then("the overflow applications are held rather than sent")
def overflow_held(spiritctx):
    admitted = spiritctx["guard"](
        company=spiritctx["company"],
        sent_in_window=spiritctx["already_sent"],
        cap=spiritctx["cap"],
    )
    assert admitted is False


@given("a company that hit its per-company cap in the previous window")
def company_capped_previous_window(spiritctx):
    spiritctx["company"] = "Acme"
    spiritctx["cap"] = 2


@when("a new window begins")
def new_window_begins(spiritctx):
    spiritctx["guard"] = _probe(
        "applicant.core.rules.company_cap", "admit_company_application"
    )


@then("the per-company cap is reset so applications to that company are allowed again")
def cap_reset_allows(spiritctx):
    # A fresh window means zero applications sent so far → the next is admitted.
    admitted = spiritctx["guard"](
        company=spiritctx["company"], sent_in_window=0, cap=spiritctx["cap"]
    )
    assert admitted is True


# ===========================================================================
# #372 — durable, immutable per-application submission snapshot
# ===========================================================================
@given("a pre-fill result for an application")
def prefill_result(spiritctx):
    from applicant.core.state_machine import ApplicationState

    spiritctx["result"] = PrefillResult(
        application_id=ApplicationId(new_id()),
        state=ApplicationState.PREFILLING,
    )


@when("values are recorded for a page during pre-fill")
def record_page_values(spiritctx):
    spiritctx["result"].filled_by_page["https://ats.test/page1"] = {
        "#first_name": "Jane",
        "#email": "jane.doe@example.com",
    }


@then("the per-page fill log carries the recorded values")
def page_log_has_values(spiritctx):
    log = spiritctx["result"].filled_by_page
    assert "https://ats.test/page1" in log
    assert log["https://ats.test/page1"]["#email"] == "jane.doe@example.com"


@given("an application about to be submitted with exact answers and material versions")
def application_to_submit(spiritctx):
    spiritctx["snapshot_input"] = {
        "application_id": str(ApplicationId(new_id())),
        "answers": {"Why this role?": "I admire the payments work."},
        "material_versions": {"resume": "variant-7", "cover_letter": "doc-3"},
        "posting_url": "https://ats.test/job/123",
    }


@when("the submission is recorded at the stop-boundary")
def record_submission_snapshot(spiritctx):
    SnapshotService = _probe(
        "applicant.application.services.submission_snapshot_service",
        "SubmissionSnapshotService",
    )
    spiritctx["snapshot"] = SnapshotService().record(**spiritctx["snapshot_input"])


@then(
    "an immutable per-application snapshot of the answers, materials, posting, and "
    "timestamp is persisted"
)
def snapshot_persisted(spiritctx):
    snap = spiritctx["snapshot"]
    assert getattr(snap, "answers", None)
    assert getattr(snap, "material_versions", None)
    assert getattr(snap, "posting_url", None)
    assert getattr(snap, "timestamp", None) is not None


@given("a persisted submission snapshot for an application")
def persisted_snapshot(spiritctx):
    spiritctx["app_id"] = str(ApplicationId(new_id()))
    SnapshotService = _probe(
        "applicant.application.services.submission_snapshot_service",
        "SubmissionSnapshotService",
    )
    spiritctx["service"] = SnapshotService()
    spiritctx["service"].record(
        application_id=spiritctx["app_id"],
        answers={"Why this role?": "I admire the payments work."},
        material_versions={"resume": "variant-7"},
        posting_url="https://ats.test/job/123",
    )


@when("the snapshot is retrieved for that application")
def retrieve_snapshot(spiritctx):
    spiritctx["retrieved"] = spiritctx["service"].get(spiritctx["app_id"])


@then("it returns the exact submitted record and cannot be mutated after the fact")
def snapshot_immutable(spiritctx):
    import dataclasses

    snap = spiritctx["retrieved"]
    assert snap is not None
    assert snap.answers["Why this role?"] == "I admire the payments work."
    # Immutable: a frozen dataclass refuses post-hoc mutation.
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.posting_url = "https://evil.test/tampered"
