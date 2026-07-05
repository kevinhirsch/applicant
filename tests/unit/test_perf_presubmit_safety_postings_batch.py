"""Regression coverage for performance lens 03 (round 2):
``check_duplicate_application`` and ``check_per_company_volume_cap``
(``application/services/presubmit_safety.py``, #367/#369) each looped every
application in the campaign and called ``storage.postings.get(app.posting_id)``
once PER application — an N+1 that runs before EVERY submission attempt (both
checks gate ``AgentLoop._process_approvals``).

The fix batches one ``storage.postings.list_for_campaign(campaign_id)`` call per
check and looks the posting up locally by id.

FAIL-BEFORE: on the pre-fix tree (verified by hand — file-copy the pre-fix
``presubmit_safety.py`` back in, rerun, see the ``.get()`` call-count assertions
fail, then restore) this pins the batch fetch AND that both checks' block/no-block
verdicts are unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.presubmit_safety import (
    PresubmitBlock,
    check_duplicate_application,
    check_per_company_volume_cap,
)
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


class _CountingPostingRepo:
    def __init__(self, inner):
        self._inner = inner
        self.get_calls = 0
        self.list_for_campaign_calls = 0

    def get(self, posting_id):
        self.get_calls += 1
        return self._inner.get(posting_id)

    def list_for_campaign(self, campaign_id):
        self.list_for_campaign_calls += 1
        return self._inner.list_for_campaign(campaign_id)

    def add(self, posting):
        return self._inner.add(posting)


def _wire(
    storage, cid, *, n_apps: int, company="Acme Corp", title="Senior Backend Engineer",
    created_at=None,
):
    created_at = created_at or (datetime.now(UTC) - timedelta(days=1))
    for i in range(n_apps):
        pid = JobPostingId(new_id())
        storage.postings.add(
            JobPosting(
                id=pid, campaign_id=cid, title=title, company=company,
                source_url=f"https://acme.test/job/{i}",
            )
        )
        storage.applications.add(
            Application(
                id=ApplicationId(new_id()), campaign_id=cid, posting_id=pid,
                status=ApplicationState.SUBMITTED_BY_USER,
                created_at=created_at,
            )
        )
    storage.commit()


@pytest.mark.unit
def test_check_duplicate_application_batches_postings_not_per_app():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    _wire(storage, cid, n_apps=4)
    counting = _CountingPostingRepo(storage.postings)
    storage.postings = counting

    new_posting = JobPosting(
        id=JobPostingId(new_id()), campaign_id=cid, title="Senior Backend Engineer",
        company="Acme Corp", source_url="https://acme.test/new",
    )

    with pytest.raises(PresubmitBlock) as exc_info:
        check_duplicate_application(cid, new_posting, storage)

    assert exc_info.value.check == "duplicate_cooldown"
    assert counting.get_calls == 0, "must not call postings.get() per application"
    assert counting.list_for_campaign_calls == 1


@pytest.mark.unit
def test_check_per_company_volume_cap_batches_postings_not_per_app():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    _wire(storage, cid, n_apps=3, created_at=datetime.now(UTC))
    counting = _CountingPostingRepo(storage.postings)
    storage.postings = counting

    new_posting = JobPosting(
        id=JobPostingId(new_id()), campaign_id=cid, title="Another Role",
        company="Acme Corp", source_url="https://acme.test/newer",
    )

    with pytest.raises(PresubmitBlock) as exc_info:
        check_per_company_volume_cap(cid, new_posting, storage, max_per_day=3)

    assert exc_info.value.check == "per_company_volume"
    assert counting.get_calls == 0, "must not call postings.get() per application"
    assert counting.list_for_campaign_calls == 1


@pytest.mark.unit
def test_check_per_company_volume_cap_allows_under_the_cap():
    """Behavior parity: below the cap, no block (batched fetch changes nothing)."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    _wire(storage, cid, n_apps=1, company="Acme Corp")
    new_posting = JobPosting(
        id=JobPostingId(new_id()), campaign_id=cid, title="Another Role",
        company="Acme Corp", source_url="https://acme.test/newer",
    )
    check_per_company_volume_cap(cid, new_posting, storage, max_per_day=3)  # must not raise
