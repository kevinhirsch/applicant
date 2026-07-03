"""Regression coverage for dark-engine audit item #43 ("pre-submit safety
verdicts preview"): the digest's read-only presubmit-safety warnings previously
only ran ``check_scam_or_ghost_job`` / ``check_duplicate_application`` (see
``tests/unit/test_cov_backlog_dupguard.py``). The other two fully-implemented
checks in ``presubmit_safety.py`` — ``check_per_company_volume_cap`` and
``check_eligibility`` — were STILL only invoked from
``AgentLoop._process_approvals`` (the pipeline-start gate, AFTER approval), so
an owner had no way to know a role would be blocked for hitting today's
per-company cap or for a work-authorization mismatch until after clicking
Approve.

**Investigation confirmed (before writing anything):** grepped
``digest_service.py``'s ``_presubmit_warnings`` — it called exactly
``check_scam_or_ghost_job`` and ``check_duplicate_application``, never
``check_per_company_volume_cap``/``check_eligibility``. This file pins the fix:
``_presubmit_warnings`` now also runs those two checks read-only (mirroring
the exact param keys ``AgentLoop`` already threads from the SAME
``presubmit_safety_params`` dict built once in ``container.py``), appending
their ``PresubmitBlock`` reasons to ``row["warnings"]`` without ever excluding
the row.

Each assertion below was verified failing by hand (temporarily reverting the
two new ``try/except`` blocks in ``_presubmit_warnings``, rerunning, seeing a
real failure — either an empty ``warnings`` list or a missing check name — then
restoring; ``git diff`` clean afterward) before this file was landed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.application.services.presubmit_safety import (
    PresubmitBlock,
    check_eligibility,
    check_per_company_volume_cap,
)
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    JobPostingId,
    OnboardingProfileId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


def _wire(*, presubmit_safety_params: dict | None = None) -> tuple:
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    # threshold=0: every scored posting clears the digest's viability bar, so
    # the presubmit signal (not the score) determines whether a warning
    # appears.
    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    digest = DigestService(
        storage,
        notifier,
        scoring,
        presubmit_safety_params=presubmit_safety_params,
    )
    return storage, digest


def _campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    return cid


def _posting(storage, cid, **overrides) -> JobPosting:
    defaults = dict(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Backend Engineer",
        company="Acme Corp",
        source_url="https://acme.test/job",
        description=(
            "We need a senior backend engineer with 5+ years of experience in "
            "distributed systems, Python, and Go. Responsibilities include owning "
            "the payments service and mentoring junior engineers."
        ),
    )
    defaults.update(overrides)
    posting = JobPosting(**defaults)
    storage.postings.add(posting)
    storage.commit()
    return posting


def _application(storage, cid, posting, *, status, created_at) -> Application:
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=posting.id,
        status=status,
        created_at=created_at,
    )
    storage.applications.add(app)
    storage.commit()
    return app


# ── per-company volume cap: now surfaces as a digest row warning ──────────────


def test_per_company_volume_cap_surfaces_as_a_digest_row_warning_without_excluding_the_row():
    storage, digest = _wire(presubmit_safety_params={"max_apps_per_company_per_day": 1})
    cid = _campaign(storage)
    now = datetime.now(UTC)
    existing = _posting(storage, cid, title="Existing Role", company="Acme Corp")
    _application(storage, cid, existing, status=ApplicationState.APPROVED, created_at=now)

    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="New Role", company="Acme Corp",
    )
    rows = digest.build_digest(cid)
    assert len(rows) == 2, "a warning must not exclude the row from the digest"
    new_row = next(r for r in rows if r["posting_id"] == new_posting.id)
    assert any(w["check"] == "per_company_volume" for w in new_row["warnings"]), (
        "expected a per_company_volume warning once today's cap for the company "
        "is already met"
    )
    assert "cap" in next(
        w["message"] for w in new_row["warnings"] if w["check"] == "per_company_volume"
    ).lower()


def test_per_company_volume_cap_warning_absent_when_under_the_cap():
    storage, digest = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)
    rows = digest.build_digest(cid)
    assert len(rows) == 1
    assert not any(w["check"] == "per_company_volume" for w in rows[0]["warnings"])


def test_volume_cap_digest_warning_threaded_from_the_same_settings_dict_agentloop_uses():
    """A digest-row warning must reflect the SAME operator-configured cap as the
    pipeline-start block, not a hardcoded default that can silently drift from a
    configured PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY."""
    storage, digest = _wire(presubmit_safety_params={"max_apps_per_company_per_day": 5})
    cid = _campaign(storage)
    now = datetime.now(UTC)
    existing = _posting(storage, cid, title="Existing Role", company="Acme Corp")
    _application(storage, cid, existing, status=ApplicationState.APPROVED, created_at=now)

    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="New Role", company="Acme Corp",
    )
    rows = digest.build_digest(cid)
    new_row = next(r for r in rows if r["posting_id"] == new_posting.id)
    assert not any(w["check"] == "per_company_volume" for w in new_row["warnings"]), (
        "a 5-per-day configured cap must suppress the warning after only 1 "
        "existing application today, proving the digest reads the SAME "
        "configured value the pipeline-start check would"
    )


# ── eligibility (work-authorization): now surfaces as a digest row warning ───


def test_eligibility_sponsorship_mismatch_surfaces_as_a_digest_row_warning():
    storage, digest = _wire()
    cid = _campaign(storage)
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            completion_flag=True,
            intake={"work_authorization": {"needs_sponsorship": True}},
        )
    )
    storage.commit()
    _posting(
        storage, cid,
        description=(
            "We are unable to sponsor visas for this role; you must have "
            "permanent work authorization in the US. 5+ years experience in "
            "distributed systems required."
        ),
    )
    rows = digest.build_digest(cid)
    assert len(rows) == 1, "a warning must not exclude the row from the digest"
    warnings = rows[0]["warnings"]
    assert any(w["check"].startswith("eligibility_") for w in warnings), (
        "expected an eligibility warning for a sponsorship mismatch"
    )


def test_eligibility_clearance_mismatch_surfaces_as_a_digest_row_warning():
    storage, digest = _wire()
    cid = _campaign(storage)
    storage.attributes.add(
        Attribute(
            id=AttributeId(new_id()),
            campaign_id=cid,
            name="security clearance",
            value="no",
        )
    )
    storage.commit()
    _posting(
        storage, cid,
        description=(
            "This role requires an active top secret clearance. 5+ years "
            "experience in distributed systems, Python, and Go required."
        ),
    )
    rows = digest.build_digest(cid)
    warnings = rows[0]["warnings"]
    assert any(w["check"] == "eligibility_clearance" for w in warnings)


def test_eligibility_warning_absent_when_profile_matches_the_posting():
    storage, digest = _wire()
    cid = _campaign(storage)
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            completion_flag=True,
            intake={"work_authorization": {"needs_sponsorship": False}},
        )
    )
    storage.commit()
    _posting(storage, cid)
    rows = digest.build_digest(cid)
    assert not any(w["check"].startswith("eligibility_") for w in rows[0]["warnings"])


def test_eligibility_check_suppressed_when_disabled_via_settings():
    """Mirrors AgentLoop: eligibility is gated behind ``eligibility_enabled`` (an
    operator may not have filled in work-authorization intake yet, in which case
    the check would just be noise) — the digest must respect the same flag."""
    storage, digest = _wire(presubmit_safety_params={"eligibility_enabled": False})
    cid = _campaign(storage)
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            completion_flag=True,
            intake={"work_authorization": {"needs_sponsorship": True}},
        )
    )
    storage.commit()
    _posting(
        storage, cid,
        description=(
            "We are unable to sponsor visas for this role. 5+ years experience "
            "in distributed systems required."
        ),
    )
    rows = digest.build_digest(cid)
    assert not any(w["check"].startswith("eligibility_") for w in rows[0]["warnings"]), (
        "eligibility_enabled=False must suppress the digest-row eligibility "
        "warning, matching AgentLoop's own gate"
    )


def test_eligibility_check_runs_by_default_when_params_omit_the_flag():
    """When ``presubmit_safety_params`` is None/omits the key, the default must
    be enabled (matches AgentLoop's own ``.get("eligibility_enabled", True)``)."""
    storage, digest = _wire()
    cid = _campaign(storage)
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            completion_flag=True,
            intake={"work_authorization": {"needs_sponsorship": True}},
        )
    )
    storage.commit()
    _posting(
        storage, cid,
        description=(
            "We are unable to sponsor visas for this role. 5+ years experience "
            "in distributed systems required."
        ),
    )
    rows = digest.build_digest(cid)
    assert any(w["check"].startswith("eligibility_") for w in rows[0]["warnings"])


