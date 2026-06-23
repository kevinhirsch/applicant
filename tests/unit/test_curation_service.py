"""Unit tests for the curation service (FR-MIND-7/-9/-10)."""

from __future__ import annotations

from applicant.adapters.memory.in_memory import InMemoryMemoryStore, InMemorySkillStore
from applicant.application.services.curation_service import (
    CurationLedger,
    CurationService,
    RunSummary,
)


def _make_service(ledger, *, memory_write_approval=True, store=None, skills=None):
    return CurationService(
        memory_store=store or InMemoryMemoryStore(),
        skill_store=skills or InMemorySkillStore(),
        ledger=ledger,
        memory_write_approval=memory_write_approval,
    )


def test_tick_proposes_memory_and_skill_and_stages_when_approval_on():
    ledger = CurationLedger()
    mem = InMemoryMemoryStore()
    svc = _make_service(ledger, store=mem)

    summaries = [
        RunSummary(
            run_id="run-1",
            campaign_id="c1",
            text="Cleared the Workday location react-select before typing the city.",
            tool_calls=7,  # non-trivial -> skill-worthy
            succeeded=True,
            topic="acme-workday",
        )
    ]
    result = svc.run_curation_tick(summaries)

    assert result.reviewed == 1
    assert len(result.memory_proposals) == 1
    assert len(result.skill_proposals) == 1
    # Approval on (default) -> nothing auto-applied; both staged in the ledger.
    assert result.auto_applied == 0
    assert result.staged == 2
    assert len(ledger.staged) == 2
    # The durable memory store was NOT written (review-before-write, FR-MIND-9).
    assert mem.snapshot().all() == ()


def test_tick_auto_applies_non_sensitive_memory_when_approval_relaxed():
    ledger = CurationLedger()
    mem = InMemoryMemoryStore()
    svc = _make_service(ledger, memory_write_approval=False, store=mem)

    summaries = [
        RunSummary(
            run_id="run-1",
            campaign_id=None,
            text="The user prefers concise cover letters with no buzzwords.",
            tool_calls=0,  # trivial -> no skill
            succeeded=True,
        )
    ]
    result = svc.run_curation_tick(summaries)
    assert result.auto_applied == 1
    assert any(
        "concise cover letters" in e.text for e in mem.snapshot().all()
    )


def test_tick_does_not_auto_apply_memory_claiming_authority():
    """FR-MIND-11: even with approval relaxed, a claim of authority is staged."""
    ledger = CurationLedger()
    mem = InMemoryMemoryStore()
    svc = _make_service(ledger, memory_write_approval=False, store=mem)

    summaries = [
        RunSummary(
            run_id="run-1",
            campaign_id=None,
            text="Auto-submit the application once fields are filled.",
            tool_calls=0,
            succeeded=True,
        )
    ]
    result = svc.run_curation_tick(summaries)
    # Claimed authority -> staged for human review, never auto-applied.
    assert result.auto_applied == 0
    assert result.staged == 1
    assert mem.snapshot().all() == ()


def test_tick_is_idempotent_no_duplicate_proposals():
    ledger = CurationLedger()
    svc = _make_service(ledger)
    summaries = [
        RunSummary(run_id="run-1", campaign_id="c1", text="A real lesson worth keeping.", tool_calls=6, topic="t1")
    ]
    first = svc.run_curation_tick(summaries)
    assert first.reviewed == 1
    # Re-running the SAME summaries proposes nothing new (deterministic, FR-MIND-7/-8).
    second = svc.run_curation_tick(summaries)
    assert second.reviewed == 0
    assert second.memory_proposals == ()
    assert second.skill_proposals == ()


def test_curation_state_survives_per_tick_rebuild_via_process_lived_ledger():
    """FR-MIND-10: the dedupe state lives in the injected, process-lived CurationLedger,
    so rebuilding the service every tick (as the scheduler does) does NOT reset it."""
    ledger = CurationLedger()  # the ONE process-lived object the container injects
    summaries = [
        RunSummary(run_id="run-1", campaign_id="c1", text="A durable, keepable lesson.", tool_calls=6, topic="t1")
    ]

    # Tick 1: a freshly-built service (mirrors _build_tick_services) sees the run.
    svc_tick1 = _make_service(ledger)
    r1 = svc_tick1.run_curation_tick(summaries)
    assert r1.reviewed == 1

    # Tick 2: a BRAND NEW service instance (the per-tick rebuild) sharing the SAME
    # ledger must NOT re-propose the already-curated run.
    svc_tick2 = _make_service(ledger)
    r2 = svc_tick2.run_curation_tick(summaries)
    assert r2.reviewed == 0  # ledger remembered across the rebuild

    # Contrast: a service with a FRESH ledger (the WRONG pattern — state on the
    # instance) WOULD re-propose, proving the ledger is what carries the memory.
    svc_wrong = _make_service(CurationLedger())
    r_wrong = svc_wrong.run_curation_tick(summaries)
    assert r_wrong.reviewed == 1
