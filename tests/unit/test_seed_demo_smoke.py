"""Hermetic smoke test for the demo-seed builders (scripts/seed_demo.py).

Guards CI: exercises ONLY the pure ``build_demo_*`` builders — never touches the
database — so it passes even with an unreachable ``DATABASE_URL``. The IO path
(``persist`` / ``_build_storage`` / ``main``) is intentionally NOT invoked here.

Run hermetically::

    DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \\
        uv run pytest -q tests/unit/test_seed_demo_smoke.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.revision_session import RevisionSession, RevisionStatus
from applicant.core.state_machine import ApplicationState

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"


def _load_seed_module():
    """Import scripts/seed_demo.py by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("seed_demo", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Register before exec so dataclass field(default_factory=...) resolution can find
    # the module in sys.modules (dataclasses inspects cls.__module__ during processing).
    sys.modules["seed_demo"] = module
    spec.loader.exec_module(module)
    return module


seed = _load_seed_module()


def test_module_imports_without_db():
    """Importing the script must not touch the DB (pure builders + IO helpers only)."""
    assert hasattr(seed, "build_demo_bundle")
    assert hasattr(seed, "persist")


def test_build_demo_campaign_is_valid_entity():
    campaign = seed.build_demo_campaign()
    assert isinstance(campaign, Campaign)
    assert str(campaign.id) == seed.DEMO_CAMPAIGN_ID
    assert campaign.active is True
    assert campaign.criteria.get("titles")


def test_build_demo_postings_are_scored():
    postings = seed.build_demo_postings()
    assert len(postings) >= 3
    for p in postings:
        assert isinstance(p, JobPosting)
        assert str(p.campaign_id) == seed.DEMO_CAMPAIGN_ID
        # Every posting carries a durable viability score so the digest renders it.
        assert p.viability_score is not None
        assert 0.0 <= p.viability_score <= 1.0
        assert p.rationale.get("summary")
    # Ids are unique (upsert-safe, no collisions).
    assert len({str(p.id) for p in postings}) == len(postings)


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
    # The four surfaces each have a subject application.
    assert ApplicationState.DIGESTED in states
    assert ApplicationState.MATERIAL_REVIEW in states
    assert ApplicationState.AWAITING_FINAL_APPROVAL in states
    assert ApplicationState.BLOCKED_QUESTION in states

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


def test_pending_actions_are_four_distinct_kinds():
    postings = seed.build_demo_postings()
    variant = seed.build_demo_resume_variant()
    apps = seed.build_demo_applications(postings, variant)
    material = seed.build_demo_material(
        str(next(a for a in apps if a.status == ApplicationState.MATERIAL_REVIEW).id)
    )
    actions = seed.build_demo_pending_actions(apps, postings, material)

    assert len(actions) == 4
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
    # Every pending action's campaign matches the bundle campaign.
    for a in bundle.pending_actions:
        assert a.campaign_id == bundle.campaign.id


def test_main_refuses_without_allow_seed_env(monkeypatch, capsys):
    """The env gate must refuse (non-zero) and never touch the DB when unset."""
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    rc = seed.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "APPLICANT_ALLOW_SEED=1" in err
