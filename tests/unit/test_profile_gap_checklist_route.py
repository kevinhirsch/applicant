"""Profile-gap checklist route (dark-engine audit item 51).

``ChatService.identify_gaps(campaign_id)`` already computes which core profile
attributes (name/email/phone/title) and search criteria are still missing --
previously read ONLY as hidden LLM context inside a chat turn (``converse``),
with no route exposing it as a visible checklist. This proves the new
``GET /api/setup/{campaign_id}/gaps`` route is registered, reachable, and reports
the SAME real gap list ``ChatService.identify_gaps`` computes directly -- no
separate/duplicated computation, nothing fabricated.

Hermetic (in-memory storage via an unreachable ``DATABASE_URL``, per repo
CLAUDE.md), mirrors the shape of ``test_stuck_applications_route.py``: real
container services driven through the actual route, not mocks.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.ids import CampaignId, new_id


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _registered_paths(app) -> set[str]:
    paths: set[str] = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    return paths


def _seed_bare_campaign(container, *, name="C") -> CampaignId:
    """A campaign with NO criteria seeded (unlike ``CampaignService.create_campaign``,
    which auto-seeds ``titles``/``human_readable`` from the campaign name -- #6 --
    which would mask the "target roles / search criteria" gap this test exercises).
    Mirrors ``test_stuck_applications_route.py``'s direct-storage seeding.
    """
    cid = CampaignId(new_id())
    container.storage.campaigns.add(
        Campaign(id=cid, name=name, run_mode=RunMode.CONTINUOUS, throughput_target=15, schedule={})
    )
    container.storage.commit()
    return cid


def test_gaps_route_is_registered(client):
    assert "/api/setup/{campaign_id}/gaps" in _registered_paths(client.app)


def test_brand_new_campaign_reports_every_core_gap(client):
    container = client.app.state.container
    cid = _seed_bare_campaign(container)

    r = client.get(f"/api/setup/{cid}/gaps")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == str(cid)
    assert body["complete"] is False
    # Real gaps from a genuinely empty campaign -- matches ChatService's own
    # core-needs set (identity attributes + search criteria), never fabricated.
    assert "email address" in body["gaps"]
    assert "phone" in body["gaps"]
    assert "target roles / search criteria" in body["gaps"]
    # "current job title" is NOT a core need (dark-engine audit): no onboarding
    # section writes that key, and the apply-readiness gate never required it either
    # -- reporting it here would contradict apply_ready=true forever.
    assert "current job title" not in body["gaps"]


def test_gaps_shrink_as_real_attributes_and_criteria_are_added(client):
    container = client.app.state.container
    cid = _seed_bare_campaign(container)

    attrs = container.attribute_cloud_service
    attrs.upsert(cid, "full_name", "Dana Lee", confirm=True)
    attrs.upsert(cid, "email", "dana@example.com", confirm=True)
    attrs.upsert(cid, "phone", "555-0100", confirm=True)
    attrs.upsert(cid, "title", "Backend Engineer", confirm=True)

    r = client.get(f"/api/setup/{cid}/gaps")
    body = r.json()
    # Identity attributes are covered; only the criteria gap remains.
    assert body["gaps"] == ["target roles / search criteria"]
    assert body["complete"] is False

    container.criteria_service.edit_criteria(
        cid, changes={"titles": ["Backend Engineer"]}, confirm=True
    )

    r2 = client.get(f"/api/setup/{cid}/gaps")
    body2 = r2.json()
    assert body2["gaps"] == []
    assert body2["complete"] is True


def test_gaps_route_matches_chat_service_identify_gaps_directly(client):
    """The route must not duplicate/re-derive the gap computation -- it has to
    read the exact same list ``ChatService.identify_gaps`` produces."""
    container = client.app.state.container
    cid = _seed_bare_campaign(container)
    container.attribute_cloud_service.upsert(cid, "full_name", "Dana Lee", confirm=True)

    expected = container.chat_service.identify_gaps(CampaignId(str(cid)))

    r = client.get(f"/api/setup/{cid}/gaps")
    assert r.json()["gaps"] == expected


def test_gaps_endpoint_never_disagrees_with_apply_readiness_on_job_title(client):
    """Dark-engine audit: identify_gaps() must agree with the apply-readiness gate.

    ``apply_readiness`` (core/rules/apply_readiness.py) has NEVER required a job
    title. Before this fix, ``identify_gaps()`` falsely required "current job title"
    forever (nothing in onboarding writes that key), so a fully-onboarded campaign
    could show ``apply_ready=true`` from the gate while /gaps still listed a job
    title as missing -- an unresolvable, contradictory nag. Seed a campaign that is
    ready per the apply-readiness gate and confirm /gaps reports zero gaps too, with
    no job-title attribute set anywhere.
    """
    container = client.app.state.container
    cid = _seed_bare_campaign(container)

    attrs = container.attribute_cloud_service
    attrs.upsert(cid, "full_name", "Dana Lee", confirm=True)
    attrs.upsert(cid, "email", "dana@example.com", confirm=True)
    attrs.upsert(cid, "phone", "555-0100", confirm=True)
    container.criteria_service.edit_criteria(
        cid,
        changes={
            "titles": ["Backend Engineer"],
            "work_modes": ["remote"],
            "locations": ["Remote"],
            "salary_floor": 120000,
            "keywords": ["python"],
        },
        confirm=True,
    )
    # Stand in for a real résumé ingest (apply_readiness's own résumé check) --
    # deliberately NO "title"/"current job title" attribute is ever set.
    container.onboarding_service.has_base_resume = lambda campaign_id: True

    readiness = container.onboarding_service.apply_readiness(str(cid))
    assert readiness.ready is True
    assert not any("title" in m.lower() for m in readiness.missing)

    r = client.get(f"/api/setup/{cid}/gaps")
    body = r.json()
    assert body["gaps"] == []
    assert body["complete"] is True
    assert "current job title" not in body["gaps"]


def test_gaps_route_for_unknown_campaign_is_well_formed(client):
    r = client.get("/api/setup/no-such-campaign/gaps")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == "no-such-campaign"
    assert isinstance(body["gaps"], list) and body["gaps"]
    assert body["complete"] is False
