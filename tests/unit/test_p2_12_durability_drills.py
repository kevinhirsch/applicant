"""P2-12 — Durability drills (road-to-market backlog).

Proves the durable-orchestration layer survives restarts: the default
``ORCHESTRATOR_BACKEND=shim`` file-backed checkpoint store
(``adapters/orchestration/checkpoint_shim.py``), the real per-application durable
pipeline (``application/workflows/application_pipeline.py``) that runs on top of
it, and the scheduler that rebuilds a fresh ``AgentLoop`` per tick
(``application/services/scheduler.py`` / ``container._build_tick_services``).

The DoD names four drills — "each drill passes (restart-survival) or files a bug":

  1. Kill the engine mid-prefill.
  2. Kill the browser mid-run.
  3. Hit a CAPTCHA wall.
  4. Take a source offline.

All four are drilled HERMETICALLY below (no real Postgres/DBOS/browser/network —
those pieces already run under ``@pytest.mark.integration`` elsewhere, see the "NOT
drilled here" list at the bottom of this docstring), by simulating the kill/restart
boundary in-process: a checkpoint written to a ``tmp_path`` directory is read back
by a BRAND-NEW ``CheckpointShimOrchestrator``/``AgentLoop`` instance, exactly
modelling a process restart over the same on-disk checkpoint store / database.

Drills 2 and 3 did NOT simply pass — they found two real, previously-undiscovered
durability bugs, now fixed in this same change (H-series honesty: the drill is
reported exactly as it ran, including what it broke):

  * **Terminal hand-off gap** (drill 2): a pre-fill that landed the §7 TERMINAL
    ``FAILED`` state (e.g. a crashed browser tab/context mid-walk, #207/#336) fell
    through the durable pipeline into material generation + a final-approval
    request for an application that had already died. At the ``AgentLoop`` level
    this ALSO leaked the sandbox capacity slot forever (``yield_for_block`` only
    releases on a ``_YIELDING_STATES`` member, and ``FAILED`` is not one) — a
    single browser crash would eventually starve every future pre-fill of sandbox
    capacity. Fixed: ``run_pipeline`` now stops (``status="failed"``) the instant
    pre-fill reports a ``core.state_machine.TERMINAL_STATES`` member, and
    ``AgentLoop._apply_outcome`` releases the slot + clears the checkpoint on that
    outcome exactly like ``done``. See ``docs/known-issues.md`` (K3, resolved).

  * **Stale-checkpoint hand-off lockout** (drill 3): once the durable "prefill"
    step checkpointed a BLOCKED_*/AWAITING_ACCOUNT_HUMAN_STEP/EMERGENCY_DATA_HANDOFF
    hand-off, ``run_step`` never re-ran it — EVERY later re-drive (the scheduler's
    per-tick resume, or a boot-time restart recovery) replayed the stale cached
    hand-off dict forever, so the application could never advance even after a
    human resolved the block (e.g. solved the CAPTCHA, supplied the missing
    attribute). Fixed: ``AgentLoop._apply_outcome`` clears the workflow's
    checkpoint on a pure pre-fill hand-off (NOT on ``MATERIAL_REVIEW``, which is
    designed to stay cached — its own re-check reads approval live, #1) so the
    next drive re-enters ``_prefill()`` and picks the right ``resume_after_*``
    entry point (#4). See ``docs/known-issues.md`` ("stale-checkpoint hand-off
    lockout", resolved).

Scheduler TICK ISOLATION (CONC-2: a fresh per-tick storage/session/loop; one
campaign's failure/skip never sinks another's tick) already has dedicated,
passing coverage in ``tests/unit/test_bugsweep_scheduler_isolation.py`` and the
``tests/unit/test_scheduler*.py`` family — not re-duplicated here.

NOT drilled here (named explicitly per the H-series — no silent claims about
scope):
  * A real Postgres kill / DBOS-backed workflow restart. Needs a live Postgres;
    covered by ``tests/integration/test_dbos_orchestrator.py`` and
    ``tests/integration/test_durable_workflow.py`` — ``@pytest.mark.integration``,
    which is not a per-PR gate (runs on ``workflow_dispatch`` / weekly, see
    ``ci-integration.yml``).
  * A real browser process actually dying (a live Playwright/patchright
    ``TargetClosedError``). ``PrefillService._continue_pages``'s own crash
    boundary (which this drill's fix sits ABOVE) is already exercised against an
    in-memory browser raising mid-walk in
    ``tests/bdd/steps/test_enh_n4_browser_steps.py`` (issues #207/#336). This file
    does not launch a browser, real or fake-in-memory; it starts from that
    boundary's already-proven output (a structured ``FAILED`` result).
  * A real CAPTCHA/anti-bot challenge being solved or bypassed. The opt-in solver
    port (#350, ``PrefillService._try_solve_captcha``) is unit-tested elsewhere;
    this drill exercises the DURABLE hand-off + resume path around that decision
    (``BLOCKED_DETECTION`` -> resume -> advance), not the solve/bypass itself.
  * A real external job-board endpoint going offline over the network. The H2
    per-source vocabulary (``SOURCE_ERROR`` / ``yield_stats.last_run`` / digest
    shortfall lines) is thoroughly covered in
    ``tests/unit/test_h2_no_silent_underdelivery.py``; this drill proves the
    SERVICE/TICK layer above it survives + degrades honestly, using a fake
    adapter that raises for one source (mirroring the real aggregator contract).
"""

