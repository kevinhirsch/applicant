"""Encrypted credential-store adapter (FR-VAULT-1/2/3, FR-CRIT-4, NFR-PRIV-1).

Production ``CredentialStorePort`` adapter. Per-site/tenant credential sets are
sealed with **libsodium** (``nacl.secret.SecretBox`` = XSalsa20-Poly1305 AEAD), so
each sealed record carries an authenticated, random-nonce ciphertext that cannot be
read or forged without the master key. The master key is a strict-permission
**key-file on disk** (FR-VAULT-3): it is created ``0600`` (owner read/write only)
and read back on every restart so the service comes up unattended without
prompting. Secrets are NEVER logged — this module only logs metadata (campaign,
tenant, banking mode), and the sealed-at-rest record never contains plaintext.

The store is structured for **many credential sets** (Workday is per-tenant) and is
**campaign-scoped** (FR-CRIT-4): rows are keyed by ``(campaign_id, tenant_key)``.
Both **banking modes** (FR-VAULT-2) are first-class: :meth:`store` for manual
vault-UI entry (preferred upfront) and :meth:`capture` for auto-capture of
credentials a human typed during live account-creation.

Two backends share the identical seal/unseal + key-file path:

* :class:`PgCredentialStore` — persists sealed records to Postgres via the storage
  session (the ``credentials`` table), so banked credentials survive restarts
  (FR-VAULT-3 24/7). Selected by ``container.py`` when a real DB is configured.
* :class:`InMemoryCredentialStore` — a dict-backed fallback so the hermetic test
  lane and the no-DB boot path still work without a Postgres.

``PgCredentialStore`` keeps its historic name + the in-memory ``_store`` attribute
as a transparent write-through cache so the existing contract/keyfile tests (which
introspect ``_store``) continue to pass; the cache is hydrated from the DB on
read-misses so a *fresh instance* (a "restart") unseals persisted rows.
"""

from __future__ import annotations

import base64
import os

from nacl import exceptions as nacl_exc
from nacl.secret import SecretBox

from applicant.core.errors import CredentialDecryptError
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
    # Create the containing dir 0700 (owner-only) so the master key can never be read
    # by another user even transiently. On a persisted volume this is the directory
    # that survives container recreation (FR-VAULT-3); tighten it if it pre-exists.
    keydir = os.path.dirname(path) or "."
    os.makedirs(keydir, mode=0o700, exist_ok=True)
    try:
        os.chmod(keydir, 0o700)
    except OSError:  # pragma: no cover - platform/permission dependent
        pass
    key = os.urandom(SecretBox.KEY_SIZE)
    _write_master_key(path, key)
    return key


def _write_master_key(keyfile: str, key: bytes) -> None:
    """Write a master key to ``keyfile`` with strict ``0600`` perms (FR-VAULT-3).

    Shared by initial key creation and master-key rotation (issue #361): a rotated
    key MUST land with the same owner-only permissions as a freshly minted one, with
    its containing dir created ``0700`` if absent.
    """
    if len(key) != SecretBox.KEY_SIZE:
        raise ValueError(
            f"master key is {len(key)} bytes; expected {SecretBox.KEY_SIZE}"
        )
    keydir = os.path.dirname(keyfile) or "."
    os.makedirs(keydir, mode=0o700, exist_ok=True)
    try:
        os.chmod(keydir, 0o700)
    except OSError:  # pragma: no cover - platform/permission dependent
        pass
    # Write with 0600 so only the owner can read the master key (FR-VAULT-3).
    fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)


