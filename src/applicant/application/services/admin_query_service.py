"""AdminQueryService — backs the debug / observability surface (FR-OBS-2, FR-LOG-3).

Real read-models for the debug surface, composed from storage + the orchestration
port + the logging ring buffer:

* ``application_history`` — every application with its logged detail, decisions,
  outcomes, and screenshot refs (FR-LOG-3 / FR-UI-6);
* ``screenshots`` — per-page screenshots captured during pre-fill (FR-OBS-2);
* ``workflow_state`` — durable-workflow (DBOS/shim) state: completed idempotent
  steps and whether the workflow is pending recovery (FR-OBS-2 / FR-DUR-1);
* ``logs`` — recent, already-redacted structured log entries (FR-LOG-3);
* ``variant_library`` — resume variants with lineage / scores / approval state,
  reusing the Phase 3 variant data (FR-UI-6 / FR-RESUME-6).

This is a query-only service (no mutation), so it can never regress live state.
"""

from __future__ import annotations

from applicant.core.ids import ApplicationId, CampaignId
from applicant.observability.logging import recent_logs


class AdminQueryService:
    def __init__(self, storage, orchestrator) -> None:
        self._storage = storage
        self._orch = orchestrator

    # --- per-application history (FR-LOG-3 / FR-UI-6) ----------------------
    def application_history(self, campaign_id: CampaignId) -> list[dict]:
        rows: list[dict] = []
        for a in self._storage.applications.list_for_campaign(campaign_id):
            shots = self._storage.screenshots.list_for_application(a.id)
            outcomes = self._storage.outcomes.list_for_application(a.id)
            rows.append(
                {
                    "application_id": str(a.id),
                    "status": a.status.value,
                    "role_name": a.role_name,
                    "job_title": a.job_title,
                    "work_mode": a.work_mode,
                    "root_url": a.root_url,
                    "resume_variant_id": str(a.resume_variant_id) if a.resume_variant_id else None,
                    "screenshot_count": len(shots),
                    "outcomes": [{"type": o.type, "source": o.source.value} for o in outcomes],
                }
            )
        return rows

    # --- per-page screenshots (FR-OBS-2) ----------------------------------
    def screenshots(self, application_id: ApplicationId) -> list[dict]:
        return [
            {"id": str(s.id), "page_ref": s.page_ref, "page_url": s.page_url}
            for s in self._storage.screenshots.list_for_application(application_id)
        ]

    # --- detection-event history (FR-OBS-2 / FR-PREFILL-6) ----------------
    def detection_events(self, campaign_id: CampaignId) -> list[dict]:
        """Persisted detection signals for a campaign's debug history surface."""
        repo = getattr(self._storage, "detection_events", None)
        if repo is None:
            return []
        return [
            {
                "id": str(e.id),
                "application_id": str(e.application_id),
                "signal_type": e.signal_type,
                "detail": e.detail,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in repo.list_for_campaign(campaign_id)
        ]

    # --- durable-workflow state (FR-OBS-2 / FR-DUR-1) ---------------------
    def workflow_state(self, application_id: ApplicationId) -> dict:
        workflow_id = f"application:{application_id}"
        orch = self._orch
        completed = (
            orch.completed_steps(workflow_id) if hasattr(orch, "completed_steps") else []
        )
        try:
            pending_list = orch.recover_pending() if hasattr(orch, "recover_pending") else []
        except NotImplementedError:  # pragma: no cover - backend not ready
            pending_list = []
        return {
            "application_id": str(application_id),
            "workflow_id": workflow_id,
            "completed_steps": list(completed),
            "pending_recovery": workflow_id in pending_list,
            "pending_workflows": list(pending_list),
        }

    # --- recent structured logs (FR-LOG-3) --------------------------------
    def logs(self, limit: int = 100) -> list[dict]:
        return recent_logs(limit)

    # --- variant library (FR-UI-6 / FR-RESUME-6) --------------------------
    def variant_library(self, campaign_id: CampaignId) -> list[dict]:
        variants = self._storage.resume_variants.list_for_campaign(campaign_id)
        by_id = {str(v.id): v for v in variants}

        def depth(v) -> int:
            d, cur = 0, v
            seen = set()
            while cur.parent_id is not None and str(cur.parent_id) in by_id:
                if str(cur.id) in seen:  # cycle guard
                    break
                seen.add(str(cur.id))
                cur = by_id[str(cur.parent_id)]
                d += 1
            return d

        return [
            {
                "variant_id": str(v.id),
                "parent_id": str(v.parent_id) if v.parent_id else None,
                "is_root": v.is_root,
                "lineage_depth": depth(v),
                "approved": v.approved,
                "targeted_jd_signature": v.targeted_jd_signature,
                "fit_scores": dict(v.fit_scores or {}),
            }
            for v in variants
        ]
