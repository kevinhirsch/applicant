"""Regression coverage for the demo-seed SETUP-GATE openers (usability follow-up
to audit §6 quick-win #49).

Seeding rows alone is not enough for an operable demo: EVERY seeded read surface
sits behind a setup gate, so a freshly seeded instance still shows the "connect a
model" / "automated work is blocked" walls instead of the populated daily loop.
Two gates matter:

* ``require_llm_configured`` (``SetupService.is_setup_gate_open`` — a non-empty
  tier ladder) — behind it: Portal, tracker, learning, post-submission.
* ``require_automated_work`` (adds ``OnboardingService.is_ready_to_apply`` — the
  hard apply-gate: search-criteria essentials + a base résumé) — behind it: the
  digest.

``dev_seed.ensure_demo_llm`` / ``dev_seed.ensure_demo_apply_ready`` open those two
gates through the REAL service write paths (``configure_llm`` / ``save_section``),
non-destructively (a real, already-satisfied gate is left untouched) and
idempotently (a re-seed is a no-op). ``build_demo_campaign`` carries the last two
criteria essentials (``keywords`` + a free-text statement) so the apply-gate can
be satisfied by the base-résumé write alone.

Each assertion below was verified by reverting the corresponding piece of the fix
(dropping the ``keywords``/``human_readable`` criteria, no-op'ing each helper) and
confirming it goes red, then restoring green — per this series' standing DoD.

Hermetic: uses a bare ``SetupService`` (in-memory config store) and a real
``OnboardingService`` over ``InMemoryStorage`` — no DB, so it runs under an
unreachable ``DATABASE_URL``.
"""

from __future__ import annotations

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services import dev_seed as seed
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.onboarding_service import OnboardingService
from applicant.application.services.setup_service import SetupService


def _onboarding(storage: InMemoryStorage) -> OnboardingService:
    """A real ``OnboardingService`` wired exactly as the container wires it: with a
    ``CriteriaService`` so ``apply_readiness`` reads the campaign's search criteria
    (the criteria half of the apply-gate), mirroring the live ``api`` service."""
    onb = OnboardingService(
        storage=storage,
        config_store=InMemoryAppConfigStore(),
        resume_parser=ResumeParser(),
    )
    onb.set_criteria_service(CriteriaService(storage))
    return onb


# ── the campaign carries ALL apply-readiness criteria essentials ─────────────


def test_demo_campaign_criteria_carries_every_apply_essential():
    """The demo campaign must carry titles, work_modes, locations, salary_floor AND
    keywords (+ a free-text statement) — the criteria half of the apply-gate — so
    the ONLY thing ``ensure_demo_apply_ready`` has to add is the base résumé."""
    crit = seed.build_demo_campaign().criteria
    assert crit.get("titles")
    assert crit.get("work_modes")
    assert crit.get("locations")
    assert crit.get("salary_floor")
    # These two were the gap: without them the apply-gate stays closed even with a
    # résumé (``has_keywords`` fails), so the digest 409s.
    assert crit.get("keywords")
    assert crit.get("human_readable", "").strip()


# ── ensure_demo_llm: opens the LLM gate, idempotent, non-destructive ─────────


def test_ensure_demo_llm_opens_a_closed_gate():
    svc = SetupService()
    assert svc.is_setup_gate_open() is False
    opened = seed.ensure_demo_llm(svc)
    assert opened is True
    assert svc.is_setup_gate_open() is True


def test_ensure_demo_llm_is_idempotent_noop_on_second_call():
    svc = SetupService()
    assert seed.ensure_demo_llm(svc) is True
    # A re-seed must report False and leave the ladder untouched.
    assert seed.ensure_demo_llm(svc) is False
    assert svc.is_setup_gate_open() is True


def test_ensure_demo_llm_never_clobbers_a_real_configured_llm():
    """If a real LLM is already configured, seeding must NOT overwrite it."""
    from applicant.ports.driving.setup_wizard import LLMSettings

    svc = SetupService()
    svc.configure_llm(
        LLMSettings(provider="openai", base_url="https://api.example.com", api_key="", model="gpt-real")
    )
    before = svc.get_tiers()
    assert seed.ensure_demo_llm(svc) is False
    assert svc.get_tiers() == before  # the operator's real tier is preserved
    assert svc.get_tiers()[0]["model"] == "gpt-real"


# ── ensure_demo_apply_ready: opens the hard apply-gate end to end ────────────


def test_ensure_demo_apply_ready_opens_the_apply_gate():
    """With the seeded campaign persisted, writing the base-résumé intake must flip
    ``is_ready_to_apply`` true (all criteria essentials + résumé now present)."""
    storage = InMemoryStorage()
    storage.campaigns.add(seed.build_demo_campaign())
    storage.commit()
    onb = _onboarding(storage)

    # The criteria essentials are present, but with no base résumé the gate is shut.
    assert onb.is_ready_to_apply(seed.DEMO_CAMPAIGN_ID) is False

    opened = seed.ensure_demo_apply_ready(onb, seed.DEMO_CAMPAIGN_ID)
    assert opened is True
    assert onb.has_base_resume(seed.DEMO_CAMPAIGN_ID) is True
    assert onb.is_ready_to_apply(seed.DEMO_CAMPAIGN_ID) is True


def test_ensure_demo_apply_ready_is_idempotent_noop_on_second_call():
    storage = InMemoryStorage()
    storage.campaigns.add(seed.build_demo_campaign())
    storage.commit()
    onb = _onboarding(storage)

    assert seed.ensure_demo_apply_ready(onb, seed.DEMO_CAMPAIGN_ID) is True
    # A re-seed sees the résumé already present and no-ops.
    assert seed.ensure_demo_apply_ready(onb, seed.DEMO_CAMPAIGN_ID) is False


def test_ensure_demo_apply_ready_never_clobbers_an_existing_base_resume():
    """If a real base résumé already exists, seeding must leave it untouched."""
    from applicant.ports.driving.onboarding import IntakeSection

    storage = InMemoryStorage()
    storage.campaigns.add(seed.build_demo_campaign())
    storage.commit()
    onb = _onboarding(storage)
    onb.save_section(
        seed.DEMO_CAMPAIGN_ID,
        IntakeSection.BASE_RESUME,
        {"document_path": "real/user-resume.pdf", "parsed": True, "raw_text": "real user text"},
    )

    assert seed.ensure_demo_apply_ready(onb, seed.DEMO_CAMPAIGN_ID) is False
    rec = onb.get_state(seed.DEMO_CAMPAIGN_ID).intake[IntakeSection.BASE_RESUME.value]
    assert rec["document_path"] == "real/user-resume.pdf"  # not the demo placeholder