from __future__ import annotations

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.capacity_service import CapacityService
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.workflows.application_pipeline import (
    FINAL_APPROVAL_TOPIC,
    PipelineContext,
    register,
    run_pipeline,
)
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, DecisionId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


# --- shared small fakes (mirrors the local-fake convention in test_agent_loop.py) --
class _FakeScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="strong fit")

    def is_viable(self, scoring):
        return True


class _FakeDigest:
    def deliver(self, campaign_id, criteria=None):
        return {"payload": {"rows": [{"posting_id": "p"}]}}


class _PrefillResult:
    def __init__(self, state):
        self.state = state


class _FakeSubmission:
    def __init__(self):
        self.recorded: list[str] = []

    def record_submission(self, application, *, source, attributes_used=None, **kw):
        from applicant.core.entities.outcome_event import OutcomeEvent
        from applicant.core.ids import OutcomeEventId

        self.recorded.append(str(application.id))
        return OutcomeEvent(
            id=OutcomeEventId(new_id()),
            application_id=application.id,
            type="submitted",
            source=source,
        )


def _make_campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=RunMode.CONTINUOUS, throughput_target=15, schedule={})
    )
    return cid


def _approve_posting(storage, cid, *, title="Engineer") -> JobPostingId:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title=title, company="Acme", source_url="http://x")
    )
    storage.decisions.add(
        Decision(id=DecisionId(new_id()), application_id=str(pid), type=DecisionType.APPROVE)
    )
    return pid


# === Drill 1: kill the engine mid-prefill -> restart survival ==================
@pytest.mark.unit
class TestDrillKillEngineMidPrefill:
    """A hard kill (``docker kill`` / OOM) DURING the "prefill" step's own body —
    before it can checkpoint — must lose only that in-flight attempt: the next
    boot (a brand-new orchestrator instance over the SAME checkpoint directory)
    re-runs pre-fill from scratch and the workflow completes normally. This is
    the mirror image of ``tests/integration/test_durable_workflow.py`` (which
    kills AFTER pre-fill checkpointed, inside "submit", and proves NO re-run) —
    together the two prove both halves of the checkpoint contract."""

    def test_kill_during_prefill_then_restart_completes_the_workflow(self, tmp_path):
        ckpt = str(tmp_path / "ckpt")
        wf_id = "application:drill-kill-mid-prefill"
        calls: list[str] = []

        class _EngineKilled(Exception):
            pass

        def _prefill_that_gets_killed() -> dict:
            calls.append("prefill-attempt-killed")
            raise _EngineKilled("simulated docker kill mid pre-fill page walk")

        # --- run 1: the engine dies inside the live "prefill" step body --------
        orch1 = CheckpointShimOrchestrator(ckpt)
        ctx1 = PipelineContext(application_id="drill-1", prefill=_prefill_that_gets_killed)
        with pytest.raises(_EngineKilled):
            run_pipeline(orch1, wf_id, ctx=ctx1)

        # Nothing durably completed from the killed attempt; the workflow is
        # correctly reported as pending recovery work for the next boot.
        assert orch1.completed_steps(wf_id) == []
        assert wf_id in orch1.recover_pending()

        # --- restart: a BRAND-NEW orchestrator instance, SAME checkpoint dir ----
        orch2 = CheckpointShimOrchestrator(ckpt)
        register(orch2)
        orch2.send(wf_id, FINAL_APPROVAL_TOPIC, {"decision": "finished_by_engine"})
        submitted: list[dict] = []
        ctx2 = PipelineContext(
            application_id="drill-1",
            prefill=lambda: (
                calls.append("prefill-attempt-resumed")
                or {"state": "AWAITING_FINAL_APPROVAL"}
            ),
            submit=lambda decision: (submitted.append(decision) or {"recorded": True}),
        )
        result = run_pipeline(orch2, wf_id, ctx=ctx2)

        assert result["status"] == "done"
        # The killed attempt's browser work counted for nothing (never checkpointed)
        # so the full step re-ran fresh on restart — it is NOT silently skipped.
        assert calls == ["prefill-attempt-killed", "prefill-attempt-resumed"]
        assert submitted == [{"decision": "finished_by_engine"}]


