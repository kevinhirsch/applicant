"""Proxmox VE API client boundary (FR-SANDBOX-1/4, FR-STEALTH-1).

A thin client over the Proxmox VE REST API used by the native Windows-VM sandbox
backend. The REAL :class:`ProxmoxApiClient` (httpx + the PVE API-token header) is
the clearly-marked ``# integration`` boundary — it talks to a real Proxmox node and
a real licensed Windows guest (qemu-guest-agent + Google Chrome + RDP). The default
test lane never reaches it; instead it drives the in-memory :class:`FakeProxmoxClient`
so the whole provision/teardown lifecycle, CDP-endpoint wiring, snapshot-revert and
clone bookkeeping are unit-tested with NO Proxmox / Windows / network.

Operations the backend needs (the ``ProxmoxClient`` protocol):

* ``clone_vm`` — clone the template VMID into a fresh (linked) clone VMID.
* ``start_vm`` / ``stop_vm`` / ``vm_status`` — power lifecycle.
* ``snapshot_create`` / ``snapshot_rollback`` — clean-snapshot revert (reuse mode).
* ``guest_exec`` — ``qm guest exec`` via the agent: launch Chrome with
  ``--remote-debugging-port`` / ``--remote-debugging-address`` and read the guest IP.
* ``guest_ip`` — the VM's reachable IP (for the CDP + RDP endpoints).
* ``destroy_vm`` — destroy an ephemeral clone on teardown.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProxmoxClient(Protocol):
    """The thin PVE operations surface the Windows-VM sandbox drives."""

    def clone_vm(self, template_vmid: int, *, name: str, linked: bool = True) -> int:
        """Clone ``template_vmid`` and return the new clone's VMID."""
        ...

    def start_vm(self, vmid: int) -> None:
        """Power on ``vmid``."""
        ...

    def stop_vm(self, vmid: int) -> None:
        """Power off ``vmid``."""
        ...

    def vm_status(self, vmid: int) -> str:
        """Return the qemu run state (``running`` / ``stopped`` / ...)."""
        ...

    def snapshot_create(self, vmid: int, name: str) -> None:
        """Create a named snapshot of ``vmid`` (the clean baseline)."""
        ...

    def snapshot_rollback(self, vmid: int, name: str) -> None:
        """Roll ``vmid`` back to a named snapshot (clean-revert reuse mode)."""
        ...

    def guest_exec(self, vmid: int, command: list[str]) -> dict:
        """Run a command in the guest via qemu-guest-agent; return its result dict."""
        ...

    def guest_ip(self, vmid: int) -> str:
        """Return the guest's reachable IPv4 address (via the agent)."""
        ...

    def destroy_vm(self, vmid: int) -> None:
        """Destroy ``vmid`` (an ephemeral clone), freeing the VMID."""
        ...


#: How Google Chrome is launched inside the Windows guest so its CDP endpoint is
#: reachable from the host. ``{port}`` / ``{host}`` are substituted per session.
#: ``--remote-debugging-address`` is what lets the host (not just localhost) connect.
CHROME_CDP_LAUNCH = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--remote-debugging-port={port}",
    "--remote-debugging-address={host}",
    "--user-data-dir=C:\\applicant\\chrome-profile",
    "--no-first-run",
    "--no-default-browser-check",
)


def chrome_cdp_command(*, port: int, address: str = "0.0.0.0") -> list[str]:
    """Build the in-guest Chrome launch command exposing CDP (pure + unit-testable).

    Real Windows Chrome bound to ``--remote-debugging-address`` lets the engine's
    Playwright ``connect_over_cdp`` reach it from the host. The fingerprint is
    genuinely Windows (Direct3D WebGL, Segoe UI/Calibri, OS signals) with NO
    spoofing — the strongest FR-STEALTH-1.
    """
    return [
        part.format(port=port, host=address) for part in CHROME_CDP_LAUNCH
    ]


def cdp_ws_endpoint(host: str, port: int) -> str:
    """Build the CDP WebSocket-debugger base endpoint for ``host:port``.

    Playwright's ``connect_over_cdp`` accepts the HTTP base (``http://host:port``)
    and resolves the ``/json/version`` ``webSocketDebuggerUrl`` itself.
    """
    return f"http://{host}:{port}"


