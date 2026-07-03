"""Hermetic test for the ``ApplicantEngineClient.setup_get_gaps`` client method
(dark-engine audit item 51) -- the workspace-side call the profile-gap-checklist
proxy route (``routes/applicant_setup_routes.py``) uses to reach the engine's new
``GET /api/setup/{campaign_id}/gaps`` route.

Zero network: served by an ``httpx.MockTransport``, matching the pattern in
``test_applicant_engine.py``. Proves the client hits the right URL (the campaign
id path-interpolated, not query-stringed or dropped) and returns the engine's
JSON unchanged.
"""

import httpx
import pytest

from src.applicant_engine import ApplicantEngineClient


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_setup_get_gaps_hits_the_campaign_scoped_url():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={"campaign_id": "camp-1", "gaps": ["email address", "phone"], "complete": False},
        )

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        data = await engine.setup_get_gaps("camp-1")

    assert captured["url"] == "http://api:8000/api/setup/camp-1/gaps"
    assert captured["method"] == "GET"
    assert data == {"campaign_id": "camp-1", "gaps": ["email address", "phone"], "complete": False}


@pytest.mark.asyncio
async def test_setup_get_gaps_complete_profile_passes_through():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"campaign_id": "camp-2", "gaps": [], "complete": True})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=_transport(handler)
    ) as engine:
        data = await engine.setup_get_gaps("camp-2")

    assert data["complete"] is True
    assert data["gaps"] == []
