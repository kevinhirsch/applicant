"""Regression coverage for performance lens 03 (round 2): ``RunHistoryProvider``
(the curation-tick's run-summary source, ``application/services/run_history.py``)
looped every reviewable application in a campaign and called
``storage.outcomes.list_for_application(app.id)`` once PER application — an N+1
that runs on every scheduled curation tick, across every active campaign.

The fix batches one ``storage.outcomes.list_for_campaign(campaign.id)`` call per
campaign (the repository method already existed — used elsewhere for admin/learning
reads) and groups the rows by ``application_id`` in Python, so the per-application
loop is a dict lookup instead of a storage round-trip.

FAIL-BEFORE: on the pre-fix tree (verified by hand — file-copy the pre-fix
``run_history.py`` back in, rerun, see the call-count assertion fail because
``list_for_application`` was called once per application instead of never, then
restore) this pins the call counts AND that the resulting ``RunSummary`` output is
byte-identical to before (same submitted/not-submitted verdict per application).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.run_history import RunHistoryProvider
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, OutcomeEventId, new_id
from applicant.core.state_machine import ApplicationState


class _CountingOutcomeRepo:
    """Wraps the real in-memory OutcomeRepo, counting each method's call count."""

    def __init__(self, inner):
        self._inner = inner
        self.list_for_application_calls = 0
        self.list_for_campaign_calls = 0

    def list_for_application(self, application_id):
        self.list_for_application_calls += 1
        return self._inner.list_for_application(application_id)

    def list_for_campaign(self, campaign_id, **kw):
        self.list_for_campaign_calls += 1
        return self._inner.list_for_campaign(campaign_id, **kw)

    def add(self, event):
        return self._inner.add(event)


def _wire_campaign_with_apps(storage, n_apps: int) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    for i in range(n_apps):
        aid = ApplicationId(new_id())
        storage.applications.add(
            Application(
                id=aid,
                campaign_id=cid,
                posting_id=JobPostingId(new_id()),
                status=ApplicationState.SUBMITTED_BY_USER,
                job_title=f"Engineer {i}",
                root_url="https://acme.test",
            )
        )
        # Every OTHER application actually converted (submitted outcome event) so
        # the batched grouping is proven to still distinguish per-application state.
        if i % 2 == 0:
            storage.outcomes.add(
                OutcomeEvent(
                    id=OutcomeEventId(new_id()),
                    application_id=aid,
                    type="submitted",
                    source=OutcomeSource.MANUAL,
                )
            )
    storage.commit()
    return cid


@pytest.mark.unit
def test_run_history_batches_outcomes_per_campaign_not_per_application():
    storage = InMemoryStorage()
    _wire_campaign_with_apps(storage, n_apps=5)
    counting = _CountingOutcomeRepo(storage.outcomes)
    storage.outcomes = counting

    summaries = RunHistoryProvider()(storage, datetime.now(UTC))

    assert len(summaries) == 5
    assert counting.list_for_campaign_calls == 1, (
        "must fetch the campaign's outcomes exactly once, not once per application"
    )
    assert counting.list_for_application_calls == 0, (
        "must NOT fall back to the per-application N+1 read"
    )
    # Behavior parity: the submitted/not-submitted split from the grouped outcomes
    # must exactly match what per-application outcome reads would have produced.
    submitted_summaries = [s for s in summaries if s.text.startswith("Submitted")]
    worked_summaries = [s for s in summaries if s.text.startswith("Worked")]
    assert len(submitted_summaries) == 3  # i = 0, 2, 4
    assert len(worked_summaries) == 2  # i = 1, 3
    assert all(s.tool_calls == 5 for s in submitted_summaries)
    assert all(s.tool_calls == 0 for s in worked_summaries)


@pytest.mark.unit
def test_run_history_multi_campaign_batches_once_per_campaign():
    storage = InMemoryStorage()
    cid_a = _wire_campaign_with_apps(storage, n_apps=2)
    cid_b = _wire_campaign_with_apps(storage, n_apps=3)
    counting = _CountingOutcomeRepo(storage.outcomes)
    storage.outcomes = counting

    summaries = RunHistoryProvider()(storage, datetime.now(UTC))

    assert len(summaries) == 5
    assert counting.list_for_campaign_calls == 2, "one batched read per active campaign"
    assert counting.list_for_application_calls == 0
    seen_campaigns = {s.campaign_id for s in summaries}
    assert seen_campaigns == {str(cid_a), str(cid_b)}
