"""Coverage: pending-actions ROUTER apply-on-resolve (FR-FB-3 / FR-LEARN-4).

A held integral change (kind ``integral_change``) is confirmed/applied through the
resolve endpoint with ``{"apply": true}`` — the user's explicit confirmation that
passes the engine's confirmation gate — and merely cleared with ``{"apply": false}``.
Hermetic: in-memory storage, real container services.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.attribute import Attribute
from applicant.core.ids import AttributeId, CampaignId, new_id


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _seed_integral(container, cid, name, value):
    container.storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name=name, value=value, is_integral=True)
    )
    container.storage.commit()


def _hold_change(container, cid, name, proposed, current):
    return container.pending_actions_service.integral_change_confirmation(
        cid, attribute_name=name, proposed_value=proposed, current_value=current
    )


def test_apply_true_commits_the_held_integral_change(client):
    container = client.app.state.container
    cid = CampaignId(new_id())
    _seed_integral(container, cid, "location", "San Francisco")
    action = _hold_change(container, cid, "location", "New York", "San Francisco")

    res = client.post(f"/api/pending-actions/{action.id}/resolve", json={"apply": True})
    assert res.status_code == 204
    # The confirmed change is committed through the gate...
    attr = next(
        a for a in container.storage.attributes.list_for_campaign(cid) if a.name == "location"
    )
    assert attr.value == "New York"
    # ...and the item is cleared.
    assert not any(a.kind == "integral_change" for a in container.pending_actions_service.list_pending(cid))


def test_apply_false_keeps_current_value_and_clears(client):
    container = client.app.state.container
    cid = CampaignId(new_id())
    _seed_integral(container, cid, "location", "San Francisco")
    action = _hold_change(container, cid, "location", "New York", "San Francisco")

    res = client.post(f"/api/pending-actions/{action.id}/resolve", json={"apply": False})
    assert res.status_code == 204
    attr = next(
        a for a in container.storage.attributes.list_for_campaign(cid) if a.name == "location"
    )
    assert attr.value == "San Francisco"  # unchanged
    assert not any(a.kind == "integral_change" for a in container.pending_actions_service.list_pending(cid))


def test_resolve_without_body_still_clears(client):
    # A plain resolve (no body) must keep working for every other kind.
    container = client.app.state.container
    cid = CampaignId(new_id())
    _seed_integral(container, cid, "location", "San Francisco")
    action = _hold_change(container, cid, "location", "New York", "San Francisco")

    res = client.post(f"/api/pending-actions/{action.id}/resolve")
    assert res.status_code == 204
    attr = next(
        a for a in container.storage.attributes.list_for_campaign(cid) if a.name == "location"
    )
    assert attr.value == "San Francisco"  # not applied without apply=true
    assert not any(a.kind == "integral_change" for a in container.pending_actions_service.list_pending(cid))
