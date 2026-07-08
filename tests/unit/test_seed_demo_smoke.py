"""Hermetic smoke test for the demo-seed builders (audit §6 quick-win #49).

Guards CI: exercises ONLY the pure ``build_demo_*`` builders in
``applicant.application.services.dev_seed`` — never touches the database — so it
passes even with an unreachable ``DATABASE_URL``. The IO path (``persist`` /
``purge`` / DB wiring) is intentionally NOT invoked here; ``scripts/seed_demo.py``
(the CLI) and ``applicant.app.routers.dev_seed`` (the HTTP route) both delegate to
this same module, so this file is the shared coverage for both callers' derivation
logic. The CLI's own env-gate behavior (``main()``) is covered separately below by
loading ``scripts/seed_demo.py`` by path, since ``scripts/`` is not an importable
package.

Run hermetically::

    DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \\
        uv run pytest -q tests/unit/test_seed_demo_smoke.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from applicant.application.services import dev_seed as seed
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.revision_session import RevisionSession, RevisionStatus
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.state_machine import ApplicationState

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"


def _load_seed_script():
    """Import scripts/seed_demo.py by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("seed_demo_cli", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["seed_demo_cli"] = module
    spec.loader.exec_module(module)
    return module


def test_module_imports_without_db():
    """Importing the module must not touch the DB (pure builders + IO helpers only)."""
    assert hasattr(seed, "build_demo_bundle")
    assert hasattr(seed, "persist")
    assert hasattr(seed, "purge")


def test_build_demo_campaign_is_valid_entity():
    campaign = seed.build_demo_campaign()
    assert isinstance(campaign, Campaign)
    assert str(campaign.id) == seed.DEMO_CAMPAIGN_ID
    assert campaign.active is True
    assert campaign.criteria.get("titles")


def test_build_demo_postings_are_scored():
    postings = seed.build_demo_postings()
    assert len(postings) >= 5
    companies = set()
    sources = set()
    for p in postings:
        assert isinstance(p, JobPosting)
        assert str(p.campaign_id) == seed.DEMO_CAMPAIGN_ID
        # Every posting carries a durable viability score so the digest renders it.
        assert p.viability_score is not None
        assert 0.0 <= p.viability_score <= 1.0
        assert p.rationale.get("summary")
        companies.add(p.company)
        sources.add(p.source_key)
    # Ids are unique (upsert-safe, no collisions).
    assert len({str(p.id) for p in postings}) == len(postings)
    # Realistic variety: distinct companies AND distinct discovery sources.
    assert len(companies) == len(postings)
    assert len(sources) >= 4


def test_build_demo_resume_variant_is_valid_entity():
    variant = seed.build_demo_resume_variant()
    assert isinstance(variant, ResumeVariant)
    assert str(variant.campaign_id) == seed.DEMO_CAMPAIGN_ID
    assert variant.is_root
    assert variant.approved is False


def test_build_demo_applications_cover_the_trust_core_states():
    postings = seed.build_demo_postings()
    variant = seed.build_demo_resume_variant()
    apps = seed.build_demo_applications(postings, variant)
    assert len(apps) == len(postings)
    for a in apps:
        assert isinstance(a, Application)
        assert str(a.campaign_id) == seed.DEMO_CAMPAIGN_ID

    states = {a.status for a in apps}
    # Every front-door surface has a subject application.
    assert ApplicationState.DIGESTED in states
    assert ApplicationState.MATERIAL_REVIEW in states
    assert ApplicationState.AWAITING_FINAL_APPROVAL in states
    assert ApplicationState.BLOCKED_QUESTION in states
    assert ApplicationState.BLOCKED_MISSING_ATTR in states
    # Two tracker-board rows share AWAITING_RESPONSE (see outcome-event signal test).
    assert sum(1 for a in apps if a.status == ApplicationState.AWAITING_RESPONSE) == 2

    # Only the material-review app carries the tailored variant.
    review = next(a for a in apps if a.status == ApplicationState.MATERIAL_REVIEW)
    assert review.resume_variant_id == variant.id
    # The final-approval app carries a takeover session URL.
    final = next(a for a in apps if a.status == ApplicationState.AWAITING_FINAL_APPROVAL)
    assert final.sandbox_session_url


def test_build_demo_material_and_revision_session():
    material = seed.build_demo_material("demo-app-globex")
    assert isinstance(material, GeneratedDocument)
    assert material.type == DocumentType.RESUME
    assert material.approved is False
    assert material.content

    session = seed.build_demo_revision_session(str(material.id))
    assert isinstance(session, RevisionSession)
    assert session.status == RevisionStatus.OPEN
    assert session.material_id == material.id
    # Redline turns exist so the review UI has state to render.
    assert len(session.turns) >= 2
    kinds = {t.kind for t in session.turns}
    assert kinds & {"add", "subtract", "free_text"}


def test_build_demo_submission_snapshot_and_outcome_events():
    postings = seed.build_demo_postings()
    variant = seed.build_demo_resume_variant()
    apps = seed.build_demo_applications(postings, variant)
    posting_by_id = {p.id: p for p in postings}
    interview_app = next(
        a for a in apps if a.id.rsplit("-", 1)[-1] == seed._INTERVIEW_SUFFIX
    )

    snapshot = seed.build_demo_submission_snapshot(
        str(interview_app.id), posting_by_id[interview_app.posting_id]
    )
    assert isinstance(snapshot, SubmissionSnapshot)
    assert snapshot.application_id == interview_app.id
    assert snapshot.posting_url

    events = seed.build_demo_outcome_events(apps)
    assert events
    for e in events:
        assert isinstance(e, OutcomeEvent)
    # The interview-signal tracker row carries a recorded interview_invited event.
    interview_types = {
        e.type for e in events if e.application_id == interview_app.id
    }
    assert "interview_invited" in interview_types
    assert "submitted" in interview_types
    # The plain AWAITING_RESPONSE row has a submitted event but no positive signal.
    plain_app = next(
        a
        for a in apps
        if a.status == ApplicationState.AWAITING_RESPONSE and a.id != interview_app.id
    )
    plain_types = {e.type for e in events if e.application_id == plain_app.id}
    assert plain_types == {"submitted"}


def test_pending_actions_cover_six_distinct_kinds():
    postings = seed.build_demo_postings()
    variant = seed.build_demo_resume_variant()
    apps = seed.build_demo_applications(postings, variant)
    material = seed.build_demo_material(
        str(next(a for a in apps if a.status == ApplicationState.MATERIAL_REVIEW).id)
    )
    actions = seed.build_demo_pending_actions(apps, postings, material)

    assert len(actions) == 6
    for a in actions:
        assert isinstance(a, PendingAction)
        assert str(a.campaign_id) == seed.DEMO_CAMPAIGN_ID
        assert a.title
        # A dedup_key is stamped so a re-seed replaces rather than piles up.
        assert a.payload.get("dedup_key")

    kinds = {a.kind for a in actions}
    assert kinds == {
        seed.KIND_DIGEST_APPROVAL,
        seed.KIND_MATERIAL_REVIEW,
        seed.KIND_AGENT_QUESTION,
        seed.KIND_FINAL_APPROVAL,
        seed.KIND_MISSING_ATTR,
        seed.KIND_INTEGRAL_CHANGE,
    }
    # Ids are unique (upsert-safe).
    assert len({str(a.id) for a in actions}) == len(actions)


def test_build_demo_bundle_is_coherent():
    bundle = seed.build_demo_bundle()
    # The material references the material-review application.
    review = next(
        a for a in bundle.applications if a.status == ApplicationState.MATERIAL_REVIEW
    )
    assert str(bundle.material.application_id) == str(review.id)
    # The revision session targets the material.
    assert bundle.revision_session.material_id == bundle.material.id
    # The submission snapshot targets the interview-signal tracker application.
    interview_app = next(
        a
        for a in bundle.applications
        if a.id.rsplit("-", 1)[-1] == seed._INTERVIEW_SUFFIX
    )
    assert bundle.submission_snapshot.application_id == interview_app.id
    # Every pending action's campaign matches the bundle campaign.
    for a in bundle.pending_actions:
        assert a.campaign_id == bundle.campaign.id
    # Every outcome event points at a real application in the bundle.
    app_ids = {a.id for a in bundle.applications}
    for e in bundle.outcome_events:
        assert e.application_id in app_ids


def test_cli_refuses_without_demo_mode_env(monkeypatch, capsys):
    """The CLI's env gate must refuse (non-zero) and never touch the DB when both
    ``DEMO_MODE`` and the ``APPLICANT_ALLOW_SEED`` alias are unset."""
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    cli = _load_seed_script()
    rc = cli.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "DEMO_MODE=1" in err


def test_cli_demo_mode_alias_enables(monkeypatch):
    """Either env var opens the gate: ``DEMO_MODE=1`` OR the ``APPLICANT_ALLOW_SEED``
    alias. Exercises the pure gate predicate (no DB touched)."""
    cli = _load_seed_script()
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    assert cli._demo_enabled() is False
    monkeypatch.setenv("DEMO_MODE", "1")
    assert cli._demo_enabled() is True
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    assert cli._demo_enabled() is True
