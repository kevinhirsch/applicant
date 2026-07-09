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


# ── resolve idempotency on an already-resolved integral_change (bug fix) ─────
#
# Bug fix: ``resolve()`` now checks ``action.resolved`` BEFORE re-applying the
# ``integral_change`` attribute-cloud side effect, so calling resolve twice on the
# same action (double-click, retried request, two tabs) commits the change exactly
# once instead of re-applying it on every call.


def _spy_upsert(container):
    calls: list[tuple[tuple, dict]] = []
    orig_upsert = container.attribute_cloud_service.upsert

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return orig_upsert(*args, **kwargs)

    container.attribute_cloud_service.upsert = spy
    return calls


def test_resolve_integral_change_applies_upsert_exactly_once(client):
    container = client.app.state.container
    cid = CampaignId(new_id())
    _seed_integral(container, cid, "location", "San Francisco")
    action = _hold_change(container, cid, "location", "New York", "San Francisco")
    calls = _spy_upsert(container)

    res = client.post(f"/api/pending-actions/{action.id}/resolve", json={"apply": True})

    assert res.status_code == 204
    assert len(calls) == 1
    attr = next(
        a for a in container.storage.attributes.list_for_campaign(cid) if a.name == "location"
    )
    assert attr.value == "New York"


def test_resolve_already_resolved_integral_change_does_not_reapply(client):
    """A second resolve call on the SAME (already-resolved) integral_change action
    must NOT re-run the attribute-cloud upsert — the fix short-circuits on
    ``action.resolved`` before the side effect."""
    container = client.app.state.container
    cid = CampaignId(new_id())
    _seed_integral(container, cid, "location", "San Francisco")
    action = _hold_change(container, cid, "location", "New York", "San Francisco")
    calls = _spy_upsert(container)

    first = client.post(f"/api/pending-actions/{action.id}/resolve", json={"apply": True})
    assert first.status_code == 204
    assert len(calls) == 1

    second = client.post(f"/api/pending-actions/{action.id}/resolve", json={"apply": True})
    # DISC-6: a repeat resolve of an already-resolved action is now
    # distinguishable from the fresh 204 above -- a 200 body carrying the
    # already-resolved signal, not a silent repeat 204.
    assert second.status_code == 200
    assert second.json() == {"action_id": str(action.id), "status": "already_resolved"}
    assert len(calls) == 1  # unchanged: the side effect did NOT re-fire
