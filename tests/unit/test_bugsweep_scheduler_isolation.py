"""Scheduler concurrency/idempotency bug-sweep regression tests (bugfix-sweep-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id


def _campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=True))
    return cid


class _RecordingLoop:
    def __init__(self):
        self.ticked = []

    def tick(self, campaign_id, now=None):
        self.ticked.append(str(campaign_id))


# --- CONC-2: a fresh storage/session is built per tick ----------------------
def test_conc2_scheduler_builds_isolated_storage_per_tick():
    """CONC-2: when a tick-services factory is configured, each tick builds its OWN
    storage + agent loop (not the request-scoped singleton) and closes its session."""
    shared_storage = InMemoryStorage()
    _campaign(shared_storage)
    shared_loop = _RecordingLoop()

    built_storages = []
    closed_sessions = []

    class _FakeSession:
        def __init__(self, idx):
            self.idx = idx

        def close(self):
            closed_sessions.append(self.idx)

    def factory():
        # A brand-new storage + loop + session each call (per tick).
        tick_storage = InMemoryStorage()
        # Mirror the campaign so the tick has work to enumerate.
        for c in shared_storage.campaigns.list():
            tick_storage.campaigns.add(c)
        loop = _RecordingLoop()
        session = _FakeSession(len(built_storages))
        built_storages.append((tick_storage, loop))
        return {
            "storage": tick_storage,
            "agent_loop": loop,
            "digest_service": None,
            "notification_service": None,
            "final_approval_service": None,
            "_session": session,
        }

    sched = Scheduler(
        storage=shared_storage,
        agent_loop=shared_loop,
        tick_services_factory=factory,
    )

    day = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    sched.tick(day)
    sched.tick(day)

    # Two ticks -> two distinct per-tick storages/loops; the shared singleton is unused.
    assert len(built_storages) == 2
    assert built_storages[0][0] is not built_storages[1][0]
    assert built_storages[0][0] is not shared_storage
    assert shared_loop.ticked == []  # request-scoped loop never ticked
    # Each per-tick session was closed after its tick (no leaked sessions).
    assert closed_sessions == [0, 1]


# --- IDEM-1: scheduler does not double-deliver the daily digest -------------
def test_idem1_scheduler_does_not_deliver_digest_itself():
    """IDEM-1: the scheduler no longer delivers the digest (the loop does), so a digest
    service handed to it is NOT invoked by the scheduler — only the loop tick runs."""
    storage = InMemoryStorage()
    _campaign(storage)

    class _BoomDigest:
        def deliver(self, campaign_id, criteria=None):  # pragma: no cover - must not run
            raise AssertionError("scheduler must not deliver the digest (IDEM-1)")

    loop = _RecordingLoop()
    sched = Scheduler(storage=storage, agent_loop=loop, digest_service=_BoomDigest())

    day = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out = sched.tick(day)
    sched.tick(day + timedelta(hours=1))
    # Loop ran each tick; scheduler reports no self-delivered digests.
    assert out["daily_digests"] == []
    assert len(loop.ticked) == 2