# === Drill 2: kill the browser mid-run =========================================
@pytest.mark.unit
class TestDrillKillBrowserMidRun:
    """PrefillService's OWN crash boundary (#207/#336) already turns a real
    browser exception into a structured ``FAILED`` result instead of letting it
    escape (drilled with an in-memory browser in
    ``tests/bdd/steps/test_enh_n4_browser_steps.py``). This drill starts from
    that boundary's output and proves the layer ABOVE it: the durable pipeline
    + the run loop must treat a TERMINAL ``FAILED`` pre-fill as fully stopped —
    they did not, until this same change (see the module docstring)."""

    def test_terminal_failed_prefill_stops_the_pipeline_before_material_or_submit(
        self, tmp_path
    ):
        calls: list[str] = []
        ctx = PipelineContext(
            application_id="drill-2",
            prefill=lambda: (calls.append("prefill") or {"state": "FAILED"}),
            material_warranted=lambda: (calls.append("material_warranted") or True),
            prepare_material=lambda: (calls.append("prepare_material") or {}),
            material_approved=lambda: (calls.append("material_approved") or True),
            request_final_approval=lambda: (
                calls.append("request_final_approval") or "handle"
            ),
            submit=lambda decision: (calls.append("submit") or {"recorded": True}),
            teardown=lambda: calls.append("teardown"),
        )
        orch = CheckpointShimOrchestrator(str(tmp_path / "ckpt"))

        result = run_pipeline(orch, "wf-drill-2", ctx=ctx)

        assert result["status"] == "failed"
        assert result["failure_state"] == "FAILED"
        # ONLY prefill + teardown ran — material generation, the approval request,
        # and submit never fired for an application that already died.
        assert calls == ["prefill", "teardown"]
        assert orch.completed_steps("wf-drill-2") == ["prefill", "teardown"]
        # A terminal checkpoint (teardown recorded) is correctly NOT "pending" —
        # a restart must not re-drive a dead application forever.
        assert orch.recover_pending() == []

    def test_browser_crash_releases_capacity_and_clears_the_checkpoint(self, tmp_path):
        """The full AgentLoop-level regression: before the fix, a FAILED pre-fill
        leaked the sandbox slot forever (proved by stashing the fix and re-running
        this exact scenario — see the module docstring / docs/known-issues.md)."""

        class _CrashingBrowserPrefill:
            def prefill_application(self, application, url, attributes=None, *, cautious=True):
                return _PrefillResult(ApplicationState.FAILED)

        storage = InMemoryStorage()
        orch = CheckpointShimOrchestrator(str(tmp_path / "ckpt"))
        cid = _make_campaign(storage)
        _approve_posting(storage, cid)
        capacity = CapacityService(orch, sandbox_concurrency=1)

        loop = AgentLoop(
            storage=storage,
            agent_run_service=AgentRunService(storage),
            scoring_service=_FakeScoring(),
            digest_service=_FakeDigest(),
            prefill_service=_CrashingBrowserPrefill(),
            capacity_service=capacity,
            orchestrator=orch,
        )

        from datetime import UTC, datetime

        result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
        app = storage.applications.list_for_campaign(cid)[0]

        assert app.status == ApplicationState.FAILED
        assert str(app.id) in result.failed
        assert result.completed == []
        # The checkpoint is cleared (terminal) — a restart will not re-drive it.
        assert orch.recover_pending() == []
        # The sandbox slot was released — a second application can be admitted to
        # the (single-slot) queue. Before the fix this returned False forever.
        assert capacity.admit_sandbox("a-different-application") is True


