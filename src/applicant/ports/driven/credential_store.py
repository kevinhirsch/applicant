"""CredentialStore port (FR-VAULT-1/2/3, NFR-PRIV-1).

Encrypted credential storage (libsodium-sealed in Postgres by default;
Vaultwarden later). Per-site/tenant credential sets (Workday is per-tenant).
The master key is a strict-permission key-file on disk (FR-VAULT-3); secrets are
never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from applicant.core.ids import CampaignId

#: How a credential set arrived in the vault (FR-VAULT-2, both banking modes).
MODE_MANUAL = "manual"  # entered by the user in the vault UI (preferred upfront)
MODE_CAPTURED = "captured"  # auto-captured from a human account-creation in the live session


@dataclass(frozen=True)
class Credential:
    """A decrypted credential set (handle with care; never log).

    ``source`` records *which* banking mode produced the set (FR-VAULT-2) so the
    UI can distinguish manually-entered from auto-captured credentials.
    """

    tenant_key: str  # e.g. workday tenant subdomain
    username: str
    secret: str
    source: str = MODE_MANUAL

    def __repr__(self) -> str:
        """Redacted repr so the secret (and username) never leak via str/log/traceback.

        The default dataclass repr would render ``secret=`` (and ``username=``) in
        plaintext; if a ``Credential`` is ever interpolated into an exception or a
        free-text log line that the structlog value-redactor cannot pattern-match
        (e.g. a short/low-entropy secret), the plaintext would leak (NFR-PRIV-1,
        FR-VAULT-3). Only the non-sensitive ``tenant_key`` + ``source`` are shown.
        """
        return f"Credential(tenant_key={self.tenant_key!r}, source={self.source!r})"


@runtime_checkable
class CredentialStorePort(Protocol):
    """Outbound port for sealed credential storage."""

    def store(self, campaign_id: CampaignId, credential: Credential) -> None:
        """Seal and persist a credential set for a campaign/tenant (FR-VAULT-1)."""
        ...

    def capture(
        self, campaign_id: CampaignId, tenant_key: str, username: str, secret: str
    ) -> None:
        """Auto-capture credentials entered during live account-creation (FR-VAULT-2).

        A convenience over :meth:`store` that tags the set ``source=captured`` so the
        second banking mode is a first-class, contract-tested path.
        """
        ...

    def retrieve(self, campaign_id: CampaignId, tenant_key: str) -> Credential | None:
        """Unseal and return a credential set, or ``None`` if absent."""
        ...

    def list_tenants(self, campaign_id: CampaignId) -> list[str]:
        """List tenant keys with stored credentials for a campaign."""
        ...
