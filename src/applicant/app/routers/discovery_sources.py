"""Discovery-source registry router (FR-DISC-2/5). Gated behind the LLM gate (FR-UI-5).

Lists the per-campaign user-selectable sources with their enable toggle + learned
yield stats, and lets the user toggle a source on/off (persisted to
``discovery_sources``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import (
    get_container,
    get_discovery_service,
    require_automated_work,
    require_llm_configured,
)

router = APIRouter(
    prefix="/api/discovery-sources",
    tags=["discovery"],
    dependencies=[Depends(require_llm_configured), Depends(require_automated_work)],
)

#: The offline sample source (``adapters/discovery/factory.py``'s ``SampleSource``)
#: is ALWAYS synthetic, clearly-marked ``example.test`` rows — it stays registered
#: regardless of ``DISCOVERY_LIVE`` so the offline lane always has a yielding source.
#: Every other registered key (the JobSpy boards, SearXNG, RSS feeds) is backed by a
#: real network client only when ``DISCOVERY_LIVE`` is set (dark-engine audit item 65:
#: the offline fakes share the exact same registry shape as the live clients, so
#: without this flag a user cannot tell sample rows from real discovery results).
_SAMPLE_SOURCE_KEY = "sample"


class ToggleSourceIn(BaseModel):
    enabled: bool


def _is_live(source_key: str, *, discovery_live: bool) -> bool:
    """Whether ``source_key`` is currently backed by a real, live client."""
    return discovery_live and source_key != _SAMPLE_SOURCE_KEY


@router.get("/{campaign_id}")
def list_sources(
    campaign_id: str,
    svc=Depends(get_discovery_service),
    container: Container = Depends(get_container),
) -> dict:
    svc.sync_registry(campaign_id)  # type: ignore[arg-type]
    sources = svc.list_sources(campaign_id)  # type: ignore[arg-type]
    discovery_live = bool(getattr(container.settings, "discovery_live", False))
    return {
        "campaign_id": campaign_id,
        "items": [
            {
                "source_key": s.source_key,
                "enabled": s.enabled,
                "yield_stats": s.yield_stats,
                "live": _is_live(s.source_key, discovery_live=discovery_live),
            }
            for s in sources
        ],
    }


@router.put("/{campaign_id}/{source_key}")
def toggle_source(
    campaign_id: str, source_key: str, body: ToggleSourceIn, svc=Depends(get_discovery_service)
) -> dict:
    svc.set_source_enabled(campaign_id, source_key, body.enabled)  # type: ignore[arg-type]
    return {"campaign_id": campaign_id, "source_key": source_key, "enabled": body.enabled}
