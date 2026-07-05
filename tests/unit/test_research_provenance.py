"""Regression coverage for dark-engine audit item #76 (B7): company-research
provenance is lost per application.

The agent loop auto-escalates to the capped deep-research tool on a genuine
company/role knowledge gap and marks ``summary["research_used"]`` on the
checkpointed ``material`` pipeline step -- but that flag (and which report
informed the writing) lived ONLY in the orchestrator's checkpoint, never
reaching any rendered payload. ``CheckpointShimOrchestrator.step_result`` adds
read-only step introspection; ``AdminQueryService.research_provenance`` (and
the ``research_provenance`` field it now adds to ``application_history``) reads
it back for a redline-review-card badge + excerpt.

Verified, by hand, to go RED when ``step_result``/``research_provenance`` are
reverted out of ``checkpoint_shim.py``/``admin_query_service.py`` (restoring
from a pre-change backup), then GREEN again after restoring the change.
"""

from __future__ import annotations

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.admin_query_service import AdminQueryService
from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, new_id
from applicant.core.state_machine import ApplicationState


def _storage_with_app() -> tuple[InMemoryStorage, CampaignId, ApplicationId]:
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=None,
            status=ApplicationState.MATERIAL_REVIEW,
            role_name="Senior Engineer",
        )
    )
    storage.commit()
    return storage, cid, aid


def _seed_material_checkpoint(orch: CheckpointShimOrchestrator, aid: ApplicationId, result: dict) -> None:
    """Directly checkpoint a ``material`` step result, the way the real
    ``application_pipeline.run_pipeline`` does via ``orchestrator.run_step`` --
    without running a whole pipeline/agent-loop tick just to seed one step."""
    workflow_id = f"application:{aid}"
    orch.run_step(workflow_id, "material", lambda: result)


# --- CheckpointShimOrchestrator.step_result ---------------------------------


def test_step_result_returns_none_when_never_checkpointed(tmp_path):
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    assert orch.step_result("application:never-run", "material") is None


def test_step_result_reads_back_a_checkpointed_step_without_rerunning(tmp_path):
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    calls = {"n": 0}

    def _fn():
        calls["n"] += 1
        return {"research_used": True}

    orch.run_step("application:x", "material", _fn)
    assert calls["n"] == 1
    result = orch.step_result("application:x", "material")
    assert result == {"research_used": True}
    # Introspection must never re-run the step body.
    assert calls["n"] == 1


# --- AdminQueryService.research_provenance ----------------------------------


def test_research_provenance_none_when_research_never_used(tmp_path):
    storage, _cid, aid = _storage_with_app()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    _seed_material_checkpoint(orch, aid, {"variant_id": "v1", "variant_generated": True})
    svc = AdminQueryService(storage, orch)
    assert svc.research_provenance(aid) is None


def test_research_provenance_none_when_checkpoint_absent():
    # A submitted/archived application whose workflow checkpoint was already
    # cleared at teardown (DUR-2) -- the common case for a post-submission row.
    storage, _cid, aid = _storage_with_app()
    orch = CheckpointShimOrchestrator(str(new_id()))
    svc = AdminQueryService(storage, orch)
    assert svc.research_provenance(aid) is None


def test_research_provenance_surfaces_real_detail(tmp_path):
    storage, _cid, aid = _storage_with_app()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    provenance = {
        "company": "Acme Corp",
        "query": "What should a job applicant know about Acme Corp?",
        "summary_excerpt": "Acme Corp is a logistics company...",
        "cached": False,
        "sources": [{"title": "Acme Corp — About", "url": "https://acme.example/about"}],
    }
    _seed_material_checkpoint(
        orch, aid, {"research_used": True, "research_provenance": provenance}
    )
    svc = AdminQueryService(storage, orch)
    result = svc.research_provenance(aid)
    assert result == provenance


def test_research_provenance_falls_back_to_used_flag_when_no_detail_dict(tmp_path):
    storage, _cid, aid = _storage_with_app()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    _seed_material_checkpoint(orch, aid, {"research_used": True})
    svc = AdminQueryService(storage, orch)
    assert svc.research_provenance(aid) == {"used": True}


def test_research_provenance_degrades_when_orchestrator_lacks_step_result():
    # e.g. the DBOS-backed orchestrator, which doesn't implement step
    # introspection -- must degrade to None, never raise.
    class _NoIntrospectionOrchestrator:
        pass

    storage, _cid, aid = _storage_with_app()
    svc = AdminQueryService(storage, _NoIntrospectionOrchestrator())
    assert svc.research_provenance(aid) is None


def test_application_history_carries_the_research_provenance_field(tmp_path):
    storage, cid, aid = _storage_with_app()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    provenance = {"company": "Acme Corp", "summary_excerpt": "...", "sources": []}
    _seed_material_checkpoint(
        orch, aid, {"research_used": True, "research_provenance": provenance}
    )
    svc = AdminQueryService(storage, orch)
    rows = svc.application_history(cid)
    assert len(rows) == 1
    assert rows[0]["research_provenance"] == provenance


def test_application_history_research_provenance_none_when_absent(tmp_path):
    storage, cid, _aid = _storage_with_app()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    svc = AdminQueryService(storage, orch)
    rows = svc.application_history(cid)
    assert rows[0]["research_provenance"] is None
