"""Coverage: pending-actions lightweight COUNT endpoint (docs/design/audits/
PRODUCT_DEEP_AUDIT_ROUND3.md exhaustive2/03_performance.md item #5).

The 60s Portal badge poll used to download the FULL pending payload (shaped
rows + derived task metadata for every open item) just to read an integer
count. This adds a sibling ``GET /api/pending-actions/{campaign_id}/count``
that reuses the exact same open-action query
(:meth:`PendingActionsService.list_pending`, itself backed by the indexed
``(campaign_id, resolved)`` query) but returns only ``{campaign_id, count}`` —
no items, no per-item task-metadata derivation.

Hermetic: in-memory storage, real container services (mirrors the existing
``tests/unit/test_pending_actions_tasks.py`` / ``test_cov_pending_actions.py``
pattern for this router).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.ids import CampaignId, new_id


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _svc(client):
    return client.app.state.container.pending_actions_service


# --- the count endpoint -------------------------------------------------


def test_count_endpoint_matches_list_count_for_open_actions(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    svc.materialize(cid, "agent_question", "Which city?")
    svc.materialize(cid, "material_review", "Cover letter ready")
    svc.materialize(cid, "missing_attr", "Need a phone number")

    list_body = client.get(f"/api/pending-actions/{cid}").json()
    count_body = client.get(f"/api/pending-actions/{cid}/count").json()

    assert count_body == {"campaign_id": str(cid), "count": 3}
    assert count_body["count"] == list_body["count"] == len(list_body["items"])


def test_count_endpoint_response_has_no_items_or_metadata(client):
    # The whole point of this endpoint is to avoid paying for per-item task
    # metadata + full row serialization — assert the payload really is just
    # the two fields, not a truncated/renamed version of the list response.
    svc = _svc(client)
    cid = CampaignId(new_id())
    svc.materialize(cid, "agent_question", "Which city?")

    r = client.get(f"/api/pending-actions/{cid}/count")
    assert r.status_code == 200
    assert set(r.json().keys()) == {"campaign_id", "count"}


def test_count_endpoint_zero_for_unknown_or_empty_campaign(client):
    cid = CampaignId(new_id())
    r = client.get(f"/api/pending-actions/{cid}/count")
    assert r.status_code == 200
    assert r.json() == {"campaign_id": str(cid), "count": 0}


def test_count_endpoint_excludes_resolved_actions(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    a1 = svc.materialize(cid, "agent_question", "Which city?")
    svc.materialize(cid, "agent_question", "Remote OK?")
    assert client.get(f"/api/pending-actions/{cid}/count").json()["count"] == 2

    svc.resolve(a1.id)
    assert client.get(f"/api/pending-actions/{cid}/count").json()["count"] == 1


def test_count_endpoint_excludes_snoozed_by_default(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    a1 = svc.materialize(cid, "agent_question", "Which city?")
    svc.materialize(cid, "agent_question", "Remote OK?")
    svc.snooze(a1.id, hours=24)

    # Snoozed items drop off the default (badge) count, same as the list...
    assert client.get(f"/api/pending-actions/{cid}/count").json()["count"] == 1
    # ...and reappear when explicitly asked for (mirrors the list endpoint's
    # own `include_snoozed` contract).
    r = client.get(f"/api/pending-actions/{cid}/count", params={"include_snoozed": "true"})
    assert r.json()["count"] == 2


def test_count_endpoint_scoped_per_campaign(client):
    svc = _svc(client)
    cid_a = CampaignId(new_id())
    cid_b = CampaignId(new_id())
    svc.materialize(cid_a, "agent_question", "A1")
    svc.materialize(cid_a, "agent_question", "A2")
    svc.materialize(cid_b, "agent_question", "B1")

    assert client.get(f"/api/pending-actions/{cid_a}/count").json()["count"] == 2
    assert client.get(f"/api/pending-actions/{cid_b}/count").json()["count"] == 1


# --- gated behind the same LLM-settings dependency as the rest of the router -


def test_count_endpoint_gated_without_llm_configured():
    # A fresh app with no LLM configured must gate the count route exactly like
    # every other route on this router (`dependencies=[Depends(require_llm_configured)]`
    # at the router level) — proves the new route was added to the SAME router,
    # not a bypassing sibling.
    with TestClient(create_app()) as c:
        cid = CampaignId(new_id())
        r = c.get(f"/api/pending-actions/{cid}/count")
        assert r.status_code in (401, 403, 409)


# --- service-level unit coverage -----------------------------------------


def test_service_count_pending_matches_len_of_list_pending(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    svc.materialize(cid, "agent_question", "Which city?")
    svc.materialize(cid, "agent_question", "Remote OK?")
    a3 = svc.materialize(cid, "agent_question", "Salary range?")
    svc.snooze(a3.id, hours=24)

    assert svc.count_pending(cid) == len(svc.list_pending(cid))
    assert svc.count_pending(cid) == 2
    assert svc.count_pending(cid, include_snoozed=True) == 3
    assert svc.count_pending(cid, include_snoozed=True) == len(
        svc.list_pending(cid, include_snoozed=True)
    )


def test_service_count_pending_zero_when_none_open(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    assert svc.count_pending(cid) == 0
