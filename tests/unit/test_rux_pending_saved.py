"""RUX-2: PendingActionsService save-for-later bucket + reminder nudge.

The three-way review decision's "Save-for-later" needs a DISTINCT "Saved / To
submit" bucket that is OUT of the active queue, plus a reminder nudge. This is the
additive service change under review.py's RUX-2 endpoint: ``save_for_later`` (a
kind + materialize + snooze, where the snooze wake-time IS the nudge) and
``list_saved`` (the bucket read). These are TDD-first: they fail until the methods
exist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.pending_actions_service import (
    KIND_SAVED_FOR_LATER,
    PendingActionsService,
)
from applicant.core.ids import ApplicationId, CampaignId, new_id


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def svc(storage) -> PendingActionsService:
    return PendingActionsService(storage)


@pytest.mark.unit
def test_save_for_later_materializes_a_saved_item_out_of_the_active_queue(svc):
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())

    action = svc.save_for_later(
        cid, title="Staff Engineer @ Acme", application_id=aid, posting_id="p1"
    )

    assert action.kind == KIND_SAVED_FOR_LATER
    # Reminder nudge reuses the snooze wake-time -> snoozed, so it is HIDDEN from the
    # active pending queue until it comes due.
    assert (action.payload or {}).get("snoozed_until")
    assert svc.list_pending(cid) == []
    # ...but it lives in the distinct "Saved / To submit" bucket.
    saved = svc.list_saved(cid)
    assert [str(a.id) for a in saved] == [str(action.id)]
    assert saved[0].payload.get("posting_id") == "p1"


@pytest.mark.unit
def test_reminder_nudge_reuses_snooze_wake_time(svc):
    cid = CampaignId(new_id())
    wake = datetime.now(UTC) + timedelta(days=3)
    action = svc.save_for_later(cid, title="Later role", remind_at=wake)
    assert (action.payload or {}).get("snoozed_until") == wake.isoformat()


@pytest.mark.unit
def test_save_for_later_is_deduped_per_application(svc):
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    first = svc.save_for_later(cid, title="Role", application_id=aid)
    second = svc.save_for_later(cid, title="Role (re-saved)", application_id=aid)
    # Re-saving the same application refreshes rather than piling up a duplicate.
    assert str(first.id) == str(second.id)
    assert len(svc.list_saved(cid)) == 1


@pytest.mark.unit
def test_list_saved_is_campaign_scoped(svc):
    cid_a = CampaignId(new_id())
    cid_b = CampaignId(new_id())
    svc.save_for_later(cid_a, title="A role", application_id=ApplicationId(new_id()))
    assert svc.list_saved(cid_b) == []
