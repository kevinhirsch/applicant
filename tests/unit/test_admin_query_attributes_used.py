"""Regression coverage for dark-engine audit item #54: "which of your details
were used" on the Tracker.

``Application.attributes_used`` (``src/applicant/core/entities/application.py``)
already carries the exact attribute map the engine consumed submitting an
application, but ``AdminQueryService.application_history`` -- the read-model
that backs both the admin Debug modal's drill-down (``GET /api/admin/history/
{campaign_id}``) and, via the owner-scoped Tracker proxy, the front-door
"View details" disclosure -- never included it in the per-application row.
This is a genuine privacy-trust artifact the engine already keeps that no
surface showed.

This only pins the engine-side read-model change: ``application_history``
now includes a real ``attributes_used`` dict per row, sourced from the
persisted ``Application`` entity, never fabricated. The front-door rendering
of this field is covered separately in
``workspace/tests/test_applicant_tracker_attributes_used.py``.

Per this series' standing DoD, this test was verified, by hand, to go RED
when the ``attributes_used`` key is reverted out of the row dict in
``admin_query_service.py``, then confirmed GREEN again after restoring.
"""

from __future__ import annotations

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.admin_query_service import AdminQueryService
from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _storage_with_app(attributes_used: dict | None = None):
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.PREFILLING,
            role_name="Senior Engineer",
            work_mode="remote",
            attributes_used=attributes_used or {},
        )
    )
    storage.commit()
    return storage, cid, aid


def test_application_history_surfaces_real_attributes_used():
    storage, cid, aid = _storage_with_app({"First Name": "Kevin", "email": "k@example.com"})
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert len(rows) == 1
    assert rows[0]["application_id"] == str(aid)
    assert rows[0]["attributes_used"] == {"First Name": "Kevin", "email": "k@example.com"}


def test_application_history_attributes_used_is_never_fabricated_when_empty():
    # An application that never recorded any consumed attributes must report
    # a real, honest empty dict -- never a fabricated/omitted field.
    storage, cid, aid = _storage_with_app(None)
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert rows[0]["attributes_used"] == {}


def test_application_history_attributes_used_is_a_copy_not_a_live_reference():
    # The row dict must not alias the entity's own mutable dict -- mutating
    # the returned row must never leak back into storage.
    storage, cid, aid = _storage_with_app({"phone": "555-0100"})
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    rows[0]["attributes_used"]["phone"] = "TAMPERED"
    fresh_rows = svc.application_history(cid)
    assert fresh_rows[0]["attributes_used"] == {"phone": "555-0100"}
