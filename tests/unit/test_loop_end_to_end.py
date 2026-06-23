"""Hermetic end-to-end smoke test of the autonomous loop (FR-AGENT, FR-DIG, FR-MIND).

This locks in "the loop runs end-to-end": one or more ``Scheduler.tick(now)`` calls
drive the WHOLE pipeline through the REAL services (no Postgres, no network, no real
sleeps — an injected clock + in-memory adapters), and the new learning hooks (the
curation nudge + the per-tick status heartbeat) run without breaking the tick.

What a tick must PROGRESS, asserted on real state (not just "no exception"):

* **Discovery -> viability scoring**: seeded postings get a persisted
  ``viability_score`` (the real ``ScoringService`` local-first lexical path).
* **Daily digest**: the real ``DigestService`` materializes a digest-approval pending
  action per viable posting (delivered once per UTC day, FR-DIG-1).
* **Approval -> pre-fill -> the review/stop-boundary**: a digest-approved posting
  becomes an ``Application`` that the durable pipeline advances to
  ``AWAITING_FINAL_APPROVAL`` — the human-in-the-loop gate. The **stop-boundary
  holds**: the loop does NOT self-authorize a submit (no ``OutcomeEvent``) and never
  walks an account-create/submit on its own.
* **Learning hooks**: the curation nudge runs (reviews recent run summaries + stages
  memory/skill proposals for human approval, FR-MIND-7/-9), idempotent across re-ticks
  the same UTC day; the scheduler status heartbeat reports the tick — all without
  breaking the pipeline tick.

Everything below is wired with the REAL services where they are hermetic
(``InMemoryStorage``, ``ScoringService(llm=None)`` + ``LocalEmbedding``,
``DigestService``, ``CriteriaService``, ``AgentRunService``, the checkpoint-shim
orchestrator, the real ``CurationService`` + ``CurationLedger``); only the browser
pre-fill (which would launch a real browser) is faked, landing the application
truthfully at the final-approval gate the loop persists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.memory.in_memory import InMemoryMemoryStore, InMemorySkillStore
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.curation_service import (
    CurationLedger,
    CurationService,
    RunSummary,
)
from applicant.application.services.digest_service import DigestService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.application.services.scheduler import Scheduler
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId, DecisionId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# --- a truthful pre-fill that lands at the final-approval gate ---------------
class _PrefillResult:
    def __init__(self, state: ApplicationState) -> None:
        self.state = state


class _GatePrefill:
    """Models the browser pre-fill: it walks the application to the human gate.

    The REAL pre-fill drives a stealth browser, so it is the one piece we cannot run
    hermetically. It still returns the SAME ``state`` contract the loop persists, so
    the pipeline lands at AWAITING_FINAL_APPROVAL exactly as production does — the
    review/stop-boundary. It NEVER returns a submitted/terminal state: the loop must
    not self-authorize past the human gate.
    """

    def __init__(self) -> None:
        self.calls = 0

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls += 1
        return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)


class _OpenGate:
    """The automated-work gate, open (onboarding + LLM satisfied, FR-ONBOARD-2)."""

    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def is_automated_work_allowed(self) -> bool:
        return self.allowed


# --- builders ---------------------------------------------------------------
def _seed_campaign(storage, *, target: int = 15) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(
            id=cid,
            name="E2E",
            run_mode=RunMode.CONTINUOUS,
            throughput_target=target,
            # Onboarding-seeded criteria so scoring/digest run against real criteria.
            criteria={"titles": ["Engineer"], "keywords": ["python"]},
        )
    )
    return cid


def _seed_posting(storage, cid, *, title="Engineer", approve=False) -> JobPostingId:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title=title,
            company="Acme",
            description="Build python services",
            source_url=f"http://jobs/{new_id()}",
        )
    )
    if approve:
        # A digest-approval decision (the user approved this row in the digest).
        storage.decisions.add(
            Decision(
                id=DecisionId(new_id()),
                application_id=str(pid),
                type=DecisionType.APPROVE,
            )
        )
    return pid


def _run_summaries(cid):
    """A recent-run summaries provider the scheduler hands to the curation nudge."""

    def provider(_storage, _now):
        return [
            RunSummary(
                run_id="run-1",
                campaign_id=str(cid),
                text="Cleared the Workday location react-select before typing the city.",
                tool_calls=7,
                succeeded=True,
                topic="acme-workday",
            )
        ]

    return provider


def _assemble(storage, orch, cid, *, gate_allowed=True, summaries_provider=None):
    """Wire the loop + scheduler with the REAL services (browser pre-fill faked).

    Returns ``(scheduler, prefill, curation_ledger)`` for assertions.
    """
    embedding = LocalEmbedding()
    scoring = ScoringService(storage, llm=None, embedding=embedding)
    criteria = CriteriaService(storage)
    pending = PendingActionsService(storage)
    digest = DigestService(
        storage,
        notification=None,
        scoring=scoring,
        criteria=criteria,
        pending_actions=pending,
    )
    gate = _OpenGate(allowed=gate_allowed)
    prefill = _GatePrefill()

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=scoring,
        digest_service=digest,
        criteria_service=criteria,
        prefill_service=prefill,
        orchestrator=orch,
        setup_service=gate,
    )

    ledger = CurationLedger()
    curation = CurationService(
        memory_store=InMemoryMemoryStore(),
        skill_store=InMemorySkillStore(),
        ledger=ledger,
    )
    sched = Scheduler(
        storage=storage,
        agent_loop=loop,
        digest_service=digest,
        setup_service=gate,
        curation_service=curation,
        curation_schedule="daily",
        run_summaries_provider=summaries_provider or _run_summaries(cid),
        interval_seconds=60.0,
    )
    return sched, prefill, ledger


# --- the end-to-end smoke ----------------------------------------------------
@pytest.mark.unit
def test_one_tick_drives_discovery_digest_prefill_and_learning(tmp_path):
    """ONE scheduler tick drives the whole pipeline to the review/stop-boundary AND
    runs the learning hooks without breaking the tick."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _seed_campaign(storage)
    approved = _seed_posting(storage, cid, title="Python Engineer", approve=True)
    # A second, off-criteria posting: discovered + scored but BELOW the viability bar
    # (the real lexical scorer discriminates), so it is excluded from the digest.
    _seed_posting(storage, cid, title="Warehouse Associate")

    sched, prefill, ledger = _assemble(storage, orch, cid)

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out = sched.tick(now)

    # --- the tick ran for the one active campaign ---
    assert out["ticked"] == [str(cid)]

    # --- discovery -> viability scoring: every posting got a persisted score ---
    postings = storage.postings.list_for_campaign(cid)
    assert len(postings) == 2
    # The real scorer persisted a numeric viability score for EVERY posting (progress
    # that did not exist before the tick), and it discriminates between them: the
    # on-criteria role outscores the off-criteria one.
    assert all(p.viability_score is not None for p in postings)
    by_title = {p.title: p.viability_score for p in postings}
    assert by_title["Python Engineer"] > by_title["Warehouse Associate"]

    # --- daily digest: a digest-approval pending action per VIABLE posting (FR-DIG-1).
    # Only the viable role makes the digest; the below-threshold one is dropped.
    pending = storage.pending_actions.list_open(cid)
    assert [pa.kind for pa in pending] == ["digest_approval"]
    assert str(pending[0].payload["posting_id"]) == str(approved)

    # --- approval -> pre-fill -> the review/stop-boundary ---
    apps = storage.applications.list_for_campaign(cid)
    # Exactly the ONE approved posting became an application (the other was only
    # discovered/scored — not approved, so no application was started for it).
    assert len(apps) == 1
    app = apps[0]
    assert str(app.posting_id) == str(approved)
    assert prefill.calls == 1
    # It advanced to the human-in-the-loop gate — the pipeline handed off here.
    assert app.status is ApplicationState.AWAITING_FINAL_APPROVAL

    # --- the stop-boundary HOLDS: no self-authorized submit ---
    assert storage.outcomes.list_for_application(app.id) == []
    assert app.status is not ApplicationState.SUBMITTED_BY_USER
    assert app.status is not ApplicationState.FINISHED_BY_ENGINE

    # --- learning hooks ran on the tick (curation nudge) ---
    assert out["curation"]["ran"] is True
    assert out["curation"]["reviewed"] == 1
    assert out["curation"]["staged"] == 2  # one memory + one skill, staged for review
    assert len(ledger.staged) == 2  # held for HUMAN approval (FR-MIND-9), not applied

    # --- status hook: the heartbeat reports this tick + the next-tick estimate ---
    state = sched.state(now)
    assert state["last_tick"] == now.isoformat()
    assert state["running"] is False
    assert state["next_tick"] == (now + timedelta(seconds=60)).isoformat()


