"""Lens 04 #27 — ``PendingActionsService.resolve`` signals an already-resolved
no-op instead of looking identical to a fresh resolve.

Before the fix, ``resolve()`` always called the storage-level ``resolve`` +
``commit()`` and returned ``None`` regardless of whether the action was open or
already resolved — a double-resolve (two tabs, a retried request, a stale
client re-sending the same action id) had no way to tell whether its call
actually cleared anything. ``resolve()`` now returns one of the stable outcome
strings (:data:`RESOLVE_RESOLVED` / :data:`RESOLVE_ALREADY_RESOLVED` /
:data:`RESOLVE_NOT_FOUND`) while staying idempotent — the underlying action is
never re-applied on a repeat call.

DISC-6 (discovered-issues ledger): that service-level signal was computed but
never left the service — ``app/routers/pending_actions.py`` returned a bare
``204`` regardless of the outcome, so the front-door had no way to surface
"this was already handled" to the user. The ``test_router_*`` cases below pin
the router-level fix: a genuine resolve still returns the original bare
``204``, but an already-resolved repeat now returns a distinguishable ``200``
body instead of a silent second ``204``.

Hermetic: real container services over the in-memory storage adapter (same
harness as ``tests/unit/test_pending_actions_tasks.py``).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.application.services.pending_actions_service import (
    RESOLVE_ALREADY_RESOLVED,
    RESOLVE_NOT_FOUND,
    RESOLVE_RESOLVED,
)
from applicant.core.ids import CampaignId, PendingActionId, new_id


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


def test_first_resolve_reports_resolved(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")

    outcome = svc.resolve(action.id)

    assert outcome == RESOLVE_RESOLVED
    assert not any(a.id == action.id for a in svc.list_pending(cid))


def test_second_resolve_on_same_action_reports_already_resolved(client):
    """The core regression: a double-resolve must be DISTINGUISHABLE from the
    first, real resolve — not silently report the same outcome."""
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")

    first = svc.resolve(action.id)
    second = svc.resolve(action.id)

    assert first == RESOLVE_RESOLVED
    assert second == RESOLVE_ALREADY_RESOLVED
    assert first != second


def test_resolve_stays_idempotent_across_repeat_calls(client):
    """Idempotency is preserved: repeat resolves are no-ops storage-side, even
    though the outcome they report is now distinguishable."""
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")

    svc.resolve(action.id)
    svc.resolve(action.id)
    third = svc.resolve(action.id)

    assert third == RESOLVE_ALREADY_RESOLVED
    stored = svc.get(action.id)
    assert stored.resolved is True


def test_resolve_unknown_action_reports_not_found(client):
    svc = _svc(client)
    outcome = svc.resolve(PendingActionId(new_id()))
    assert outcome == RESOLVE_NOT_FOUND


# --- DISC-6: the router surfaces the signal instead of a bare 204 ----------


def test_router_first_resolve_still_returns_bare_204(client):
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")

    res = client.post(f"/api/pending-actions/{action.id}/resolve")

    assert res.status_code == 204
    assert res.content == b""


def test_router_second_resolve_surfaces_already_resolved_distinguishably(client):
    """The core DISC-6 regression: a repeat resolve through the HTTP router
    (not just the service) must come back looking different from the first,
    real resolve — not another identical silent 204."""
    svc = _svc(client)
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")

    first = client.post(f"/api/pending-actions/{action.id}/resolve")
    second = client.post(f"/api/pending-actions/{action.id}/resolve")

    assert first.status_code == 204
    assert second.status_code == 200
    assert second.json() == {"action_id": str(action.id), "status": "already_resolved"}
