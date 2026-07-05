"""Regression coverage for performance lens 03 (round 2): ``CompareService``
(``application/services/compare_service.py``), when a ``campaign_id`` scope is
given, fetched the WHOLE campaign's applications/postings via ``list_for_campaign``
just to build an ``allowed`` id set, then re-fetched each requested id individually
via ``.get()`` — the same rows, twice, on every comparison.

The fix builds an ``{id: entity}`` dict from the single ``list_for_campaign`` call
and looks up locally; ``.get()`` is only used when no ``campaign_id`` scope is given
(the original unscoped behavior, unchanged).

FAIL-BEFORE: on the pre-fix tree (verified by hand — file-copy the pre-fix
``compare_service.py`` back in, rerun, see the ``.get()`` call-count assertion fail,
then restore) this pins that a scoped comparison never calls ``.get()``, and that
the comparison RESULT is unchanged (same entities, same dimensions, same scoping
behavior for an out-of-campaign id).
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.compare_service import CompareService
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId
from applicant.core.state_machine import ApplicationState


class _CountingGetRepo:
    """Wraps a real in-memory repo, counting ``.get()`` calls only."""

    def __init__(self, inner):
        self._inner = inner
        self.get_calls = 0

    def get(self, entity_id):
        self.get_calls += 1
        return self._inner.get(entity_id)

    def list_for_campaign(self, campaign_id):
        return self._inner.list_for_campaign(campaign_id)

    def add(self, entity):
        return self._inner.add(entity)


def _make_app(cid, aid, status=ApplicationState.APPROVED) -> Application:
    return Application(
        id=ApplicationId(aid), campaign_id=CampaignId(cid),
        posting_id=JobPostingId(f"posting-{aid}"), status=status,
    )


def _make_posting(cid, pid, title="Engineer") -> JobPosting:
    return JobPosting(
        id=JobPostingId(pid), campaign_id=CampaignId(cid), title=title,
        company="Acme", source_url="https://example.com/job",
    )


@pytest.mark.unit
def test_compare_applications_scoped_never_calls_get():
    storage = InMemoryStorage()
    storage.applications.add(_make_app("c-1", "a-1"))
    storage.applications.add(_make_app("c-1", "a-2"))
    storage.applications.add(_make_app("c-other", "a-3"))
    counting = _CountingGetRepo(storage.applications)
    storage.applications = counting
    svc = CompareService(storage)

    result = svc.compare_applications(["a-1", "a-2", "a-3"], campaign_id="c-1")

    assert counting.get_calls == 0, "a campaign-scoped compare must not call .get() at all"
    # Behavior parity: same scoping result as before -- only the 2 in-campaign apps.
    assert set(result.entity_ids) == {"a-1", "a-2"}
    assert len(result.dimensions) >= 1


@pytest.mark.unit
def test_compare_applications_unscoped_still_uses_get():
    """No campaign_id -> no batch list is possible; must still work via .get()."""
    storage = InMemoryStorage()
    storage.applications.add(_make_app("c-1", "a-1"))
    storage.applications.add(_make_app("c-2", "a-2"))
    svc = CompareService(storage)

    result = svc.compare_applications(["a-1", "a-2"])

    assert set(result.entity_ids) == {"a-1", "a-2"}


@pytest.mark.unit
def test_compare_postings_scoped_never_calls_get():
    storage = InMemoryStorage()
    storage.postings.add(_make_posting("c-1", "p-1"))
    storage.postings.add(_make_posting("c-1", "p-2"))
    storage.postings.add(_make_posting("c-other", "p-3"))
    counting = _CountingGetRepo(storage.postings)
    storage.postings = counting
    svc = CompareService(storage)

    result = svc.compare_postings(["p-1", "p-2", "p-3"], campaign_id="c-1")

    assert counting.get_calls == 0
    assert set(result.entity_ids) == {"p-1", "p-2"}
    assert len(result.dimensions) >= 1
