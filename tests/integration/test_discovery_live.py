"""Live discovery integration tests (FR-DISC-2/4) — network-gated, skipped by default.

These hit the REAL python-jobspy boards / a real SearXNG instance, so they are marked
``integration`` and skipped unless explicitly enabled. The default test lane stays
hermetic (offline fake clients in the contract tests).

Enable with:
    DISCOVERY_LIVE_TEST=1 uv run pytest -m integration tests/integration/test_discovery_live.py
"""

from __future__ import annotations

import os

import pytest

from applicant.adapters.discovery.factory import build_default_discovery
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id

_ENABLED = os.environ.get("DISCOVERY_LIVE_TEST") == "1"


@pytest.mark.integration
@pytest.mark.skipif(not _ENABLED, reason="Set DISCOVERY_LIVE_TEST=1 to hit real boards.")
def test_live_jobspy_returns_postings():
    cid = CampaignId(new_id())
    agg = build_default_discovery(
        live=True,
        searxng_url=os.environ.get("SEARXNG_URL", ""),
        include_sample=False,
    )
    crit = SearchCriteria(campaign_id=cid, titles=("software engineer",), locations=("Remote",))
    results = agg.search(cid, crit)
    assert results, "expected at least one live posting from the easy boards"
    for p in results:
        assert p.title and p.source_url and p.source_key
