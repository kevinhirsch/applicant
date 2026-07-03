"""Regression coverage for dark-engine audit item #56: posting metadata
(salary/location/work mode) inconsistently surfaced.

``salary``/``location``/``work_mode``/``source_key`` are captured per posting
(``JobPosting`` -- ``src/applicant/core/entities/job_posting.py``), but before
this change ``AdminQueryService.application_history`` -- the read-model that
backs both the admin Debug modal's drill-down (``GET /api/admin/history/
{campaign_id}``) and, via the owner-scoped Tracker proxy, the front-door
"View details" disclosure -- only ever carried ``Application.work_mode``
(a denormalized copy on the application itself) through to that surface.
Salary and location never reached it at all, even though they are recorded on
the very posting the application traces back to via ``Application.posting_id``.

This only pins the engine-side read-model change: ``application_history`` now
looks up each row's originating ``JobPosting`` (batched per campaign, same
shape as the existing screenshot/outcome batching) and includes real
``salary``/``location`` fields, sourced from the persisted ``JobPosting``
entity, never fabricated. The front-door rendering of these fields is covered
separately in ``workspace/tests/test_applicant_tracker_posting_metadata.py``.

Per this series' standing DoD, this test was verified, by hand, to go RED
when the ``salary``/``location`` keys are reverted out of the row dict in
``admin_query_service.py`` (restoring the file from a pre-change backup), then
confirmed GREEN again after restoring the change.
"""

from __future__ import annotations

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.admin_query_service import AdminQueryService
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _storage_with_app_and_posting(
    *, salary: str | None = "$150k-$180k", location: str | None = "Remote (US)"
):
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    pid = JobPostingId(new_id())
    aid = ApplicationId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title="Senior Engineer",
            company="Acme Corp",
            source_url="https://example.com/jobs/1",
            location=location,
            work_mode="remote",
            salary=salary,
        )
    )
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=pid,
            status=ApplicationState.PREFILLING,
            role_name="Senior Engineer",
            work_mode="remote",
        )
    )
    storage.commit()
    return storage, cid, aid


def test_application_history_surfaces_real_salary_and_location():
    storage, cid, aid = _storage_with_app_and_posting(
        salary="$150k-$180k", location="Remote (US)"
    )
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert len(rows) == 1
    assert rows[0]["application_id"] == str(aid)
    assert rows[0]["salary"] == "$150k-$180k"
    assert rows[0]["location"] == "Remote (US)"


def test_application_history_salary_location_never_fabricated_when_absent():
    # A posting that never recorded salary/location must report the honest
    # ``None`` -- never a fabricated placeholder value.
    storage, cid, aid = _storage_with_app_and_posting(salary=None, location=None)
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert rows[0]["salary"] is None
    assert rows[0]["location"] is None


def test_application_history_salary_location_none_when_posting_missing():
    # Defensive: an application whose posting_id doesn't resolve to a stored
    # posting (should not happen in practice) must degrade to ``None``, never
    # raise and never fabricate.
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.PREFILLING,
            role_name="Ghost Posting Role",
        )
    )
    storage.commit()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert rows[0]["salary"] is None
    assert rows[0]["location"] is None


def test_application_history_still_includes_existing_work_mode_field():
    # This change must not regress the pre-existing work_mode field already
    # surfaced by dark-engine audit #25.
    storage, cid, aid = _storage_with_app_and_posting()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert rows[0]["work_mode"] == "remote"
