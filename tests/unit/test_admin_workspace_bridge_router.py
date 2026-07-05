"""Coverage: ``GET /api/admin/workspace-bridge`` (dark-engine audit #71).

``HttpWorkspaceClient.ping`` existed exactly for a health probe but nothing ever
called it and no surface showed whether ``APPLICANT_INTERNAL_TOKEN`` is even
configured — a bad/missing token silently disables calendar-interview sync,
deep-research, and the memory/skills bridge with zero visible signal. These call
the router function directly against a fake ``container.workspace`` (a plain
function; explicit kwargs bypass FastAPI's ``Depends`` resolution) so the
configured/reachable matrix is exercised hermetically, without a real HTTP
callback channel.
"""

from __future__ import annotations

import pytest

from applicant.app.routers.admin import workspace_bridge
from applicant.ports.driven.workspace import WorkspaceError


class _FakeContainer:
    def __init__(self, workspace):
        self.workspace = workspace


class _DisabledWorkspace:
    """Mirrors HttpWorkspaceClient with no APPLICANT_INTERNAL_TOKEN configured."""

    def available(self) -> bool:
        return False

    def ping(self):  # pragma: no cover - must never be called when disabled
        raise AssertionError("ping() must not be called when the channel is disabled")


class _ReachableWorkspace:
    def available(self) -> bool:
        return True

    def ping(self):
        return {"status": "ok"}


class _ConfiguredButDownWorkspace:
    def available(self) -> bool:
        return True

    def ping(self):
        raise WorkspaceError("Workspace request to /ping failed: connection refused")


@pytest.mark.unit
def test_bridge_reports_not_configured_without_a_token():
    out = workspace_bridge(container=_FakeContainer(_DisabledWorkspace()))
    assert out == {"configured": False, "reachable": False, "detail": None, "status": "live"}


@pytest.mark.unit
def test_bridge_pings_through_when_configured_and_reachable():
    out = workspace_bridge(container=_FakeContainer(_ReachableWorkspace()))
    assert out["configured"] is True
    assert out["reachable"] is True
    assert out["detail"] is None


@pytest.mark.unit
def test_bridge_reports_configured_but_unreachable():
    out = workspace_bridge(container=_FakeContainer(_ConfiguredButDownWorkspace()))
    assert out["configured"] is True
    assert out["reachable"] is False
    assert "connection refused" in out["detail"]
