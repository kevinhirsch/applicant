"""Regression coverage for dark-engine audit items #57/#58 (B6).

#57 — ``Application.sandbox_session_url`` (the application's own live
sandbox/takeover session URL) was stored on the entity but never reached any
rendered payload -- ``AdminQueryService.application_history`` (the SAME
read-model item #56 already extended for salary/location) now carries it
through, real value or honest ``None``, never fabricated.

#58 — the pre-fill planner's Plan-as-Data op-sequence (GOTO/FIND/FILL/... --
``core.entities.plan.Plan``) is computed per page when ``PREFILL_USE_PLANNER``
is on, but was never persisted anywhere reviewable. ``PrefillService.
record_plan_history``/``get_plan_history`` add a process-lived, in-memory
ledger (deliberately NOT a new DB table/migration -- this is read-only
observability data), and ``application_history`` surfaces it as ``plan_ops``.

Per this series' standing DoD, both additions were verified, by hand, to go
RED when reverted out of ``admin_query_service.py`` (restoring from a
pre-change backup), then confirmed GREEN again after restoring the change.
"""

from __future__ import annotations

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.admin_query_service import AdminQueryService
from applicant.application.services.prefill_service import (
    _PLAN_HISTORY,
    _PLAN_HISTORY_MAX_PER_APP,
    get_plan_history,
    record_plan_history,
)
from applicant.core.entities.application import Application
from applicant.core.entities.plan import FillOp, GotoOp, Plan, StopOp
from applicant.core.ids import ApplicationId, CampaignId, new_id
from applicant.core.state_machine import ApplicationState


def _storage_with_app(*, sandbox_session_url: str | None = "https://sandbox.example/s/abc123"):
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=None,
            status=ApplicationState.PREFILLING,
            role_name="Senior Engineer",
            sandbox_session_url=sandbox_session_url,
        )
    )
    storage.commit()
    return storage, cid, aid


# --- #57: sandbox_session_url -----------------------------------------------


def test_application_history_surfaces_real_sandbox_session_url():
    storage, cid, aid = _storage_with_app(sandbox_session_url="https://sandbox.example/s/abc123")
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert len(rows) == 1
    assert rows[0]["application_id"] == str(aid)
    assert rows[0]["sandbox_session_url"] == "https://sandbox.example/s/abc123"


def test_application_history_sandbox_session_url_none_when_absent():
    # No live session for this application (e.g. already submitted/archived) --
    # the honest ``None``, never a fabricated link.
    storage, cid, _aid = _storage_with_app(sandbox_session_url=None)
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert rows[0]["sandbox_session_url"] is None


def test_application_history_sandbox_session_url_none_when_blank():
    # A blank string (never explicitly set) also degrades to ``None``, not "".
    storage, cid, _aid = _storage_with_app(sandbox_session_url="")
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert rows[0]["sandbox_session_url"] is None


# --- #58: plan-as-data op history --------------------------------------------


def test_record_and_get_plan_history_round_trips_ops():
    aid = ApplicationId(new_id())
    _PLAN_HISTORY.pop(str(aid), None)
    plan = Plan(ops=(GotoOp(url="https://ats.example/apply"), FillOp(ref="#name", attribute_id="full_name")))
    record_plan_history(aid, "https://ats.example/apply", plan)
    history = get_plan_history(aid)
    assert len(history) == 1
    assert history[0]["url"] == "https://ats.example/apply"
    assert history[0]["ops"] == [
        {"kind": "goto", "url": "https://ats.example/apply"},
        {"kind": "fill", "ref": "#name", "attribute_id": "full_name"},
    ]
    assert "captured_at" in history[0]


def test_get_plan_history_empty_when_planner_never_ran():
    aid = ApplicationId(new_id())
    _PLAN_HISTORY.pop(str(aid), None)
    assert get_plan_history(aid) == []


def test_plan_history_returns_a_copy_not_the_live_ledger():
    aid = ApplicationId(new_id())
    _PLAN_HISTORY.pop(str(aid), None)
    record_plan_history(aid, "https://ats.example/p1", Plan(ops=(StopOp(reason="final_submit"),)))
    history = get_plan_history(aid)
    history.append({"tampered": True})
    assert get_plan_history(aid) == [history[0]]


def test_plan_history_capped_per_application():
    aid = ApplicationId(new_id())
    _PLAN_HISTORY.pop(str(aid), None)
    for i in range(_PLAN_HISTORY_MAX_PER_APP + 3):
        record_plan_history(aid, f"https://ats.example/page{i}", Plan(ops=(GotoOp(url=f"https://ats.example/page{i}"),)))
    history = get_plan_history(aid)
    assert len(history) == _PLAN_HISTORY_MAX_PER_APP
    # oldest entries are dropped first -- the newest page survives.
    assert history[-1]["url"] == f"https://ats.example/page{_PLAN_HISTORY_MAX_PER_APP + 2}"


def test_application_history_surfaces_plan_ops_when_planner_ran():
    storage, cid, aid = _storage_with_app()
    _PLAN_HISTORY.pop(str(aid), None)
    record_plan_history(aid, "https://ats.example/apply", Plan(ops=(GotoOp(url="https://ats.example/apply"),)))
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert rows[0]["plan_ops"]
    assert rows[0]["plan_ops"][0]["ops"] == [{"kind": "goto", "url": "https://ats.example/apply"}]


def test_application_history_plan_ops_empty_when_planner_never_ran():
    storage, cid, aid = _storage_with_app()
    _PLAN_HISTORY.pop(str(aid), None)
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert rows[0]["plan_ops"] == []