# === Drill 3: hit a CAPTCHA wall (BLOCKED_DETECTION) ===========================
@pytest.mark.unit
class TestDrillCaptchaWall:
    """``BLOCKED_DETECTION`` is the §7 state a CAPTCHA/anti-bot wall lands an
    application in. Proves the durable resume path across ticks — and across a
    simulated engine restart while parked at the wall — actually advances once
    the block clears, which it did NOT before this change's fix (see the module
    docstring)."""

    class _SeqCaptchaPrefill:
        def __init__(self):
            self.calls: list[str] = []

        def prefill_application(self, application, url, attributes=None, *, cautious=True):
            self.calls.append("prefill_application")
            return _PrefillResult(ApplicationState.BLOCKED_DETECTION)

        def resume_after_detection(self, application, attributes, *, cautious=True):
            self.calls.append("resume_after_detection")
            return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)

    def test_blocked_detection_resumes_and_completes_across_ticks(self, tmp_path):
        from datetime import UTC, datetime

        storage = InMemoryStorage()
        orch = CheckpointShimOrchestrator(str(tmp_path / "ckpt"))
        cid = _make_campaign(storage)
        _approve_posting(storage, cid)
        spy = self._SeqCaptchaPrefill()
        submission = _FakeSubmission()

        loop = AgentLoop(
            storage=storage,
            agent_run_service=AgentRunService(storage),
            scoring_service=_FakeScoring(),
            digest_service=_FakeDigest(),
            prefill_service=spy,
            submission_service=submission,
            orchestrator=orch,
        )
        loop._resume_backoff_seconds = 0  # drive every tick, no real-time backoff

        t1 = datetime(2026, 6, 16, tzinfo=UTC)
        loop.run_once(cid, now=t1)
        app = storage.applications.list_for_campaign(cid)[0]
        assert app.status == ApplicationState.BLOCKED_DETECTION
        assert spy.calls == ["prefill_application"]

        # Tick 2 (e.g. the human clears the CAPTCHA in between): the SAME
        # workflow_id must re-enter pre-fill and pick the targeted resume entry
        # point (#4) — before the fix it replayed the stale cached hand-off
        # forever and NEVER called resume_after_detection.
        t2 = datetime(2026, 6, 16, 0, 1, tzinfo=UTC)
        loop.run_once(cid, now=t2)
        assert spy.calls == ["prefill_application", "resume_after_detection"]
        app = storage.applications.list_for_campaign(cid)[0]
        assert app.status == ApplicationState.AWAITING_FINAL_APPROVAL

        # Tick 3: deliver the approval decision and let it submit.
        orch.send(
            f"application:{app.id}", FINAL_APPROVAL_TOPIC, {"decision": "finished_by_engine"}
        )
        t3 = datetime(2026, 6, 16, 0, 2, tzinfo=UTC)
        loop.run_once(cid, now=t3)
        assert str(app.id) in submission.recorded

    def test_engine_restart_while_parked_at_captcha_wall_still_resumes(self, tmp_path):
        """Simulates an engine restart (fresh orchestrator + fresh AgentLoop, the
        scheduler's own per-tick rebuild taken to its extreme) while an
        application sits at the CAPTCHA wall. Resumability survives the restart
        because it is driven by the PERSISTED ``Application.status`` (real
        storage), not a durable-orchestration checkpoint — and the checkpoint
        itself is correctly empty (no stale hand-off left to relitigate)."""
        from datetime import UTC, datetime

        storage = InMemoryStorage()
        ckpt_dir = str(tmp_path / "ckpt")
        orch1 = CheckpointShimOrchestrator(ckpt_dir)
        cid = _make_campaign(storage)
        _approve_posting(storage, cid)
        spy1 = self._SeqCaptchaPrefill()

        loop1 = AgentLoop(
            storage=storage,
            agent_run_service=AgentRunService(storage),
            scoring_service=_FakeScoring(),
            digest_service=_FakeDigest(),
            prefill_service=spy1,
            orchestrator=orch1,
        )
        loop1.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
        app = storage.applications.list_for_campaign(cid)[0]
        assert app.status == ApplicationState.BLOCKED_DETECTION
        # Nothing left pending on the orchestrator for a boot-time re-drive to
        # (wrongly) replay — the persisted status is the real source of truth.
        assert orch1.recover_pending() == []

        # --- "restart": brand-new orchestrator + brand-new AgentLoop instance ---
        orch2 = CheckpointShimOrchestrator(ckpt_dir)
        spy2 = self._SeqCaptchaPrefill()
        submission2 = _FakeSubmission()
        loop2 = AgentLoop(
            storage=storage,
            agent_run_service=AgentRunService(storage),
            scoring_service=_FakeScoring(),
            digest_service=_FakeDigest(),
            prefill_service=spy2,
            submission_service=submission2,
            orchestrator=orch2,
        )
        loop2._resume_backoff_seconds = 0
        loop2.run_once(cid, now=datetime(2026, 6, 16, 0, 5, tzinfo=UTC))
        assert spy2.calls == ["resume_after_detection"]
        app = storage.applications.list_for_campaign(cid)[0]
        assert app.status == ApplicationState.AWAITING_FINAL_APPROVAL


