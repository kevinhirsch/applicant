"""Encrypted credential-store adapter (FR-VAULT-1/2/3, NFR-PRIV-1).

# STAGE B — owned by Phase 0 (real-ish); flesh out here (libsodium + Postgres).

This is a *real-ish* in-memory implementation: it actually seals/unseals secrets
with a symmetric XOR-keystream placeholder standing in for libsodium's
``crypto_secretbox`` so the data flow (seal on store, unseal on retrieve, master
key from a strict-permission key-file) is exercised end-to-end and contract-tested
today. Phase 0/2 swaps the cipher for libsodium and the dict for Postgres rows.

SECURITY NOTE: the placeholder cipher is NOT secure — it exists only to model the
seal/unseal boundary. Do not ship it as the production cipher.
"""

from __future__ import annotations

import base64
import hashlib
import os

from applicant.core.ids import CampaignId
from applicant.ports.driven.credential_store import Credential


def _load_or_create_master_key(keyfile: str) -> bytes:
    """Load the master key from a strict-permission key-file, creating it if absent.

    FR-VAULT-3: the master key is a strict-permission key-file on disk so the
    service restarts unattended without prompting.
    """
    path = keyfile
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    key = os.urandom(32)
    # Write with 0600 so only the owner can read the master key.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def _keystream(master: bytes, nonce: bytes, length: int) -> bytes:
    """Derive a pseudo-random keystream (placeholder for libsodium secretbox)."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(master + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


class PgCredentialStore:
    """CredentialStorePort adapter: seals secrets with a master key-file.

    Storage backend is in-memory here (Phase 2 replaces with encrypted Postgres
    rows); the seal/unseal boundary and key-file handling are real.
    """

    def __init__(self, keyfile: str = "secrets/master.key") -> None:
        self._master = _load_or_create_master_key(keyfile)
        # (campaign_id, tenant_key) -> sealed record
        self._store: dict[tuple[str, str], dict[str, str]] = {}

    def _seal(self, plaintext: str) -> str:
        nonce = os.urandom(16)
        data = plaintext.encode("utf-8")
        ct = bytes(b ^ k for b, k in zip(data, _keystream(self._master, nonce, len(data)), strict=False))
        return base64.b64encode(nonce + ct).decode("ascii")

    def _unseal(self, sealed: str) -> str:
        raw = base64.b64decode(sealed)
        nonce, ct = raw[:16], raw[16:]
        data = bytes(b ^ k for b, k in zip(ct, _keystream(self._master, nonce, len(ct)), strict=False))
        return data.decode("utf-8")

    def store(self, campaign_id: CampaignId, credential: Credential) -> None:
        self._store[(str(campaign_id), credential.tenant_key)] = {
            "username": self._seal(credential.username),
            "secret": self._seal(credential.secret),
        }

    def retrieve(self, campaign_id: CampaignId, tenant_key: str) -> Credential | None:
        rec = self._store.get((str(campaign_id), tenant_key))
        if rec is None:
            return None
        return Credential(
            tenant_key=tenant_key,
            username=self._unseal(rec["username"]),
            secret=self._unseal(rec["secret"]),
        )

    def list_tenants(self, campaign_id: CampaignId) -> list[str]:
        return [t for (c, t) in self._store if c == str(campaign_id)]