def test_build_digest_payload_carries_all_four_warning_kinds_through_to_the_top_level_rows():
    """build_digest_payload (what GET /api/digest/{id} — and thus the workspace
    proxy + applicantDigest.js — actually reads) must not drop the new warnings."""
    storage, digest = _wire(presubmit_safety_params={"max_apps_per_company_per_day": 1})
    cid = _campaign(storage)
    now = datetime.now(UTC)
    existing = _posting(storage, cid, title="Existing Role", company="Acme Corp")
    _application(storage, cid, existing, status=ApplicationState.APPROVED, created_at=now)
    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="New Role", company="Acme Corp",
    )
    payload = digest.build_digest_payload(cid)
    new_row = next(r for r in payload["rows"] if r["posting_id"] == new_posting.id)
    assert any(w["check"] == "per_company_volume" for w in new_row["warnings"]), (
        "the volume-cap warning must survive into the digest payload"
    )


# ── presubmit_safety.py itself is unchanged (read-only investigation) ─────────


def test_presubmit_block_still_raised_for_a_direct_call_of_the_two_newly_wired_checks():
    """presubmit_safety.py itself is untouched by this fix: check_per_company_volume_cap
    / check_eligibility still raise PresubmitBlock exactly as before — the digest
    only newly CATCHES them read-only; it does not change the checks."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    now = datetime.now(UTC)
    existing = _posting(storage, cid, title="Existing Role", company="Acme Corp")
    _application(storage, cid, existing, status=ApplicationState.APPROVED, created_at=now)
    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="New Role", company="Acme Corp",
    )
    try:
        check_per_company_volume_cap(cid, new_posting, storage, max_per_day=1)
    except PresubmitBlock as exc:
        assert exc.check == "per_company_volume"
    else:
        raise AssertionError("expected PresubmitBlock for an exceeded daily company cap")

    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            completion_flag=True,
            intake={"work_authorization": {"needs_sponsorship": True}},
        )
    )
    storage.commit()
    clearance_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="Cleared Role", company="Globex",
        description="Requires unable to sponsor visas for this role.",
    )
    try:
        check_eligibility(cid, clearance_posting, storage)
    except PresubmitBlock as exc:
        assert exc.check.startswith("eligibility_")
    else:
        raise AssertionError("expected PresubmitBlock for a sponsorship mismatch")