# === Drill 4: take a source offline =============================================
@pytest.mark.unit
class TestDrillSourceOffline:
    """A discovery source going down must not lose the OTHER sources' results
    (H2: honest per-source degradation, already deeply covered in
    ``tests/unit/test_h2_no_silent_underdelivery.py``) nor crash the tick even
    when the adapter itself does not degrade gracefully."""

    class _MixedHealthDiscovery:
        """One healthy source, one offline — mirrors the well-behaved real
        aggregator (``JobSpySearxngDiscovery``) contract: it catches each
        source's own failure and reports it per-source in
        ``last_source_outcomes`` rather than losing the whole run."""

        def __init__(self):
            self.last_source_outcomes: list[dict] = []

        def available_sources(self):
            return ["healthy-board", "offline-board"]

        def is_source_enabled(self, key):
            return True

        def apply_toggles(self, toggles):
            return None

        def search(self, campaign_id, criteria, **kwargs):
            self.last_source_outcomes = [
                {"source_key": "healthy-board", "status": "ok", "found": 1},
                {
                    "source_key": "offline-board",
                    "status": "error",
                    "found": 0,
                    "error": "connection refused",
                },
            ]
            return [
                JobPosting(
                    id=JobPostingId(new_id()),
                    campaign_id=campaign_id,
                    title="Still-working-board role",
                    company="Acme",
                    source_url="http://healthy-board/1",
                    source_key="healthy-board",
                )
            ]

    def test_discovery_service_survives_one_source_going_offline(self):
        from applicant.adapters.embedding.local_embedding import LocalEmbedding

        storage = InMemoryStorage()
        cid = _make_campaign(storage)
        disc = self._MixedHealthDiscovery()
        svc = DiscoveryService(storage, disc, LocalEmbedding())

        kept = svc.run_discovery(cid, SearchCriteria(campaign_id=cid))

        # The healthy source's posting is still delivered — one source's outage
        # never loses the others' results.
        assert len(kept) == 1
        assert kept[0].source_key == "healthy-board"
        # The outage is durably visible (H2), not silently dropped.
        down = storage.discovery_sources.get(cid, "offline-board")
        assert down.yield_stats["last_run"]["status"] == "error"
        assert down.yield_stats["last_run"]["error"] == "connection refused"
        healthy = storage.discovery_sources.get(cid, "healthy-board")
        assert healthy.yield_stats["last_run"]["status"] == "ok"

    def test_agent_loop_tick_survives_a_fully_unreachable_discovery_adapter(
        self, tmp_path
    ):
        """The coarser case: the adapter itself does not degrade gracefully (its
        ``run_discovery`` raises straight through, e.g. every source's board is
        unreachable this tick). ``AgentLoop`` has its own outer boundary around
        discovery (``agent_loop.py`` around ``_run_discovery``) — the tick must
        still complete rather than stall the whole campaign."""
        from datetime import UTC, datetime

        class _TotallyDownDiscovery:
            def run_discovery(self, campaign_id, criteria=None):
                raise ConnectionError("every job board is unreachable this tick")

        storage = InMemoryStorage()
        orch = CheckpointShimOrchestrator(str(tmp_path / "ckpt"))
        cid = _make_campaign(storage)

        loop = AgentLoop(
            storage=storage,
            agent_run_service=AgentRunService(storage),
            discovery_service=_TotallyDownDiscovery(),
            scoring_service=_FakeScoring(),
            digest_service=_FakeDigest(),
            orchestrator=orch,
        )

        result = loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))

        # The tick completed (did not raise / stall) — discovery just contributed
        # nothing this pass; the NEXT tick tries again.
        assert result.ran is True
        assert result.discovered == 0
