"""Bugsweep batch I: data-integrity / state-machine fixes.

Each test is a fail-before/pass-after regression for one verified bug:

#1 digest pending-action must not write a posting id into the application_id FK
   column (IntegrityError on Postgres; here reproduced on SQLite + FK pragma).
#2 agent_loop must not bypass the state machine when landing the final-approval gate.
#3 the submission router must not synthesize an AWAITING_FINAL_APPROVAL record over a
   real persisted non-legal pre-state (must 409 instead).
#6 FieldMappingRepo.find() must be deterministic across lanes when many match.
#7 a scored posting must round-trip viability_score + rationale through storage.
#9 AgentRun.seq must stay monotonic across a simulated process restart.
"""

from __future__ import annotations

import tempfile

import pytest
from sqlalchemy import event

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.adapters.storage.models import Base
from applicant.adapters.storage.repositories import SqlAlchemyStorage
from applicant.adapters.storage.session import make_engine, make_session_factory
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.entities.job_posting import JobPosting
from applicant.core.errors import IllegalStateTransition
from applicant.core.ids import (
    AgentRunId,
    CampaignId,
    FieldMappingId,
    JobPostingId,
    new_id,
)


def _fk_sqlite_storage():
    """A SQLite SqlAlchemyStorage with foreign_keys=ON, mirroring Postgres FKs."""
    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):  # pragma: no cover - trivial pragma hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    return SqlAlchemyStorage(session), session, engine


def _seed_posting(storage, cid, *, title="Senior Python Engineer"):
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title=title,
            company="Acme",
            source_url="https://acme.test/job",
            work_mode="remote",
            description="python fastapi",
            source_key="jobspy:indeed",
        )
    )
    storage.commit()
    return pid


# --- #1 digest FK ----------------------------------------------------------
def test_digest_deliver_commits_without_fk_violation_on_sqlite_fk():
    """The digest-delivery flow must commit on a FK-enforcing store.

    Before the fix, ``deliver`` wrote the POSTING id into ``pending_actions.application_id``
    (an FK to ``applications.id``); with FKs enforced (Postgres / SQLite PRAGMA) the
    commit raised IntegrityError. After the fix the posting id lives in the payload
    and application_id stays NULL.
    """
    storage, session, engine = _fk_sqlite_storage()
    try:
        cid = CampaignId(new_id())
        storage.campaigns.add(Campaign(id=cid, name="C"))
        storage.commit()
        pid = _seed_posting(storage, cid)

        pending = PendingActionsService(storage)
        notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
        digest = DigestService(
            storage,
            notifier,
            scoring=None,  # no scoring -> every posting is a row
            notification_service=NotificationService(notifier),
            pending_actions=pending,
        )
        # Must not raise IntegrityError.
        digest.deliver(cid)

        items = [a for a in pending.list_pending(cid) if a.kind == "digest_approval"]
        assert len(items) == 1
        # The FK column is NULL; the posting id lives in the payload.
        assert items[0].application_id is None
        assert items[0].payload.get("posting_id") == str(pid)
    finally:
        session.close()
        engine.dispose()


