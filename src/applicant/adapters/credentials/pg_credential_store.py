"""Encrypted credential-store adapter (FR-VAULT-1/2/3, NFR-PRIV-1).

Production ``CredentialStorePort`` adapter. Per-site/tenant credential sets are
sealed with **libsodium** (``nacl.secret.SecretBox`` = XSalsa20-Poly1305 AEAD), so
each sealed record carries an authenticated, random-nonce ciphertext that cannot be
read or forged without the master key. The master key is a strict-permission
**key-file on disk** (FR-VAULT-3): it is created ``0600`` (owner read/write only)
and read back on every restart so the service comes up unattended without
prompting. Secrets are NEVER logged — this module only logs metadata (campaign,
tenant, banking mode), and the sealed-at-rest record never contains plaintext.

The store is structured for **many credential sets** (Workday is per-tenant): rows
are keyed by ``(campaign_id, tenant_key)``. Both **banking modes** (FR-VAULT-2) are
first-class: :meth:`store` for manual vault-UI entry (preferred upfront) and
:meth:`capture` for auto-capture of credentials a human typed during live
account-creation.

Backend: the row store is in-memory here so the contract/BDD/unit lanes are fully
hermetic (real libsodium in-process, temp key-file). The seal/unseal boundary and
key-file handling are the production code path; swapping the dict for encrypted
Postgres rows (``credentials`` table) is a storage-only change — the sealed bytes
and key-file are identical.
"""

from __future__ import annotations

import base64
import os

from nacl import exceptions as nacl_exc
from nacl.secret import SecretBox

from applicant.core.ids import CampaignId
from applicant.observability.logging import get_logger
from applicant.ports.driven.credential_store import (
    MODE_CAPTURED,
    MODE_MANUAL,
    Credential,
)

log = get_logger(__name__)


def _load_or_create_master_key(keyfile: str) -> bytes:
    """Load the libsodium master key from a strict-permission key-file (FR-VAULT-3).

    Creates a fresh 32-byte (``SecretBox.KEY_SIZE``) key with ``0600`` permissions
    if absent, so the service restarts unattended without prompting. If the file
    already exists with looser permissions we tighten it back to ``0600`` (defense
    in depth) before reading.
    """
    path = keyfile
    if os.path.exists(path):
        # Tighten permissions defensively in case the file was created loosely.
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - platform/permission dependent
            pass
        with open(path, "rb") as f:
            key = f.read()
        if len(key) != SecretBox.KEY_SIZE:
            raise ValueError(
                f"master key-file {path!r} is {len(key)} bytes; "
                f"expected {SecretBox.KEY_SIZE} (corrupt or wrong file)"
            )
        return key
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    key = os.urandom(SecretBox.KEY_SIZE)
    # Write with 0600 so only the owner can read the master key (FR-VAULT-3).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


class PgCredentialStore:
    """CredentialStorePort adapter: libsodium-sealed, key-file master key.

    Storage backend is in-memory here (production swaps for encrypted Postgres
    rows); the libsodium seal/unseal and key-file handling are the real path.
    """

    def __init__(self, keyfile: str = "secrets/master.key") -> None:
        self._box = SecretBox(_load_or_create_master_key(keyfile))
        # (campaign_id, tenant_key) -> sealed record (NEVER contains plaintext).
        self._store: dict[tuple[str, str], dict[str, str]] = {}

    # --- seal / unseal (libsodium SecretBox) -----------------------------
    def _seal(self, plaintext: str) -> str:
        # SecretBox.encrypt prepends a fresh random 24-byte nonce + 16-byte MAC.
        sealed = self._box.encrypt(plaintext.encode("utf-8"))
        return base64.b64encode(bytes(sealed)).decode("ascii")

    def _unseal(self, sealed: str) -> str:
        raw = base64.b64decode(sealed)
        try:
            return self._box.decrypt(raw).decode("utf-8")
        except nacl_exc.CryptoError as exc:  # tamper / wrong key
            raise ValueError("credential record failed authentication") from exc

    # --- CredentialStorePort ---------------------------------------------
    def store(self, campaign_id: CampaignId, credential: Credential) -> None:
        """Seal and persist a credential set for a campaign/tenant (FR-VAULT-1).

        Logs ONLY metadata — never the username or secret (NFR-PRIV-1).
        """
        self._store[(str(campaign_id), credential.tenant_key)] = {
            "username": self._seal(credential.username),
            "secret": self._seal(credential.secret),
            "source": credential.source,
        }
        log.info(
            "credential_banked",
            campaign_id=str(campaign_id),
            tenant_key=credential.tenant_key,
            source=credential.source,
        )

    def capture(
        self, campaign_id: CampaignId, tenant_key: str, username: str, secret: str
    ) -> None:
        """Auto-capture credentials entered during live account-creation (FR-VAULT-2)."""
        self.store(
            campaign_id,
            Credential(
                tenant_key=tenant_key,
                username=username,
                secret=secret,
                source=MODE_CAPTURED,
            ),
        )

    def retrieve(self, campaign_id: CampaignId, tenant_key: str) -> Credential | None:
        rec = self._store.get((str(campaign_id), tenant_key))
        if rec is None:
            return None
        return Credential(
            tenant_key=tenant_key,
            username=self._unseal(rec["username"]),
            secret=self._unseal(rec["secret"]),
            source=rec.get("source", MODE_MANUAL),
        )

    def list_tenants(self, campaign_id: CampaignId) -> list[str]:
        return [t for (c, t) in self._store if c == str(campaign_id)]
