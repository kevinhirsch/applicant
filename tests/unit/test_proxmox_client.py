"""Tests for applicant.adapters.sandbox.proxmox_client."""

from __future__ import annotations

import pytest

from applicant.adapters.sandbox.proxmox_client import (
    FakeProxmoxClient,
    ProxmoxClient,
    chrome_cdp_command,
    cdp_ws_endpoint,
)


@pytest.fixture(autouse=True)
def _xdist_safe() -> None:
    """Reset module-level state for parallel xdist safety."""
    return


class TestProxmoxClientProtocol:
    """Tests for ProxmoxClient runtime_checkable protocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        assert isinstance(FakeProxmoxClient(), ProxmoxClient)


class TestFakeProxmoxClientInit:
    """Tests for FakeProxmoxClient initialisation."""

    def test_defaults(self) -> None:
        client = FakeProxmoxClient()
        assert client._next_vmid == 9000
        assert client._guest_ip == "10.0.0.50"
        assert client.status == {}
        assert client.snapshots == {}
        assert client.rolled_back == {}
        assert client.exec_log == []
        assert client.existing == set()
        assert client.cloned == []
        assert client._ips == {}

    def test_custom_base_vmid(self) -> None:
        client = FakeProxmoxClient(base_vmid=8000)
        assert client._next_vmid == 8000

    def test_custom_guest_ip(self) -> None:
        client = FakeProxmoxClient(guest_ip="192.168.1.100")
        assert client._guest_ip == "192.168.1.100"


class TestFakeProxmoxClientRegisterTemplate:
    """Tests for register_template."""

    def test_registers_in_existing(self) -> None:
        client = FakeProxmoxClient()
        client.register_template(100)
        assert 100 in client.existing

    def test_sets_default_status(self) -> None:
        client = FakeProxmoxClient()
        client.register_template(100)
        assert client.status[100] == "stopped"

    def test_initialises_snapshots_set(self) -> None:
        client = FakeProxmoxClient()
        client.register_template(100)
        assert client.snapshots[100] == set()


class TestFakeProxmoxClientCloneVm:
    """Tests for clone_vm."""

    def test_returns_next_vmid(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="clone-1")
        assert vmid == 9000

    def test_increments_vmid(self) -> None:
        client = FakeProxmoxClient()
        vmid1 = client.clone_vm(100, name="clone-1")
        vmid2 = client.clone_vm(100, name="clone-2")
        assert vmid1 == 9000
        assert vmid2 == 9001

    def test_registers_template_in_existing(self) -> None:
        client = FakeProxmoxClient()
        client.clone_vm(999, name="clone-1")
        assert 999 in client.existing

    def test_new_clone_in_existing(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="clone-1")
        assert vmid in client.existing

    def test_sets_status_to_stopped(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="clone-1")
        assert client.status[vmid] == "stopped"

    def test_initialises_snapshots(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="clone-1")
        assert client.snapshots[vmid] == set()

    def test_appends_to_cloned_list(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="clone-1")
        assert client.cloned == [vmid]

    def test_sets_distinct_ip_per_clone(self) -> None:
        client = FakeProxmoxClient()
        vmid1 = client.clone_vm(100, name="clone-1")
        vmid2 = client.clone_vm(100, name="clone-2")
        assert client._ips[vmid1] == "10.0.0.50-9000"
        assert client._ips[vmid2] == "10.0.0.50-9001"

    def test_linked_default_true(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="clone-1", linked=True)
        assert vmid == 9000


class TestFakeProxmoxClientLifecycle:
    """Tests for start_vm, stop_vm, vm_status lifecycle."""

    @pytest.fixture(autouse=True)
    def _clone_and_start(self) -> None:
        self.client = FakeProxmoxClient()
        self.vmid = self.client.clone_vm(100, name="test-vm")

    def test_start_vm_sets_running(self) -> None:
        self.client.start_vm(self.vmid)
        assert self.client.status[self.vmid] == "running"

    def test_vm_status_running(self) -> None:
        self.client.start_vm(self.vmid)
        assert self.client.vm_status(self.vmid) == "running"

    def test_start_then_stop_sets_stopped(self) -> None:
        self.client.start_vm(self.vmid)
        self.client.stop_vm(self.vmid)
        assert self.client.status[self.vmid] == "stopped"

    def test_vm_status_stopped(self) -> None:
        assert self.client.vm_status(self.vmid) == "stopped"

    def test_vm_status_unknown_vmid(self) -> None:
        assert self.client.vm_status(99999) == "stopped"


class TestFakeProxmoxClientSnapshots:
    """Tests for snapshot_create and snapshot_rollback."""

    @pytest.fixture(autouse=True)
    def _clone(self) -> None:
        self.client = FakeProxmoxClient()
        self.vmid = self.client.clone_vm(100, name="test-vm")

    def test_snapshot_create_adds_name(self) -> None:
        self.client.snapshot_create(self.vmid, "clean")
        assert "clean" in self.client.snapshots[self.vmid]

    def test_snapshot_create_multiple(self) -> None:
        self.client.snapshot_create(self.vmid, "snap-1")
        self.client.snapshot_create(self.vmid, "snap-2")
        assert self.client.snapshots[self.vmid] == {"snap-1", "snap-2"}

    def test_snapshot_create_adds_to_new_vmid(self) -> None:
        new_vmid = self.client.clone_vm(100, name="other-vm")
        self.client.snapshot_create(new_vmid, "init")
        assert self.client.snapshots[new_vmid] == {"init"}

    def test_snapshot_rollback_records(self) -> None:
        self.client.snapshot_rollback(self.vmid, "clean")
        assert self.client.rolled_back[self.vmid] == "clean"

    def test_snapshot_rollback_overwrites(self) -> None:
        self.client.snapshot_rollback(self.vmid, "clean")
        self.client.snapshot_rollback(self.vmid, "baseline")
        assert self.client.rolled_back[self.vmid] == "baseline"


class TestFakeProxmoxClientGuestExec:
    """Tests for guest_exec."""

    @pytest.fixture(autouse=True)
    def _clone(self) -> None:
        self.client = FakeProxmoxClient()
        self.vmid = self.client.clone_vm(100, name="test-vm")

    def test_records_in_exec_log(self) -> None:
        cmd = ["chrome.exe", "--version"]
        self.client.guest_exec(self.vmid, cmd)
        assert len(self.client.exec_log) == 1
        assert self.client.exec_log[0] == (self.vmid, cmd)

    def test_records_multiple_commands(self) -> None:
        cmd1 = ["chrome.exe", "--version"]
        cmd2 = ["echo", "hello"]
        self.client.guest_exec(self.vmid, cmd1)
        self.client.guest_exec(self.vmid, cmd2)
        assert len(self.client.exec_log) == 2

    def test_returns_dict(self) -> None:
        result = self.client.guest_exec(self.vmid, ["cmd.exe"])
        assert isinstance(result, dict)
        assert result["exited"] == 1
        assert result["exitcode"] == 0
        assert result["out-data"] == ""



class TestFakeProxmoxClientGuestIp:
    """Tests for guest_ip."""

    def test_returns_default_ip(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="test-vm")
        assert client.guest_ip(vmid) == "10.0.0.50-9000"

    def test_returns_default_guest_ip_for_unknown_vmid(self) -> None:
        client = FakeProxmoxClient()
        assert client.guest_ip(99999) == "10.0.0.50"

    def test_returns_distinct_ip_per_clone(self) -> None:
        client = FakeProxmoxClient()
        vmid1 = client.clone_vm(100, name="vm-1")
        vmid2 = client.clone_vm(100, name="vm-2")
        assert client.guest_ip(vmid1) == "10.0.0.50-9000"
        assert client.guest_ip(vmid2) == "10.0.0.50-9001"

    def test_custom_guest_ip_used_as_prefix(self) -> None:
        client = FakeProxmoxClient(guest_ip="192.168.1.100")
        vmid = client.clone_vm(100, name="test-vm")
        assert client.guest_ip(vmid) == "192.168.1.100-9000"


class TestFakeProxmoxClientDestroyVm:
    """Tests for destroy_vm."""

    def test_removes_from_existing(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="test-vm")
        client.destroy_vm(vmid)
        assert vmid not in client.existing

    def test_removes_status(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="test-vm")
        client.destroy_vm(vmid)
        assert vmid not in client.status

    def test_removes_snapshots(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="test-vm")
        client.destroy_vm(vmid)
        assert vmid not in client.snapshots

    def test_removes_ip(self) -> None:
        client = FakeProxmoxClient()
        vmid = client.clone_vm(100, name="test-vm")
        client.destroy_vm(vmid)
        assert vmid not in client._ips

    def test_destroy_unknown_vmid_is_noop(self) -> None:
        client = FakeProxmoxClient()
        client.destroy_vm(99999)
        assert client.existing == set()


class TestChromeCdpCommand:
    """Tests for chrome_cdp_command."""

    def test_returns_list_of_strings(self) -> None:
        result = chrome_cdp_command(port=9222)
        assert isinstance(result, list)
        assert all(isinstance(item, str) for item in result)

    def test_includes_chrome_exe_path(self) -> None:
        result = chrome_cdp_command(port=9222)
        assert "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" in result

    def test_port_substitution(self) -> None:
        result = chrome_cdp_command(port=9222)
        assert "--remote-debugging-port=9222" in result

    def test_default_address_zero(self) -> None:
        result = chrome_cdp_command(port=9222)
        assert "--remote-debugging-address=0.0.0.0" in result

    def test_custom_address_substitution(self) -> None:
        result = chrome_cdp_command(port=9222, address="10.0.0.50")
        assert "--remote-debugging-address=10.0.0.50" in result

    def test_user_data_dir_flag(self) -> None:
        result = chrome_cdp_command(port=9222)
        assert any("user-data-dir" in item for item in result)

    def test_no_first_run_flag(self) -> None:
        result = chrome_cdp_command(port=9222)
        assert "--no-first-run" in result

    def test_no_default_browser_check_flag(self) -> None:
        result = chrome_cdp_command(port=9222)
        assert "--no-default-browser-check" in result

    def test_has_expected_length(self) -> None:
        result = chrome_cdp_command(port=9222)
        assert len(result) == 6


class TestCdpWsEndpoint:
    """Tests for cdp_ws_endpoint."""

    def test_returns_http_url(self) -> None:
        result = cdp_ws_endpoint("10.0.0.50", 9222)
        assert result == "http://10.0.0.50:9222"

    def test_different_host(self) -> None:
        result = cdp_ws_endpoint("192.168.1.100", 9222)
        assert result == "http://192.168.1.100:9222"

    def test_different_port(self) -> None:
        result = cdp_ws_endpoint("10.0.0.50", 9333)
        assert result == "http://10.0.0.50:9333"

    def test_ipv6_host(self) -> None:
        result = cdp_ws_endpoint("::1", 9222)
        assert result == "http://::1:9222"

    def test_hostname_host(self) -> None:
        result = cdp_ws_endpoint("pve-node.local", 9222)
        assert result == "http://pve-node.local:9222"

