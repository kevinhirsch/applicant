"""Credential-store contract against the PgCredentialStore adapter."""

from __future__ import annotations

import os
import stat

import pytest

from applicant.adapters.credentials.pg_credential_store import PgCredentialStore
from applicant.core.ids import CampaignId, new_id
from applicant.ports.driven.credential_store import Credential
from tests.contract.base import CredentialStorePortContract


@pytest.mark.contract
class TestPgCredentialStoreContract(CredentialStorePortContract):
    @pytest.fixture
    def adapter(self, tmp_path):
        return PgCredentialStore(str(tmp_path / "master.key"))


@pytest.mark.contract
class TestPgCredentialStoreKeyfile:
    """FR-VAULT-3: strict-permission key-file, clean unattended restart."""

    def test_keyfile_created_0600(self, tmp_path):
        keyfile = tmp_path / "master.key"
        PgCredentialStore(str(keyfile))
        mode = stat.S_IMODE(os.stat(keyfile).st_mode)
        assert mode == 0o600  # owner read/write only

    def test_restart_reuses_keyfile_and_decrypts(self, tmp_path):
        # A second instance on the SAME key-file must unseal records sealed by the
        # first (the master key is loaded from disk, not regenerated).
        keyfile = str(tmp_path / "master.key")
        cid = CampaignId(new_id())
        first = PgCredentialStore(keyfile)
        first.store(cid, Credential(tenant_key="acme.workday", username="kev", secret="s3cret"))
        sealed = dict(first._store)  # simulate persisted rows surviving a restart

        second = PgCredentialStore(keyfile)
        second._store = sealed
        got = second.retrieve(cid, "acme.workday")
        assert got is not None and got.secret == "s3cret"

    def test_libsodium_seal_is_authenticated(self, tmp_path):
        # XSalsa20-Poly1305: a tampered ciphertext fails authentication on unseal.
        store = PgCredentialStore(str(tmp_path / "master.key"))
        sealed = store._seal("plaintext")
        tampered = sealed[:-4] + ("AAAA" if sealed[-4:] != "AAAA" else "BBBB")
        with pytest.raises(ValueError):
            store._unseal(tampered)
