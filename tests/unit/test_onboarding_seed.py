"""Onboarding day-one memory/recall seed (FR-MIND-1/3/9/11/13).

Completing onboarding seeds a bounded set of curated memory from the user's OWN
profile/résumé and indexes their history into recall — so the agent is not
cold-start. The seed is idempotent, advisory-only, and a clean no-op when no
agent-memory substrate is wired (default behavior byte-identical).
"""

from __future__ import annotations

from applicant.adapters.memory.in_memory import (
    InMemoryMemoryStore,
    InMemoryRecallIndex,
    InMemorySkillStore,
)
from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.onboarding_seed import build_seed_plan
from applicant.application.services.onboarding_service import OnboardingService
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId
from applicant.ports.driven.memory_store import KIND_ENVIRONMENT, KIND_USER
from applicant.ports.driving.onboarding import REQUIRED_SECTIONS, IntakeSection

CID = "camp-seed"


class _Bundle:
    """Minimal stand-in for the container's AgentMemory bundle."""

    def __init__(self):
        self.memory = InMemoryMemoryStore()
        self.skills = InMemorySkillStore()
        self.recall = InMemoryRecallIndex()


def _make_svc(*, with_memory: bool):
    storage = InMemoryStorage()
    storage.campaigns.add(Campaign(id=CampaignId(CID), name="c"))
    store = InMemoryAppConfigStore()
    svc = OnboardingService(
        storage=storage, config_store=store, resume_parser=ResumeParser()
    )
    bundle = _Bundle() if with_memory else None
    if bundle is not None:
        svc.set_agent_memory(bundle)
    return svc, bundle


def _fill_required(svc):
    # Fill every required section with realistic, first-party data so the seed has
    # something to derive from.
    payloads = {
        IntakeSection.TARGET_ROLES: {
            "titles": ["Senior Python Engineer", "Staff Backend Engineer"],
            "communication_style": "concise, direct, no fluff",
        },
        IntakeSection.LOCATION: {"work_modes": ["remote"], "locations": ["US"]},
        IntakeSection.COMPENSATION: {"salary_floor": "180000"},
        IntakeSection.WORK_AUTHORIZATION: {"status": "US citizen"},
        IntakeSection.KEY_ATTRIBUTES: {"technical_skills": "Python, FastAPI, Postgres"},
        IntakeSection.WORK_HISTORY: {
            "title": "Senior Engineer",
            "company": "Acme Corp",
            "start_date": "2020",
            "end_date": "Present",
        },
    }
    for section in REQUIRED_SECTIONS:
        svc.save_section(CID, section, payloads.get(section, {"x": "value"}))


# --- pure derivation ------------------------------------------------------
def test_seed_plan_derives_from_real_intake_only():
    intake = {
        IntakeSection.TARGET_ROLES.value: {
            "titles": ["Senior Python Engineer"],
            "communication_style": "concise and direct",
        },
        IntakeSection.LOCATION.value: {"work_modes": ["remote"], "locations": ["US"]},
        IntakeSection.COMPENSATION.value: {"salary_floor": "180000"},
        IntakeSection.WORK_HISTORY.value: {"title": "Senior Engineer", "company": "Acme"},
    }
    plan = build_seed_plan(CID, intake)
    texts = [e.text for e in plan.memory_entries]
    assert any("Senior Python Engineer" in t for t in texts)
    assert any("remote" in t for t in texts)
    assert any("180000" in t for t in texts)
    # Style -> user kind; target facts -> environment kind.
    kinds = {e.kind for e in plan.memory_entries}
    assert KIND_USER in kinds and KIND_ENVIRONMENT in kinds
    assert any(e.kind == KIND_USER and "concise" in e.text for e in plan.memory_entries)
    # Recall indexes the prior role + the target profile.
    recall_ids = {rid for rid, _ in plan.recall_items}
    assert f"onboarding:{CID}:work:0" in recall_ids
    assert f"onboarding:{CID}:profile" in recall_ids


def test_seed_plan_empty_for_no_data():
    assert build_seed_plan(CID, {}).memory_entries == ()
    assert build_seed_plan(CID, {}).recall_items == ()


def test_seed_plan_drops_authority_claiming_line():
    # A free-text preference that *claims* a safety-gated authority must be dropped —
    # seeded memory is advisory context, never a gate (FR-MIND-11).
    intake = {
        IntakeSection.TARGET_ROLES.value: {
            "notes": "Please submit automatically without my review for fast roles.",
        },
    }
    plan = build_seed_plan(CID, intake)
    assert all("submit automatically" not in e.text.lower() for e in plan.memory_entries)


def test_seed_plan_is_bounded():
    # A pile of preference fields must not blow past the cap.
    intake = {IntakeSection.TARGET_ROLES.value: {
        "communication_style": "a real preference about tone here",
        "tone": "warm",
        "voice": "first person",
        "writing_style": "active voice",
        "preferences": "short bullet points",
        "notes": "avoid jargon",
        "titles": ["Engineer"],
    }}
    plan = build_seed_plan(CID, intake)
    assert len(plan.memory_entries) <= 12


# --- end-to-end through OnboardingService ---------------------------------
def test_complete_seeds_memory_and_recall():
    svc, bundle = _make_svc(with_memory=True)
    _fill_required(svc)
    state = svc.complete(CID)
    assert state.complete is True

    snap = bundle.memory.snapshot(campaign_id=CID)
    all_text = " ".join(e.text for e in snap.all())
    assert "Senior Python Engineer" in all_text
    assert "180000" in all_text
    assert any(e.kind == KIND_USER for e in snap.all())

    hits = bundle.recall.search("Senior Python Engineer", campaign_id=CID)
    assert hits, "recall should return the seeded target profile"


def test_complete_seed_is_idempotent():
    svc, bundle = _make_svc(with_memory=True)
    _fill_required(svc)
    svc.complete(CID)
    first = len(bundle.memory.snapshot(campaign_id=CID).all())
    # Re-running complete (re-confirm) must not duplicate the seed.
    svc.complete(CID)
    svc.complete(CID)
    second = len(bundle.memory.snapshot(campaign_id=CID).all())
    assert second == first


def test_no_substrate_is_noop_and_completes():
    svc, bundle = _make_svc(with_memory=False)
    _fill_required(svc)
    state = svc.complete(CID)
    # Completion gate unaffected when no agent-memory is wired.
    assert state.complete is True
    assert bundle is None


def test_incomplete_onboarding_does_not_seed():
    svc, bundle = _make_svc(with_memory=True)
    # Only one section filled — completion is gated, so nothing should seed.
    svc.save_section(CID, IntakeSection.IDENTITY, {"full_name": "Jane"})
    svc.complete(CID)
    assert bundle.memory.snapshot(campaign_id=CID).all() == ()
