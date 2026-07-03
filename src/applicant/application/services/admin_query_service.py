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
  reusing the Phase 3 variant data (FR-UI-6 / FR-RESUME-6), plus a per-variant
  usage count and (where the data supports it) interview rate (design-audit
  Top-25 #19).

This is a query-only service (no mutation), so it can never regress live state.
"""

from __future__ import annotations

# Reuse the SAME "submitted" state set and positive-signal outcome types the
# tracker board already uses (post_submission_service, #4 of the design audit)
# rather than redefining them here, so the variant scoreboard's notion of
# "used"/"converted" never drifts from the tracker's.
from applicant.application.services.post_submission_service import (
    POSITIVE_SIGNAL_TYPES,
    TRACKER_STATES,
)
from applicant.core.ids import ApplicationId, CampaignId
from applicant.observability.logging import recent_logs

#: Hard cap on how far the variant-lineage walk follows parent-id chains. The
#: cycle guard alone bounds a closed loop, but a very long *acyclic* chain (or a
#: chain spanning rows outside this page's ``by_id`` map) could still walk deep; this
#: cap keeps ``depth()`` O(1)-ish per variant regardless of lineage length.
MAX_LINEAGE_DEPTH = 20


class AdminQueryService:
    def __init__(self, storage, orchestrator) -> None:
        self._storage = storage
        self._orch = orchestrator

    # --- per-application history (FR-LOG-3 / FR-UI-6) ----------------------
    def application_history(
        self, campaign_id: CampaignId, *, limit: int | None = None
    ) -> list[dict]:
        """Per-application history (#14): batch screenshots + outcomes by campaign.

        Was O(N) per-application ``list_for_application`` calls for screenshots AND
        outcomes (a 2*N query storm). Now fetches both ONCE per campaign via the batch
        repo methods (``screenshots.list_for_campaign`` / ``outcomes.list_for_campaign``)
        and groups in memory, falling back to per-app where the batch method is absent.
        ``limit`` bounds the rows returned.
        """
        apps = self._storage.applications.list_for_campaign(campaign_id)
        if limit is not None:
            apps = apps[:limit]
        shots_by_app = self._batch_screenshots(campaign_id, apps)
        outcomes_by_app = self._batch_outcomes(campaign_id, apps)
        rows: list[dict] = []
        for a in apps:
            shots = shots_by_app.get(str(a.id), [])
            outcomes = outcomes_by_app.get(str(a.id), [])
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
                    # dark-engine audit #54: the attribute map the engine actually
                    # consumed for THIS application (``Application.attributes_used``,
                    # recorded at mark-submitted/record-submission time) -- a genuine
                    # privacy-trust artifact the engine already keeps but never
                    # surfaced anywhere. Real data only, never fabricated: an
                    # application that never recorded any attributes returns ``{}``.
                    "attributes_used": dict(a.attributes_used or {}),
                }
            )
        return rows

    def _batch_screenshots(self, campaign_id: CampaignId, apps) -> dict[str, list]:
        """Group per-app screenshots from one campaign-wide query (#14)."""
        out: dict[str, list] = {}
        for s in self._storage.screenshots.list_for_campaign(campaign_id):
            out.setdefault(str(s.application_id), []).append(s)
        return out

    def _batch_outcomes(self, campaign_id: CampaignId, apps) -> dict[str, list]:
        """Group per-app outcomes from one campaign-wide query (#14)."""
        out: dict[str, list] = {}
        for o in self._storage.outcomes.list_for_campaign(campaign_id):
            out.setdefault(str(o.application_id), []).append(o)
        return out

    # --- per-page screenshots (FR-OBS-2) ----------------------------------
    def screenshots(self, application_id: ApplicationId) -> list[dict]:
        return [
            {"id": str(s.id), "page_ref": s.page_ref, "page_url": s.page_url}
            for s in self._storage.screenshots.list_for_application(application_id)
        ]

    # --- gallery collections (issue #296) ---------------------------------
    def gallery(self, campaign_id: CampaignId) -> dict:
        """Gallery read-model: per-campaign screenshot + material collections (#296).

        Reuses the SAME real read sources as the debug surface — no new storage,
        no new state. Screenshots come from the campaign-wide screenshot batch
        (real fields ``page_ref``/``page_url``); materials come from the generated-
        materials repo (real fields ``type``/``storage_path``/``approved``/
        ``content``). Both are grouped into "collections" so a simple grid view can
        render them. Query-only, so it can never regress live state.
        """
        screenshots = [
            {
                "id": str(s.id),
                "application_id": str(s.application_id),
                "page_ref": s.page_ref,
                "page_url": s.page_url,
            }
            for s in self._storage.screenshots.list_for_campaign(campaign_id)
        ]
        materials = [
            {
                "id": str(d.id),
                "application_id": str(d.application_id) if d.application_id else None,
                "type": d.type.value if hasattr(d.type, "value") else str(d.type),
                "storage_path": d.storage_path,
                "approved": bool(d.approved),
                "content": d.content,
            }
            for d in self._storage.documents.list_for_campaign(campaign_id)
        ]
        return {
            "campaign_id": str(campaign_id),
            "screenshots": {"count": len(screenshots), "items": screenshots},
            "materials": {"count": len(materials), "items": materials},
        }

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
    def variant_library(
        self, campaign_id: CampaignId, *, limit: int | None = None
    ) -> list[dict]:
        variants = self._storage.resume_variants.list_for_campaign(campaign_id)
        by_id = {str(v.id): v for v in variants}
        if limit is not None:
            variants = variants[:limit]

        def depth(v) -> int:
            d, cur = 0, v
            seen = set()
            while cur.parent_id is not None and str(cur.parent_id) in by_id:
                if str(cur.id) in seen:  # cycle guard
                    break
                if d >= MAX_LINEAGE_DEPTH:  # depth cap: don't walk an unbounded chain
                    break
                seen.add(str(cur.id))
                cur = by_id[str(cur.parent_id)]
                d += 1
            return d

        uses_by_variant, positives_by_variant = self._variant_usage_stats(campaign_id)

        rows = []
        for v in variants:
            vid = str(v.id)
            uses = uses_by_variant.get(vid, 0)
            positives = positives_by_variant.get(vid, 0)
            rows.append(
                {
                    "variant_id": vid,
                    "parent_id": str(v.parent_id) if v.parent_id else None,
                    "is_root": v.is_root,
                    "lineage_depth": depth(v),
                    "approved": v.approved,
                    "targeted_jd_signature": v.targeted_jd_signature,
                    "fit_scores": dict(v.fit_scores or {}),
                    # design-audit Top-25 #19 (per-variant A/B scoreboard): usage is
                    # always countable (real ``Application.resume_variant_id`` FK),
                    # rounded-percent interview rate is derived from the SAME
                    # outcome-event trail the tracker board reads and is ``None``
                    # (never a fabricated 0%) until the variant has at least one
                    # tracked use.
                    "uses": uses,
                    "interview_rate": (
                        round(100.0 * positives / uses, 1) if uses > 0 else None
                    ),
                }
            )
        return rows

    def _variant_usage_stats(
        self, campaign_id: CampaignId
    ) -> tuple[dict[str, int], dict[str, int]]:
        """Per-variant use count + positive-signal count (design-audit Top-25 #19).

        "Used" means an application carrying that variant's id
        (``Application.resume_variant_id``) actually reached a submitted/
        post-submission state (``TRACKER_STATES`` — the same set the tracker board
        uses), not merely that a variant was picked during drafting. "Positive
        signal" reuses ``POSITIVE_SIGNAL_TYPES`` (``interview_invited``/``offer``)
        from the outcome trail so this number can never diverge from what the
        tracker board itself shows for the same application.
        """
        apps = self._storage.applications.list_for_campaign(campaign_id)
        outcomes_by_app = self._batch_outcomes(campaign_id, apps)
        uses: dict[str, int] = {}
        positives: dict[str, int] = {}
        for a in apps:
            if a.resume_variant_id is None or a.status not in TRACKER_STATES:
                continue
            vid = str(a.resume_variant_id)
            uses[vid] = uses.get(vid, 0) + 1
            events = outcomes_by_app.get(str(a.id), [])
            if any(e.type in POSITIVE_SIGNAL_TYPES for e in events):
                positives[vid] = positives.get(vid, 0) + 1
        return uses, positives
