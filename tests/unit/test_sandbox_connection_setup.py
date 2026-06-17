"""OOBE sandbox-connection step: collects connection/login data, vaults secrets,
and gates the native proxmox-windows backend (FR-OOBE, FR-VAULT-3, FR-SANDBOX-1)."""

from __future__ import annotations

import pytest

from applicant.adapters.credentials.pg_credential_store import InMemoryCredentialStore
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.setup_service import (
    _SANDBOX_RDP_REF,
    _SANDBOX_TOKEN_REF,
    SetupService,
)
from applicant.ports.driving.setup_wizard import SandboxConnectionSettings, WizardStep


def _conn(**over):
    base = dict(
        proxmox_api_url="https://pve.local:8006",
        proxmox_node="pve1",
        proxmox_token_id="root@pam!applicant",
        proxmox_token_secret="super-secret-token",
        template_vmid=9000,
        clone_mode="snapshot-revert",
        cdp_port=9222,
        rdp_username="Applicant",
        rdp_password="hunter2",
        takeover_method="rdp",
    )
    base.update(over)
    return SandboxConnectionSettings(**base)


@pytest.mark.unit
class TestSandboxConnectionStep:
    def _svc(self, *, backend="proxmox-windows", tmp_path=None):
        keyfile = str(tmp_path / "master.key") if tmp_path else "secrets/master.key"
        creds = InMemoryCredentialStore(keyfile)
        return SetupService(
            llm_configured=True,
            config_store=InMemoryAppConfigStore(),
            credentials=creds,
            sandbox_backend=backend,
        ), creds

    def test_proxmox_backend_gates_until_configured(self, tmp_path):
        svc, _ = self._svc(tmp_path=tmp_path)
        assert svc.sandbox_connection_configured() is False
        assert svc.is_sandbox_backend_ready() is False
        # The sandbox step is not complete -> automated work would be blocked.
        assert WizardStep.SANDBOX.value not in svc.status().steps_complete

    def test_local_backend_never_gated_by_sandbox_step(self, tmp_path):
        svc, _ = self._svc(backend="local", tmp_path=tmp_path)
        # Local backend: the sandbox step is implicitly satisfied (does not apply).
        assert svc.is_sandbox_backend_ready() is True
        assert WizardStep.SANDBOX.value in svc.status().steps_complete

    def test_sandbox_backend_property_surfaced(self, tmp_path):
        # The selected backend is exposed so the front-door wizard can show the
        # right affordance (built-in vs native Windows VM).
        local, _ = self._svc(backend="local", tmp_path=tmp_path)
        win, _ = self._svc(backend="proxmox-windows", tmp_path=tmp_path)
        assert local.sandbox_backend == "local"
        assert win.sandbox_backend == "proxmox-windows"

    def test_configure_collects_and_ungates(self, tmp_path):
        svc, _ = self._svc(tmp_path=tmp_path)
        svc.configure_sandbox_connection(_conn())
        assert svc.sandbox_connection_configured() is True
        assert svc.is_sandbox_backend_ready() is True
        assert WizardStep.SANDBOX.value in svc.status().steps_complete

    def test_secrets_vaulted_not_in_config(self, tmp_path):
        svc, creds = self._svc(tmp_path=tmp_path)
        svc.configure_sandbox_connection(_conn())
        # Non-secret view NEVER contains the token secret or RDP password.
        view = svc.get_sandbox_connection()
        assert view["proxmox_node"] == "pve1"
        assert "token_secret" not in view
        assert "rdp_password" not in view
        assert "token_secret_ref" not in view
        # The secrets are sealed in the vault and resolvable only internally.
        from applicant.core.ids import CampaignId

        tok = creds.retrieve(CampaignId("__system__"), _SANDBOX_TOKEN_REF)
        rdp = creds.retrieve(CampaignId("__system__"), _SANDBOX_RDP_REF)
        assert tok is not None and tok.secret == "super-secret-token"
        assert rdp is not None and rdp.secret == "hunter2"
        assert svc.resolve_sandbox_secret("token") == "super-secret-token"
        assert svc.resolve_sandbox_secret("rdp") == "hunter2"

    def test_missing_required_fields_rejected(self, tmp_path):
        svc, _ = self._svc(tmp_path=tmp_path)
        with pytest.raises(ValueError):
            svc.configure_sandbox_connection(_conn(proxmox_api_url=""))
        with pytest.raises(ValueError):
            svc.configure_sandbox_connection(_conn(template_vmid=0))
        with pytest.raises(ValueError):
            svc.configure_sandbox_connection(_conn(proxmox_token_secret=""))

    def test_advance_sandbox_step_requires_config(self, tmp_path):
        svc, _ = self._svc(tmp_path=tmp_path)
        with pytest.raises(ValueError):
            svc.advance_step(WizardStep.SANDBOX)
        svc.configure_sandbox_connection(_conn())
        svc.advance_step(WizardStep.SANDBOX)  # now allowed
