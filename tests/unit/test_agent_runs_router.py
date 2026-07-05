"""Coverage: the agent-runs status endpoint's scheduler/campaign-health merge.

``GET /api/agent-runs/{campaign_id}/status`` (``routers/agent_runs.py``) merges
``AgentRunService.status`` with ``Scheduler.state()`` and, per dark-engine audit
#73, this campaign's OWN tick failures / overlap-skips (previously log-only) — so
the Run-controls status surface can show WHY a specific campaign's automated work
stalled, not just the whole-scheduler heartbeat. These call the router function
directly (a plain function; passing explicit kwargs bypasses FastAPI's ``Depends``
resolution) against real in-memory services, mirroring the Scheduler unit tests'
use of ``campaign_health``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.routers.agent_runs import run_status
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id


class _RecordingLoop:
    def tick(self, campaign_id, now=None):
        return None


def _campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    return cid


@pytest.mark.unit
def test_status_omits_campaign_health_when_never_failed():
    """A healthy campaign's payload carries no ``scheduler.campaign`` noise."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    svc = AgentRunService(storage)
    sched = Scheduler(storage=storage, agent_loop=_RecordingLoop())

    out = run_status(str(cid), svc=svc, scheduler=sched)
    assert "campaign" not in out["scheduler"]


@pytest.mark.unit
def test_status_surfaces_this_campaigns_tick_failure():
    """Dark-engine audit #73: THIS campaign's own last tick failure/count is
    merged into ``scheduler.campaign`` without disturbing the rest of the
    scheduler heartbeat or the run-config/intent fields."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    svc = AgentRunService(storage)
    sched = Scheduler(storage=storage, agent_loop=_RecordingLoop())
    now = datetime(2026, 6, 16, tzinfo=UTC)
    sched._note_campaign_failure(cid, now, RuntimeError("login page timed out"))

    out = run_status(str(cid), svc=svc, scheduler=sched)
    assert out["campaign_id"] == str(cid)  # untouched run-config fields
    campaign_health = out["scheduler"]["campaign"]
    assert campaign_health["failure_count"] == 1
    assert "login page timed out" in campaign_health["last_error"]
    # A different campaign's payload is unaffected.
    other = _campaign(storage)
    out2 = run_status(str(other), svc=svc, scheduler=sched)
    assert "campaign" not in out2["scheduler"]


@pytest.mark.unit
def test_status_handles_missing_scheduler():
    """No scheduler wired (legacy/unit callers) -> ``scheduler`` is None, no crash."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    svc = AgentRunService(storage)
    out = run_status(str(cid), svc=svc, scheduler=None)
    assert out["scheduler"] is None
