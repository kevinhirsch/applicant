"""Gallery router — screenshots + generated materials as gallery collections (#296).

A read-only, campaign-scoped view that surfaces what the engine already captured
during a campaign as browsable collections:

* the per-page **screenshots** archived during pre-fill (real fields
  ``page_ref`` / ``page_url``), and
* the **generated materials** drafted for the campaign (real fields ``type`` /
  ``storage_path`` / ``approved`` / ``content``).

Both come straight from :class:`AdminQueryService` (the same real read-models the
debug surface uses) — this router adds NO new engine logic or state. Gated behind
the LLM-settings gate (FR-UI-5), mirroring its admin/pending-actions peers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from applicant.app.deps import get_admin_query_service, require_llm_configured

router = APIRouter(
    prefix="/api/gallery",
    tags=["gallery"],
    dependencies=[Depends(require_llm_configured)],
)


@router.get("")
def index() -> dict:
    return {"surface": "gallery", "status": "live"}


@router.get("/{campaign_id}")
def gallery(campaign_id: str, admin_query=Depends(get_admin_query_service)) -> dict:
    """Screenshot + material collections for a campaign (#296).

    Returns ``{campaign_id, screenshots: {count, items}, materials: {count, items}}``
    so a simple grid/collection view can render both. Read-only.
    """
    return admin_query.gallery(campaign_id)  # type: ignore[arg-type]