class _SealingMixin:
    """Shared libsodium seal/unseal + key-file handling (the real crypto path)."""

    _box: SecretBox
    _keyfile: str

    def _init_box(self, keyfile: str) -> None:
        self._keyfile = keyfile
        self._box = SecretBox(_load_or_create_master_key(keyfile))

    # --- seal / unseal (libsodium SecretBox) -----------------------------
    def _seal(self, plaintext: str) -> str:
        # SecretBox.encrypt prepends a fresh random 24-byte nonce + 16-byte MAC.
        sealed = self._box.encrypt(plaintext.encode("utf-8"))
        return base64.b64encode(bytes(sealed)).decode("ascii")

    def _unseal(self, sealed: str, *, box: SecretBox | None = None) -> str:
        raw = base64.b64decode(sealed)
        try:
            return (box or self._box).decrypt(raw).decode("utf-8")
        except nacl_exc.CryptoError as exc:  # tamper / wrong key (#361)
            # A DISTINCT, contained decrypt-failure — NEVER a silent empty credential.
            # Subclasses ValueError so the historic ``pytest.raises(ValueError)`` and
            # callers catching ValueError keep working; new callers can catch the
            # distinct type to surface a key-loss alert (FR-VAULT-3, NFR-PRIV-1).
            raise CredentialDecryptError(
                "credential record failed authentication"
            ) from exc

    # --- master-key rotation (#361, FR-VAULT-3) --------------------------
    def _reseal_all(self, new_box: SecretBox) -> None:
        """Re-encrypt every cached sealed record under ``new_box``.

        Each record's username/secret are unsealed with the CURRENT box and re-sealed
        with the new one, so the new key decrypts and the old key no longer does. The
        in-memory ``_store`` cache is the source of truth for what to re-seal; the
        persistent backends override :meth:`rotate_master_key` to hydrate the full row
        set first and persist the re-sealed rows.
        """
        store: dict = getattr(self, "_store", {})
        rotated: dict = {}
        for key, rec in store.items():
            rotated[key] = {
                "username": base64.b64encode(
                    bytes(new_box.encrypt(self._unseal(rec["username"]).encode("utf-8")))
                ).decode("ascii"),
                "secret": base64.b64encode(
                    bytes(new_box.encrypt(self._unseal(rec["secret"]).encode("utf-8")))
                ).decode("ascii"),
                "source": rec.get("source", MODE_MANUAL),
            }
        store.clear()
        store.update(rotated)

    def __repr__(self) -> str:  # never leak sealed/plaintext material in a repr
        return f"<{type(self).__name__} (sealed credential store)>"


class InMemoryCredentialStore(_SealingMixin):
    """No-DB fallback CredentialStorePort: libsodium-sealed records in a dict.

    Used by the hermetic test lane and the container's no-DB boot path. Records are
    sealed exactly as in the Postgres backend; only the row store differs.
    """

    def __init__(self, keyfile: str = "secrets/master.key") -> None:
        self._init_box(keyfile)
        # (campaign_id, tenant_key) -> sealed record (NEVER contains plaintext).
        self._store: dict[tuple[str, str], dict[str, str]] = {}

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

    def delete(self, campaign_id: CampaignId, tenant_key: str) -> bool:
        """Erase a single sealed credential set (#363). True if one was removed."""
        return self._store.pop((str(campaign_id), tenant_key), None) is not None

    def delete_campaign(self, campaign_id: CampaignId) -> int:
        """Erase ALL sealed credentials for a campaign (#363). Returns the count.

        Part of the campaign-delete purge cascade — banked credentials must be
        verifiably absent after a campaign is deleted (FR-CRIT-4, NFR-PRIV-1).
        """
        keys = [k for k in self._store if k[0] == str(campaign_id)]
        for k in keys:
            del self._store[k]
        if keys:
            log.info(
                "credentials_purged", campaign_id=str(campaign_id), count=len(keys)
            )
        return len(keys)

    def rotate_master_key(self, new_keyfile: str) -> int:
        """Rotate the master key: re-encrypt every secret under a NEW key (#361).

        Writes a fresh 32-byte key to ``new_keyfile`` (``0600``), re-seals every cached
        record under it, and swaps the live box. Afterwards the new key decrypts and the
        old key no longer does (FR-VAULT-3). Returns the number of records re-sealed.
        """
        new_key = os.urandom(SecretBox.KEY_SIZE)
        new_box = SecretBox(new_key)
        self._reseal_all(new_box)
        _write_master_key(new_keyfile, new_key)
        self._box = new_box
        self._keyfile = new_keyfile
        log.info("vault_master_key_rotated", records=len(self._store))
        return len(self._store)