@pytest.mark.unit
def test_multi_day_ticks_progress_and_curation_is_idempotent(tmp_path):
    """Ticks across simulated days keep the pipeline at the gate (no auto-advance past
    the human) and the curation nudge runs once per UTC day (idempotent on re-tick)."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _seed_campaign(storage)
    _seed_posting(storage, cid, title="Python Engineer", approve=True)

    sched, prefill, ledger = _assemble(storage, orch, cid)

    day1 = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(day1)
    app = storage.applications.list_for_campaign(cid)[0]
    assert app.status is ApplicationState.AWAITING_FINAL_APPROVAL
    assert out1["curation"]["ran"] is True
    assert out1["curation"]["reviewed"] == 1

    # --- re-tick the SAME UTC day: the nudge does NOT re-run (idempotent cadence) ---
    out_same = sched.tick(day1 + timedelta(minutes=5))
    assert out_same["curation"] == {"ran": False, "reason": "already_ran_today"}
    # The application is STILL parked at the gate (the loop never self-advances past
    # the human-in-the-loop point) and nothing was submitted.
    app = storage.applications.list_for_campaign(cid)[0]
    assert app.status is ApplicationState.AWAITING_FINAL_APPROVAL
    assert storage.outcomes.list_for_application(app.id) == []
    # Re-ticking did not duplicate the digest pending actions.
    assert [pa.kind for pa in storage.pending_actions.list_open(cid)] == [
        "digest_approval"
    ]
    # The curation ledger holds exactly the first day's proposals — no duplicates.
    assert len(ledger.staged) == 2
    assert "run-1" in ledger.proposed_runs

    # --- a NEW UTC day: the nudge runs again (per-day cadence) ---
    out2 = sched.tick(day1 + timedelta(days=1))
    # run-1 was already proposed (deduped by the process-lived ledger), so the second
    # day reviews nothing new but still "runs" the nudge once for the day.
    assert out2["curation"]["ran"] is True
    assert out2["curation"]["reviewed"] == 0
    assert len(ledger.staged) == 2  # no new proposals (run-1 already curated)


@pytest.mark.unit
def test_closed_gate_starts_no_new_work_but_tick_does_not_break(tmp_path):
    """Before onboarding/LLM are satisfied the gate is closed: a tick starts NO new
    work (no scoring/digest/pipeline, no curation) yet still completes cleanly — the
    learning hooks degrade to a gated no-op rather than breaking the tick."""
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _seed_campaign(storage)
    _seed_posting(storage, cid, title="Python Engineer", approve=True)

    sched, prefill, ledger = _assemble(storage, orch, cid, gate_allowed=False)

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out = sched.tick(now)

    # The campaign was ticked, but the closed gate stopped all NEW work.
    assert out["ticked"] == [str(cid)]
    assert storage.applications.list_for_campaign(cid) == []  # no pipeline started
    assert prefill.calls == 0
    assert storage.pending_actions.list_open(cid) == []  # no digest delivered
    # The learning hook is gated off, not crashed.
    assert out["curation"] == {"ran": False, "reason": "gated"}
    assert ledger.staged == []
    # The status heartbeat still reflects a completed tick (FR-OBS-2).
    assert sched.state(now)["last_tick"] == now.isoformat()
