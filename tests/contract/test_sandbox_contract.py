"""Sandbox + RemoteView contract (FR-SANDBOX-1/2/3/4).

Asserts the behavioral contract a ``SandboxPort`` + ``RemoteViewPort`` promise:
provision mints an ephemeral session with a one-click view URL, sessions are
multi and independently controllable, teardown is idempotent, and the remote-view
sub-port is swappable (Neko <-> noVNC) under one identical contract.
"""

from __future__ import annotations

import pytest

from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.sandbox.remote_view import NekoRemoteView, NoVncRemoteView
from applicant.core.ids import ApplicationId, new_id
from applicant.ports.driven.sandbox import (
    RemoteViewPort,
    SandboxPort,
    SandboxSession,
)


@pytest.mark.contract
class TestLocalSandboxContract:
    @pytest.fixture
    def adapter(self) -> LocalSandbox:
        return LocalSandbox()

    def test_satisfies_port_protocol(self, adapter):
        assert isinstance(adapter, SandboxPort)
        assert isinstance(adapter.remote_view(), RemoteViewPort)

    def test_provision_returns_session_with_view_url(self, adapter):
        aid = ApplicationId(new_id())
        session = adapter.provision(aid)
        assert isinstance(session, SandboxSession)
        assert session.application_id == aid
        assert session.remote_view_url  # one-click live-session URL (FR-SANDBOX-2)

    def test_multi_session_independent(self, adapter):
        # FR-SANDBOX-4: multi + independently controllable.
        s1 = adapter.provision(ApplicationId(new_id()))
        s2 = adapter.provision(ApplicationId(new_id()))
        assert s1.session_id != s2.session_id
        assert len(adapter.active_sessions()) == 2

    def test_teardown_is_ephemeral_and_idempotent(self, adapter):
        session = adapter.provision(ApplicationId(new_id()))
        adapter.teardown(session.session_id)
        assert adapter.get(session.session_id) is None
        adapter.teardown(session.session_id)  # idempotent: no error


@pytest.mark.contract
@pytest.mark.parametrize("view_cls", [NekoRemoteView, NoVncRemoteView])
class TestRemoteViewSwappable:
    """The remote-view sub-port honors one contract regardless of provider."""

    def test_satisfies_port_protocol(self, view_cls):
        assert isinstance(view_cls(), RemoteViewPort)

    def test_view_url_is_one_click(self, view_cls):
        view = view_cls()
        url = view.view_url("sess-1")
        assert isinstance(url, str) and "sess-1" in url

    def test_authorize_takeover(self, view_cls):
        view = view_cls()
        assert view.has_takeover("sess-1") is False
        view.authorize_takeover("sess-1")
        assert view.has_takeover("sess-1") is True


@pytest.mark.contract
def test_sandbox_remote_view_is_swappable():
    """LocalSandbox accepts either remote-view adapter (Neko <-> noVNC)."""
    neko = LocalSandbox(remote_view=NekoRemoteView())
    novnc = LocalSandbox(remote_view=NoVncRemoteView())
    assert neko.remote_view().provider == "neko"
    assert novnc.remote_view().provider == "novnc"