class PgCredentialStore(_SealingMixin):
    """CredentialStorePort adapter: libsodium-sealed records persisted to Postgres.

    Sealed records are written to / read from the ``credentials`` table via the
    storage session (``session_factory``). Survives restarts (FR-VAULT-3): a fresh
    instance reads the persisted rows and unseals them with the same key-file.

    A write-through ``_store`` dict mirrors the historic in-memory shape (the
    contract/keyfile tests introspect it) and serves as a cache; it is hydrated from
    the DB on read-misses so persistence is transparent. When no ``session_factory``
    is supplied the store behaves like the in-memory fallback (the no-DB path), which
    is what the default conftest fixture exercises.
    """

    def __init__(
        self,
        keyfile: str = "secrets/master.key",
        *,
        session_factory=None,
    ) -> None:
        self._init_box(keyfile)
        self._session_factory = session_factory
        # (campaign_id, tenant_key) -> sealed record (NEVER contains plaintext).
        self._store: dict[tuple[str, str], dict[str, str]] = {}

    # --- DB access (None when no session_factory wired = in-memory path) ---
    def _persist_row(
        self, campaign_id: str, tenant_key: str, rec: dict[str, str]
    ) -> None:
        if self._session_factory is None:
            return
        from applicant.adapters.storage.models import CredentialModel
        from applicant.core.ids import new_id

        session = self._session_factory()
        try:
            existing = (
                session.query(CredentialModel)
                .filter(
                    CredentialModel.campaign_id == campaign_id,
                    CredentialModel.tenant_key == tenant_key,
                )
                .one_or_none()
            )
            if existing is None:
                session.add(
                    CredentialModel(
                        id=new_id(),
                        campaign_id=campaign_id,
                        tenant_key=tenant_key,
                        sealed_username=rec["username"],
                        sealed_secret=rec["secret"],
                        source=rec.get("source", MODE_MANUAL),
                    )
                )
            else:
                existing.sealed_username = rec["username"]
                existing.sealed_secret = rec["secret"]
                existing.source = rec.get("source", MODE_MANUAL)
            session.commit()
        finally:
            session.close()

    def _load_row(self, campaign_id: str, tenant_key: str) -> dict[str, str] | None:
        if self._session_factory is None:
            return None
        from applicant.adapters.storage.models import CredentialModel

        session = self._session_factory()
        try:
            row = (
                session.query(CredentialModel)
                .filter(
                    CredentialModel.campaign_id == campaign_id,
                    CredentialModel.tenant_key == tenant_key,
                )
                .one_or_none()
            )
            if row is None:
                return None
            return {
                "username": row.sealed_username,
                "secret": row.sealed_secret,
                "source": row.source,
            }
        finally:
            session.close()

    def _load_tenants(self, campaign_id: str) -> list[str]:
        if self._session_factory is None:
            return []
        from applicant.adapters.storage.models import CredentialModel

        session = self._session_factory()
        try:
            rows = (
                session.query(CredentialModel.tenant_key)
                .filter(CredentialModel.campaign_id == campaign_id)
                .all()
            )
            return [r[0] for r in rows]
        finally:
            session.close()

    def _delete_campaign_rows(self, campaign_id: str) -> int:
        if self._session_factory is None:
            return 0
        from applicant.adapters.storage.models import CredentialModel

        session = self._session_factory()
        try:
            n = (
                session.query(CredentialModel)
                .filter(CredentialModel.campaign_id == campaign_id)
                .delete(synchronize_session=False)
            )
            session.commit()
            return int(n or 0)
        finally:
            session.close()

    def _delete_row(self, campaign_id: str, tenant_key: str) -> int:
        if self._session_factory is None:
            return 0
        from applicant.adapters.storage.models import CredentialModel

        session = self._session_factory()
        try:
            n = (
                session.query(CredentialModel)
                .filter(
                    CredentialModel.campaign_id == campaign_id,
                    CredentialModel.tenant_key == tenant_key,
                )
                .delete(synchronize_session=False)
            )
            session.commit()
            return int(n or 0)
        finally:
            session.close()

    def _hydrate_all_rows(self) -> None:
        """Load EVERY persisted sealed row into the cache (rotation must touch all)."""
        if self._session_factory is None:
            return
        from applicant.adapters.storage.models import CredentialModel

        session = self._session_factory()
        try:
            for row in session.query(CredentialModel).all():
                self._store[(row.campaign_id, row.tenant_key)] = {
                    "username": row.sealed_username,
                    "secret": row.sealed_secret,
                    "source": row.source,
                }
        finally:
            session.close()

    # --- CredentialStorePort ---------------------------------------------
    def store(self, campaign_id: CampaignId, credential: Credential) -> None:
        """Seal and persist a credential set for a campaign/tenant (FR-VAULT-1).

        Persists the SEALED record to Postgres (when a session is wired) so it
        survives restarts; logs ONLY metadata — never the username/secret (NFR-PRIV-1).
        """
        rec = {
            "username": self._seal(credential.username),
            "secret": self._seal(credential.secret),
            "source": credential.source,
        }
        self._store[(str(campaign_id), credential.tenant_key)] = rec
        self._persist_row(str(campaign_id), credential.tenant_key, rec)
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
        key = (str(campaign_id), tenant_key)
        rec = self._store.get(key)
        if rec is None:
            # Cache miss: hydrate from the persisted row (survives restart, FR-VAULT-3).
            rec = self._load_row(str(campaign_id), tenant_key)
            if rec is None:
                return None
            self._store[key] = rec
        return Credential(
            tenant_key=tenant_key,
            username=self._unseal(rec["username"]),
            secret=self._unseal(rec["secret"]),
            source=rec.get("source", MODE_MANUAL),
        )

    def list_tenants(self, campaign_id: CampaignId) -> list[str]:
        cached = {t for (c, t) in self._store if c == str(campaign_id)}
        cached.update(self._load_tenants(str(campaign_id)))
        return sorted(cached)

    def delete(self, campaign_id: CampaignId, tenant_key: str) -> bool:
        """Erase a single sealed credential set, cache + DB (#363)."""
        in_cache = self._store.pop((str(campaign_id), tenant_key), None) is not None
        in_db = self._delete_row(str(campaign_id), tenant_key) > 0
        return in_cache or in_db

    def delete_campaign(self, campaign_id: CampaignId) -> int:
        """Erase ALL sealed credentials for a campaign, cache + DB (#363).

        Part of the campaign-delete purge cascade — banked credentials must be
        verifiably absent afterwards (FR-CRIT-4, NFR-PRIV-1).
        """
        cache_keys = [k for k in self._store if k[0] == str(campaign_id)]
        for k in cache_keys:
            del self._store[k]
        n_db = self._delete_campaign_rows(str(campaign_id))
        n = max(len(cache_keys), n_db)
        if n:
            log.info("credentials_purged", campaign_id=str(campaign_id), count=n)
        return n

    def rotate_master_key(self, new_keyfile: str) -> int:
        """Rotate the master key: re-encrypt every secret under a NEW key (#361).

        Hydrates the FULL persisted row set (so a fresh instance rotates everything,
        not just what happens to be cached), re-seals every record under a fresh key
        written to ``new_keyfile`` (``0600``), persists the re-sealed rows, and swaps the
        live box. Afterwards the new key decrypts and the old key no longer does
        (FR-VAULT-3). Returns the number of records re-sealed.
        """
        self._hydrate_all_rows()
        new_key = os.urandom(SecretBox.KEY_SIZE)
        new_box = SecretBox(new_key)
        self._reseal_all(new_box)
        _write_master_key(new_keyfile, new_key)
        self._box = new_box
        self._keyfile = new_keyfile
        # Persist the re-sealed rows so the rotation survives a restart.
        for (cid, tenant), rec in self._store.items():
            self._persist_row(cid, tenant, rec)
        log.info("vault_master_key_rotated", records=len(self._store))
        return len(self._store)
