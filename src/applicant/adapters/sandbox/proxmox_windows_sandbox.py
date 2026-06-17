"""Native Proxmox Windows VM sandbox backend (FR-SANDBOX-1/4, FR-STEALTH-1).

A selectable :class:`SandboxPort` where the browser the engine drives — and that the
human takes over — is REAL Google Chrome inside a real, licensed Windows VM on a
Proxmox node. Because it IS real Windows, the fingerprint (JA3/TLS, Direct3D WebGL,
Segoe UI/Calibri, OS signals) is genuinely Windows with ZERO spoofing — the
strongest FR-STEALTH-1. The stealth persona is therefore ``native`` (no override).

DEFINITION OF READY (the operator provides; documented in the README): a licensed
Windows VM (Server or Desktop) on the Proxmox node with Google Chrome installed +
qemu-guest-agent + RDP enabled. EVERYTHING ELSE is automated here.

Lifecycle (mirrors :class:`LocalSandbox`'s multi-session bookkeeping):

* ``provision`` — clone the template (``linked-clone``) OR reuse the persistent VM
  with a snapshot-revert (``snapshot-revert``), start it, wait for the guest agent +
  Chrome's CDP endpoint to be reachable, launch Chrome with ``--remote-debugging-*``,
  and return a :class:`SandboxSession` carrying the CDP ws endpoint (for automation),
  a tokenized takeover URL (RDP / web-console), and the application URL (continuity).
* ``teardown`` — snapshot-revert / stop / destroy the clone; invalidate the token.

The REAL Proxmox control plane is the integration-gated :class:`ProxmoxApiClient`;
the default lane injects :class:`FakeProxmoxClient` so the orchestration, selection,
CDP wiring, takeover URL/token, and lifecycle are all unit-tested with NO Proxmox /
Windows / CDP / RDP.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from applicant.adapters.sandbox.proxmox_client import (
    ProxmoxClient,
    cdp_ws_endpoint,
    chrome_cdp_command,
)
from applicant.adapters.sandbox.remote_view import WindowsRdpRemoteView
from applicant.core.ids import ApplicationId, new_id
from applicant.observability.logging import get_logger
from applicant.ports.driven.sandbox import RemoteViewPort, SandboxSession

log = get_logger(__name__)

#: Clone modes (mirror app.config constants; duplicated here to keep the adapter
#: importable without the settings module).
CLONE_LINKED = "linked-clone"
CLONE_SNAPSHOT_REVERT = "snapshot-revert"

#: The clean baseline snapshot name used by snapshot-revert reuse mode.
CLEAN_SNAPSHOT = "applicant-clean"


@dataclass
class _WinSession:
    """Internal per-session VM bookkeeping (vmid + mode for teardown)."""

    session: SandboxSession
    vmid: int
    clone_mode: str


class ProxmoxWindowsSandbox:
    """SandboxPort adapter — real Chrome in a real Windows VM on Proxmox.

    Swappable behind the existing :class:`SandboxPort` / :class:`RemoteViewPort`
    contract: the engine, services, and router are unchanged.
    """

    backend = "proxmox-windows"

    def __init__(
        self,
        client: ProxmoxClient,
        *,
        template_vmid: int,
        node: str = "",
        clone_mode: str = CLONE_SNAPSHOT_REVERT,
        cdp_host: str = "",
        cdp_port: int = 9222,
        remote_view: RemoteViewPort | None = None,
        app_url_for: Callable[[ApplicationId], str | None] | None = None,
    ) -> None:
        self._client = client
        self._template_vmid = template_vmid
        self._node = node
        self._clone_mode = clone_mode
        #: Empty cdp_host -> use the guest's reported IP (the usual case).
        self._cdp_host = cdp_host
        self._cdp_port = cdp_port
        self._remote_view = remote_view or WindowsRdpRemoteView()
        #: Optional resolver: application_id -> application URL (session continuity).
        self._app_url_for = app_url_for
        #: session_id -> _WinSession (live only; popped on teardown).
        self._sessions: dict[str, _WinSession] = {}
        #: application_id -> session_id (one active sandbox per application).
        self._by_application: dict[str, str] = {}

    # --- SandboxPort -----------------------------------------------------
    def provision(self, application_id: ApplicationId) -> SandboxSession:
        """Provision a Windows VM, launch Chrome-over-CDP, return the session.

        ``linked-clone`` mode clones the template per session (destroyed on
        teardown). ``snapshot-revert`` reuses the persistent template VMID, rolling
        it back to the clean snapshot for a fresh start.
        """
        session_id = f"winvm-{new_id()[:12]}"
        if self._clone_mode == CLONE_LINKED:
            vmid = self._client.clone_vm(
                self._template_vmid, name=session_id, linked=True
            )
        else:
            vmid = self._template_vmid
            # Roll back to the clean baseline so the session starts pristine.
            self._client.snapshot_rollback(vmid, CLEAN_SNAPSHOT)

        self._client.start_vm(vmid)
        # Wait for the guest agent + Chrome's CDP endpoint (real waits are
        # integration-gated; the fake returns immediately).
        host = self._cdp_host or self._client.guest_ip(vmid)
        # Launch Chrome with --remote-debugging-port/-address so the engine can
        # connect over CDP. Bind to 0.0.0.0 inside the guest so the host can reach it.
        self._client.guest_exec(
            vmid, chrome_cdp_command(port=self._cdp_port, address="0.0.0.0")
        )
        cdp = cdp_ws_endpoint(host, self._cdp_port)

        app_url = self._resolve_app_url(application_id)
        # Bind the VM's connection details to the takeover sub-port so the one-click
        # takeover URL (RDP / web-console) resolves with a fresh token.
        bind = getattr(self._remote_view, "bind_session", None)
        if callable(bind):
            bind(
                session_id,
                host=host,
                vmid=vmid,
                node=self._node,
                app_url=app_url or "",
            )
        takeover_url = self._remote_view.view_url(session_id)

        session = SandboxSession(
            session_id=session_id,
            application_id=application_id,
            remote_view_url=takeover_url,
            cdp_endpoint=cdp,
            application_url=app_url,
        )
        self._sessions[session_id] = _WinSession(
            session=session, vmid=vmid, clone_mode=self._clone_mode
        )
        self._by_application[str(application_id)] = session_id
        log.info(
            "proxmox_windows_provisioned",
            session_id=session_id,
            vmid=vmid,
            clone_mode=self._clone_mode,
        )
        return session

    def teardown(self, session_id: str) -> None:
        """Tear down the Windows VM session; idempotent.

        ``linked-clone`` -> stop + destroy the ephemeral clone. ``snapshot-revert``
        -> stop + roll back to the clean snapshot (the persistent VM is kept). The
        takeover token is always invalidated so the deep link stops working.
        """
        win = self._sessions.pop(session_id, None)
        if win is None:
            return  # idempotent
        self._by_application.pop(str(win.session.application_id), None)
        try:
            self._client.stop_vm(win.vmid)
            if win.clone_mode == CLONE_LINKED:
                self._client.destroy_vm(win.vmid)
            else:
                self._client.snapshot_rollback(win.vmid, CLEAN_SNAPSHOT)
        finally:
            invalidate = getattr(self._remote_view, "invalidate", None)
            if callable(invalidate):
                invalidate(session_id)
        log.info("proxmox_windows_teardown", session_id=session_id, vmid=win.vmid)

    def remote_view(self) -> RemoteViewPort:
        """Return the swappable remote-view sub-port (RDP / web-console)."""
        return self._remote_view

    def active_sessions(self) -> list[SandboxSession]:
        return [w.session for w in self._sessions.values()]

    # --- introspection helpers (parity with LocalSandbox) ----------------
    def active_count(self) -> int:
        return len(self._sessions)

    def get(self, session_id: str) -> SandboxSession | None:
        win = self._sessions.get(session_id)
        return win.session if win else None

    def for_application(self, application_id: ApplicationId) -> SandboxSession | None:
        sid = self._by_application.get(str(application_id))
        win = self._sessions.get(sid) if sid else None
        return win.session if win else None

    # --- internals -------------------------------------------------------
    def _resolve_app_url(self, application_id: ApplicationId) -> str | None:
        if self._app_url_for is None:
            return None
        try:
            return self._app_url_for(application_id) or None
        except Exception:  # pragma: no cover - defensive
            return None
