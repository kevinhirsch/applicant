"""Credential-store contract against the PgCredentialStore adapter."""

from __future__ import annotations

import pytest

from applicant.adapters.credentials.pg_credential_store import PgCredentialStore
from tests.contract.base import CredentialStorePortContract


@pytest.mark.contract
class TestPgCredentialStoreContract(CredentialStorePortContract):
    @pytest.fixture
    def adapter(self, tmp_path):
        return PgCredentialStore(str(tmp_path / "master.key"))