def test_digest_approve_resolves_pending_by_posting_id():
    """Approving a digest item clears its portal entry (resolve by posting id)."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    pid = _seed_posting(storage, cid)

    pending = PendingActionsService(storage)
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    digest = DigestService(
        storage,
        notifier,
        scoring=None,
        notification_service=NotificationService(notifier),
        pending_actions=pending,
    )
    digest.deliver(cid)
    assert any(a.kind == "digest_approval" for a in pending.list_pending(cid))

    from applicant.core.ids import ApplicationId

    digest.approve(ApplicationId(str(pid)))  # digest-row id is the posting id
    assert not any(a.kind == "digest_approval" for a in pending.list_pending(cid))


# --- #6 deterministic field-mapping find -----------------------------------
def test_field_mapping_find_deterministic_across_lanes():
    """Two shared mappings for the same key resolve to the SAME one in both lanes."""
    ids = [FieldMappingId(f"fm-{i}") for i in (3, 1, 2)]

    def _populate(storage):
        for fid in ids:
            storage.field_mappings.add(
                FieldMapping(id=fid, site_key="workday", field_selector="email")
            )
        storage.commit()
        return storage.field_mappings.find("workday", "email")

    mem = InMemoryStorage()
    mem_found = _populate(mem)

    storage, session, engine = _fk_sqlite_storage()
    try:
        sql_found = _populate(storage)
    finally:
        session.close()
        engine.dispose()

    assert mem_found is not None and sql_found is not None
    # Deterministic ORDER BY id -> the lowest id ("fm-1") wins in BOTH lanes.
    assert str(mem_found.id) == str(sql_found.id) == "fm-1"


# --- #7 durable posting score ----------------------------------------------
def test_scored_posting_roundtrips_viability_score_and_rationale():
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    pid = _seed_posting(storage, cid)

    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    result = scoring.score_viability(pid)

    reloaded = storage.postings.get(pid)
    assert reloaded.viability_score == pytest.approx(result.score)
    assert reloaded.rationale.get("text") == result.rationale


# --- #9 monotonic agent-run seq across restart -----------------------------
def test_agent_run_seq_survives_simulated_restart():
    """A new run at an equal timestamp still wins after a process restart.

    Before the fix ``seq`` came from a process-local ``itertools.count`` that reset
    to 1 on restart, so a fresh run at the same timestamp got a LOWER seq than the
    persisted one and ``latest_intent`` returned the stale intent.
    """
    from datetime import UTC, datetime

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()

    ts = datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)
    # A persisted run from "before restart" with a high seq.
    storage.agent_runs.add(
        AgentRun(
            id=AgentRunId(new_id()),
            campaign_id=cid,
            intent_sentence="OLD intent",
            timestamp=ts,
            seq=99,
        )
    )
    storage.commit()

    # A fresh service (simulated restart) records a NEW run at the SAME timestamp.
    svc = AgentRunService(storage)
    import applicant.core.entities.agent_run as ar

    # Reset the process-local counter to prove we no longer depend on it.
    ar._SEQ = ar.itertools.count(1)
    new_run = svc.start_run(cid, "NEW intent")
    # The new run's seq must exceed the persisted max (derived, not process-local).
    assert new_run.seq > 99
    # Tie-break on equal timestamp now favors the newer run.
    storage.agent_runs.add(
        AgentRun(
            id=new_run.id,
            campaign_id=cid,
            intent_sentence="NEW intent",
            timestamp=ts,
            seq=new_run.seq,
        )
    )
    storage.commit()
    assert svc.latest_intent(cid) == "NEW intent"


# --- #2 state-machine integrity on submit ----------------------------------
def test_advance_to_gate_rejects_illegal_prestate():
    """``_advance_to`` raises on an illegal pre-state for AWAITING_FINAL_APPROVAL (#2)."""
    from applicant.application.services.agent_loop import AgentLoop
    from applicant.core.entities.application import Application
    from applicant.core.state_machine import ApplicationState

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    pid = _seed_posting(storage, cid)
    from applicant.core.ids import ApplicationId

    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=pid,
        status=ApplicationState.PREFILLING,  # illegal direct pre-state for the gate
    )
    storage.applications.add(app)
    storage.commit()

    loop = AgentLoop(storage=storage, agent_run_service=AgentRunService(storage))
    with pytest.raises(IllegalStateTransition):
        loop._advance_to(app, ApplicationState.AWAITING_FINAL_APPROVAL)


# --- #3 submission router enforces the gate ---------------------------------
def test_load_or_stub_409s_on_illegal_persisted_prestate():
    """A persisted app in PREFILLING/BLOCKED_* must 409, not be synthesized (#3)."""
    from applicant.app.routers.outcomes import _load_or_stub
    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId
    from applicant.core.state_machine import ApplicationState

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=JobPostingId(""),
            status=ApplicationState.PREFILLING,
        )
    )
    storage.commit()

    class _C:
        pass

    container = _C()
    container.storage = storage

    with pytest.raises(IllegalStateTransition):
        _load_or_stub(container, str(aid))


# --- #4 detection events persisted from the prefill path -------------------
def test_detection_event_persisted_when_cautious_mode_blocks():
    """Cautious-mode classification of a signal persists a DetectionEvent (#4)."""
    from applicant.adapters.browser.patchright_browser import PatchrightBrowser
    from applicant.adapters.detection.detection_monitor import DetectionMonitor
    from applicant.adapters.sandbox.local_sandbox import LocalSandbox
    from applicant.application.services.prefill_service import PrefillService
    from applicant.core.entities.application import Application
    from applicant.core.ids import ApplicationId
    from applicant.core.state_machine import ApplicationState

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    aid = ApplicationId(new_id())
    app = Application(
        id=aid,
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        root_url="https://acme.workday.test/apply",
    )
    storage.applications.add(app)  # so detection_events can resolve its campaign
    storage.commit()
    svc = PrefillService(
        storage=storage,
        browser=PatchrightBrowser(),
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        llm=None,
    )
    # Open a session + inject a rate-limit signal, then run the cautious detection
    # check directly (the same call wired into the pre-fill loop).
    svc._sandbox.provision(aid)
    svc._browser.open(aid, app.root_url)
    svc._browser.inject_page_signals(aid, status=429)
    event = svc._check_detection(aid)

    assert event is not None and event.signal_type == "rate_limited"
    events = storage.detection_events.list_for_application(aid)
    assert any(e.signal_type == "rate_limited" for e in events)
    assert storage.detection_events.list_for_campaign(cid)


# --- #4 onboarding completion writes an onboarding_profiles row -------------
def test_onboarding_completion_writes_profile_row():
    from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
    from applicant.application.services.onboarding_service import OnboardingService
    from applicant.ports.driving.onboarding import REQUIRED_SECTIONS

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()

    svc = OnboardingService(
        storage=storage, config_store=InMemoryAppConfigStore(), resume_parser=None
    )
    # Fill every required section so completion is allowed.
    for section in REQUIRED_SECTIONS:
        svc.save_section(str(cid), section, {"filled": "yes"})

    assert storage.onboarding_profiles.get_for_campaign(cid) is None  # before complete
    state = svc.complete(str(cid))
    assert state.complete is True
    profile = storage.onboarding_profiles.get_for_campaign(cid)
    assert profile is not None and profile.completion_flag is True