class FakeProxmoxClient:
    """In-memory :class:`ProxmoxClient` for the default lane (NO Proxmox / network).

    Models VMID allocation, power state, snapshots, the guest IP, and records every
    ``guest_exec`` call so tests can assert the Chrome-CDP launch command without a
    real Windows guest. Deterministic and side-effect-free.
    """

    def __init__(self, *, base_vmid: int = 9000, guest_ip: str = "10.0.0.50") -> None:
        self._next_vmid = base_vmid
        self._guest_ip = guest_ip
        #: vmid -> run state.
        self.status: dict[int, str] = {}
        #: vmid -> set of snapshot names.
        self.snapshots: dict[int, set[str]] = {}
        #: vmid -> last rolled-back snapshot (introspection for tests).
        self.rolled_back: dict[int, str] = {}
        #: list of (vmid, command) for every guest_exec (assert the CDP launch).
        self.exec_log: list[tuple[int, list[str]]] = []
        #: VMIDs that exist (template + clones); destroyed clones are removed.
        self.existing: set[int] = set()
        #: VMIDs created via clone (so teardown can assert what was cloned).
        self.cloned: list[int] = []
        #: per-vmid guest IP override (so multiple clones get distinct IPs).
        self._ips: dict[int, str] = {}

    def register_template(self, vmid: int) -> None:
        """Register a pre-existing template/persistent VMID so it can be driven."""
        self.existing.add(vmid)
        self.status.setdefault(vmid, "stopped")
        self.snapshots.setdefault(vmid, set())

    def clone_vm(self, template_vmid: int, *, name: str, linked: bool = True) -> int:
        self.existing.add(template_vmid)
        vmid = self._next_vmid
        self._next_vmid += 1
        self.existing.add(vmid)
        self.status[vmid] = "stopped"
        self.snapshots[vmid] = set()
        self.cloned.append(vmid)
        # Distinct IP per clone so multi-session bookkeeping is observable.
        self._ips[vmid] = f"{self._guest_ip}-{vmid}"
        return vmid

    def start_vm(self, vmid: int) -> None:
        self.status[vmid] = "running"

    def stop_vm(self, vmid: int) -> None:
        self.status[vmid] = "stopped"

    def vm_status(self, vmid: int) -> str:
        return self.status.get(vmid, "stopped")

    def snapshot_create(self, vmid: int, name: str) -> None:
        self.snapshots.setdefault(vmid, set()).add(name)

    def snapshot_rollback(self, vmid: int, name: str) -> None:
        self.rolled_back[vmid] = name

    def guest_exec(self, vmid: int, command: list[str]) -> dict:
        self.exec_log.append((vmid, list(command)))
        return {"exited": 1, "exitcode": 0, "out-data": ""}

    def guest_ip(self, vmid: int) -> str:
        return self._ips.get(vmid, self._guest_ip)

    def destroy_vm(self, vmid: int) -> None:
        self.existing.discard(vmid)
        self.status.pop(vmid, None)
        self.snapshots.pop(vmid, None)
        self._ips.pop(vmid, None)


# --- REAL PVE REST client (REAL, integration-gated) -------------------------
class ProxmoxApiClient:  # pragma: no cover - integration
    """REAL Proxmox VE REST client (FR-SANDBOX-1) — # integration boundary.

    Talks to a running PVE node with an API token (``Authorization: PVEAPIToken=
    <id>=<secret>``). httpx is imported lazily so the default lane never needs the
    dependency or a reachable node; an integration-gated test (skipped without
    ``PROXMOX_API_URL``) drives it. TLS verification defaults ON; an operator with a
    self-signed PVE cert sets ``verify_tls=False``.
    """

    def __init__(
        self,
        api_url: str,
        token_id: str,
        token_secret: str,
        node: str,
        *,
        verify_tls: bool = True,
        timeout: float = 60.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._token_id = token_id
        self._token_secret = token_secret
        self._node = node
        self._verify_tls = verify_tls
        self._timeout = timeout

    def _client(self):
        import httpx

        return httpx.Client(
            base_url=f"{self._api_url}/api2/json",
            headers={"Authorization": f"PVEAPIToken={self._token_id}={self._token_secret}"},
            verify=self._verify_tls,
            timeout=self._timeout,
        )

    def _node_path(self, vmid: int) -> str:
        return f"/nodes/{self._node}/qemu/{vmid}"

    def clone_vm(self, template_vmid: int, *, name: str, linked: bool = True) -> int:
        # The caller picks a free VMID via the cluster nextid endpoint.
        with self._client() as c:
            newid = int(c.get("/cluster/nextid").json()["data"])
            c.post(
                f"{self._node_path(template_vmid)}/clone",
                data={
                    "newid": newid,
                    "name": name,
                    "full": 0 if linked else 1,
                    "target": self._node,
                },
            ).raise_for_status()
        return newid

    def start_vm(self, vmid: int) -> None:
        with self._client() as c:
            c.post(f"{self._node_path(vmid)}/status/start").raise_for_status()

    def stop_vm(self, vmid: int) -> None:
        with self._client() as c:
            c.post(f"{self._node_path(vmid)}/status/stop").raise_for_status()

    def vm_status(self, vmid: int) -> str:
        with self._client() as c:
            data = c.get(f"{self._node_path(vmid)}/status/current").json()["data"]
            return data.get("status", "unknown")

    def snapshot_create(self, vmid: int, name: str) -> None:
        with self._client() as c:
            c.post(f"{self._node_path(vmid)}/snapshot", data={"snapname": name}).raise_for_status()

    def snapshot_rollback(self, vmid: int, name: str) -> None:
        with self._client() as c:
            c.post(f"{self._node_path(vmid)}/snapshot/{name}/rollback").raise_for_status()

    def guest_exec(self, vmid: int, command: list[str]) -> dict:
        with self._client() as c:
            resp = c.post(
                f"{self._node_path(vmid)}/agent/exec",
                data={"command": command},
            )
            resp.raise_for_status()
            return resp.json().get("data", {})

    def guest_ip(self, vmid: int) -> str:
        with self._client() as c:
            data = c.get(
                f"{self._node_path(vmid)}/agent/network-get-interfaces"
            ).json()["data"]
            for iface in data.get("result", []):
                for addr in iface.get("ip-addresses", []):
                    ip = addr.get("ip-address", "")
                    if addr.get("ip-address-type") == "ipv4" and not ip.startswith("127."):
                        return ip
        raise RuntimeError(f"No IPv4 address reported by guest agent for VMID {vmid}")

    def destroy_vm(self, vmid: int) -> None:
        with self._client() as c:
            c.delete(self._node_path(vmid)).raise_for_status()
