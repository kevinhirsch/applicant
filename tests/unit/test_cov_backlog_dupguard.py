"""Regression coverage for docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md's
product-gaps backlog items "duplicate-application guard" and the "scam/ghost-job
warning".

**Investigation (before writing anything):** ``presubmit_safety.py`` already had
fully-implemented ``check_duplicate_application`` / ``check_scam_or_ghost_job`` /
``check_per_company_volume_cap`` / ``check_eligibility``. A repo-wide grep showed
they were wired in exactly ONE place: ``AgentLoop._process_approvals`` (the
pipeline-start gate, `src/applicant/application/services/agent_loop.py`), which
runs them ONLY *after* the owner has already approved a role from the digest, and
on a block just logs ``presubmit_blocked`` and silently skips — never surfaced to
the owner. ``DigestService.build_digest``/``build_digest_payload`` (the thing that
actually produces what the owner sees, before any approval) never called them at
all. So: built, wired, but dark as a pre-approval signal — the owner had no way to
know a role was a likely duplicate or scam/ghost listing until after clicking
Approve, and even then only via a server log line.

This file pins the fix: ``DigestService.build_digest`` now runs BOTH read-only
checks per row (via a new ``_presubmit_warnings`` helper) and attaches
``row["warnings"]`` — a list of ``{"check": ..., "message": ...}`` — without ever
excluding the row (a warning informs; only the pipeline-start gate still blocks).
``DigestService`` also accepts an optional ``presubmit_safety_params`` dict (same
shape/keys as ``AgentLoop``'s, threaded from the SAME settings-derived dict in
``container.py`` — see the ``presubmit_safety_params = {...}`` built once in
``build_container``) so a digest warning reflects the same operator-configured
age/cooldown thresholds as the actual pipeline block, not a second, independently
drifting default.

Each assertion below was verified failing by hand (temporarily reverting the
``row["warnings"] = ...`` line / the ``_presubmit_warnings`` helper / the
constructor param, rerunning, seeing a real failure, then restoring — ``git diff``
clean afterward) before this file was landed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.application.services.presubmit_safety import (
    PresubmitBlock,
    check_duplicate_application,
    check_scam_or_ghost_job,
)
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _wire(*, presubmit_safety_params: dict | None = None) -> tuple:
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    # threshold=0: every scored posting clears the digest's viability bar, so the
    # scam/duplicate signal (not the score) is what determines whether the row is
    # excluded or merely warned about.
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


# ── the checks themselves are unchanged (read-only investigation) ─────────────


def test_the_two_checks_still_only_run_from_agent_loop_process_approvals():
    """Sanity check on the investigation: the pipeline-start call site still
    exists exactly once in agent_loop.py's approval-to-pipeline path (this test
    does not change that call site; it documents the pre-existing wiring the
    digest-level warning below is additive to)."""
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src"
        / "applicant"
        / "application"
        / "services"
        / "agent_loop.py"
    ).read_text(encoding="utf-8")
    assert src.count("check_scam_or_ghost_job(") == 1
    assert src.count("check_duplicate_application(") == 1
    assert "_process_approvals" in src


# ── digest-row warnings: the genuine gap this file closes ─────────────────────


def test_scam_signal_surfaces_as_a_digest_row_warning_without_excluding_the_row():
    storage, digest = _wire()
    cid = _campaign(storage)
    posting = _posting(storage, cid, company="Confidential")  # placeholder company
    rows = digest.build_digest(cid)
    assert len(rows) == 1, "a warning must not exclude the row from the digest"
    row = rows[0]
    assert row["posting_id"] == posting.id
    assert row["warnings"], "expected a non-empty warnings list for a placeholder company"
    assert row["warnings"][0]["check"] == "company_reputation"
    assert "placeholder" in row["warnings"][0]["message"].lower()


def test_clean_posting_has_no_warnings():
    storage, digest = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)
    rows = digest.build_digest(cid)
    assert len(rows) == 1
    assert rows[0]["warnings"] == []


def test_duplicate_application_at_same_company_and_title_surfaces_as_a_warning():
    storage, digest = _wire()
    cid = _campaign(storage)
    # An already-submitted application to the same (company, title) 5 days ago —
    # inside the default 30-day cooldown.
    old_posting = _posting(storage, cid, title="Senior Backend Engineer", company="Acme Corp")
    old_app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=old_posting.id,
        status=ApplicationState.SUBMITTED_BY_USER,
        created_at=datetime.now(UTC) - timedelta(days=5),
    )
    storage.applications.add(old_app)
    storage.commit()

    # A freshly-discovered, DIFFERENT posting (different id) for the same
    # (company, normalized-title) pair.
    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="Senior Backend Engineer",
        company="Acme Corp",
    )
    rows = digest.build_digest(cid)
    new_row = next(r for r in rows if r["posting_id"] == new_posting.id)
    assert any(w["check"] == "duplicate_cooldown" for w in new_row["warnings"]), (
        "expected a duplicate_cooldown warning for the same company/normalized-title "
        "within the cooldown window"
    )
    assert "already applied" in new_row["warnings"][0]["message"].lower()


def test_in_flight_application_does_not_count_toward_the_duplicate_warning():
    """Mirrors check_duplicate_application's own contract: only TERMINAL
    applications count toward the cooldown — an in-flight one is being worked on
    now, not a completed duplicate."""
    storage, digest = _wire()
    cid = _campaign(storage)
    old_posting = _posting(storage, cid, title="Senior Backend Engineer", company="Acme Corp")
    in_flight = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=old_posting.id,
        status=ApplicationState.APPROVED,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    storage.applications.add(in_flight)
    storage.commit()
    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="Senior Backend Engineer",
        company="Acme Corp",
    )
    rows = digest.build_digest(cid)
    new_row = next(r for r in rows if r["posting_id"] == new_posting.id)
    assert not any(w["check"] == "duplicate_cooldown" for w in new_row["warnings"])


def test_digest_warning_thresholds_are_threaded_from_the_same_settings_dict_agentloop_uses():
    """A digest-row warning must reflect the SAME operator-configured cooldown as
    the pipeline-start block, not a hardcoded default that can silently drift from
    a configured PRESUBMIT_DUPLICATE_COOLDOWN_DAYS."""
    storage, digest = _wire(presubmit_safety_params={"duplicate_cooldown_days": 0})
    cid = _campaign(storage)
    old_posting = _posting(storage, cid, title="Senior Backend Engineer", company="Acme Corp")
    old_app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=old_posting.id,
        status=ApplicationState.SUBMITTED_BY_USER,
        created_at=datetime.now(UTC) - timedelta(days=5),
    )
    storage.applications.add(old_app)
    storage.commit()
    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="Senior Backend Engineer",
        company="Acme Corp",
    )
    rows = digest.build_digest(cid)
    new_row = next(r for r in rows if r["posting_id"] == new_posting.id)
    assert not any(w["check"] == "duplicate_cooldown" for w in new_row["warnings"]), (
        "a 0-day configured cooldown must suppress the warning for a 5-day-old "
        "application, proving the digest reads the SAME configured value the "
        "pipeline-start check would"
    )


def test_build_digest_payload_carries_the_warnings_through_to_the_top_level_rows():
    """build_digest_payload (what the HTTP GET /api/digest/{id} route — and thus
    the workspace proxy + applicantDigest.js — actually reads) must not drop the
    warnings field build_digest computed."""
    storage, digest = _wire()
    cid = _campaign(storage)
    _posting(storage, cid, company="undisclosed")
    payload = digest.build_digest_payload(cid)
    assert payload["rows"][0]["warnings"], "warnings must survive into the digest payload"


def test_presubmit_block_still_raised_for_a_direct_call_unchanged_by_this_fix():
    """presubmit_safety.py itself is untouched: check_scam_or_ghost_job /
    check_duplicate_application still raise PresubmitBlock exactly as before —
    the digest only newly CATCHES it read-only; it does not change the checks."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    posting = _posting(storage, cid, company="n/a")
    try:
        check_scam_or_ghost_job(posting)
    except PresubmitBlock as exc:
        assert exc.check == "company_reputation"
    else:
        raise AssertionError("expected PresubmitBlock for a placeholder company name")

    old_posting = _posting(storage, cid, title="Data Scientist", company="Globex")
    storage.applications.add(
        Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=old_posting.id,
            status=ApplicationState.FINISHED_BY_ENGINE,
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
    )
    storage.commit()
    dup_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="Data Scientist", company="Globex"
    )
    try:
        check_duplicate_application(cid, dup_posting, storage)
    except PresubmitBlock as exc:
        assert exc.check == "duplicate_cooldown"
    else:
        raise AssertionError("expected PresubmitBlock for a same-company/title duplicate")
