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


def test_approve_applies_memory_proposal_to_store_and_clears_it():
    """FR-MIND-9: approving a staged memory proposal is the ONLY path that writes it."""
    ledger = CurationLedger()
    mem = InMemoryMemoryStore()
    svc = _make_service(ledger, store=mem)
    svc.run_curation_tick(
        [RunSummary(run_id="run-1", campaign_id=None, text="A keepable lesson.", tool_calls=1, topic="t1")]
    )
    staged = svc.list_staged()
    assert len(staged) == 1
    assert mem.snapshot().all() == ()  # not yet applied

    from applicant.application.services.curation_service import proposal_to_dict

    pid = proposal_to_dict(staged[0])["id"]
    assert svc.approve(pid) is True
    # Applied to the durable store (global scope), and removed from the queue.
    assert any("keepable" in e.text for e in mem.snapshot().all())
    assert svc.list_staged() == ()
    # Approving an already-handled id is a no-op (idempotent).
    assert svc.approve(pid) is False


def test_deny_discards_proposal_without_applying():
    ledger = CurationLedger()
    mem = InMemoryMemoryStore()
    skills = InMemorySkillStore()
    svc = _make_service(ledger, store=mem, skills=skills)
    svc.run_curation_tick(
        [RunSummary(run_id="run-1", campaign_id="c1", text="A keepable lesson.",
                    tool_calls=7, succeeded=True, topic="acme")]
    )
    from applicant.application.services.curation_service import proposal_to_dict

    for staged in list(svc.list_staged()):
        assert svc.deny(proposal_to_dict(staged)["id"]) is True
    assert svc.list_staged() == ()
    # Nothing was written to either store.
    assert mem.snapshot().all() == ()
    assert skills.list_skills() == ()


def test_proposal_to_dict_is_white_labeled_and_flags_authority():
    """The Portal payload uses plain language and surfaces an authority claim as a
    flag — never as a grant (FR-MIND-11/-12)."""
    ledger = CurationLedger()
    svc = _make_service(ledger)
    svc.run_curation_tick(
        [RunSummary(run_id="run-1", campaign_id=None,
                    text="Always auto-submit the Acme application.", tool_calls=1, topic="t1")]
    )
    from applicant.application.services.curation_service import proposal_to_dict

    items = [proposal_to_dict(p) for p in svc.list_staged()]
    assert items, "expected a staged memory proposal"
    d = items[0]
    # White-labeled: no upstream codenames / FR jargon in user-facing fields.
    blob = (d.get("label", "") + d.get("text", "")).lower()
    assert "hermes" not in blob and "memory.md" not in blob and "fr-mind" not in blob
    assert d["claims_authority"] is True  # flagged for the reviewer, advisory only
