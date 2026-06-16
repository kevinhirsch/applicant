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


@dataclass(frozen=True)
class Credential:
    """A decrypted credential set (handle with care; never log)."""

    tenant_key: str  # e.g. workday tenant subdomain
    username: str
    secret: str


@runtime_checkable
class CredentialStorePort(Protocol):
    """Outbound port for sealed credential storage."""

    def store(self, campaign_id: CampaignId, credential: Credential) -> None:
        """Seal and persist a credential set for a campaign/tenant (FR-VAULT-1)."""
        ...

    def retrieve(self, campaign_id: CampaignId, tenant_key: str) -> Credential | None:
        """Unseal and return a credential set, or ``None`` if absent."""
        ...

    def list_tenants(self, campaign_id: CampaignId) -> list[str]:
        """List tenant keys with stored credentials for a campaign."""
        ...
