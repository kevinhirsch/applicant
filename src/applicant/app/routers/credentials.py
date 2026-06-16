"""Credential vault router (FR-VAULT-1/2/3, NFR-PRIV-1).

Both banking modes are first-class:

* ``POST /api/credentials`` — **manual entry** in the vault UI (preferred upfront).
* ``POST /api/credentials/capture`` — the **auto-capture hook** invoked when the user
  types credentials during a human account-creation in the live session.

Secrets are sealed with libsodium at rest and are NEVER returned in plaintext from a
list endpoint (NFR-PRIV-1) — only tenant keys + the banking mode are surfaced.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured
from applicant.core.ids import CampaignId
from applicant.ports.driven.credential_store import Credential

router = APIRouter(
    prefix="/api/credentials",
    tags=["credentials"],
    dependencies=[Depends(require_llm_configured)],
)


class BankIn(BaseModel):
    campaign_id: str
    tenant_key: str
    username: str
    secret: str


class CaptureIn(BaseModel):
    campaign_id: str
    tenant_key: str
    username: str
    secret: str


@router.post("", status_code=201)
def bank_manual(body: BankIn, container: Container = Depends(get_container)) -> dict:
    """Manually bank a credential set in the vault (FR-VAULT-2, preferred upfront)."""
    container.credentials.store(
        CampaignId(body.campaign_id),
        Credential(tenant_key=body.tenant_key, username=body.username, secret=body.secret),
    )
    return {"campaign_id": body.campaign_id, "tenant_key": body.tenant_key, "source": "manual"}


@router.post("/capture", status_code=201)
def capture(body: CaptureIn, container: Container = Depends(get_container)) -> dict:
    """Auto-capture credentials entered during live account-creation (FR-VAULT-2)."""
    container.credentials.capture(
        CampaignId(body.campaign_id), body.tenant_key, body.username, body.secret
    )
    return {"campaign_id": body.campaign_id, "tenant_key": body.tenant_key, "source": "captured"}


@router.get("/{campaign_id}/tenants")
def list_tenants(campaign_id: str, container: Container = Depends(get_container)) -> dict:
    """List tenant keys with stored credentials (no secrets returned) (NFR-PRIV-1)."""
    tenants = container.credentials.list_tenants(CampaignId(campaign_id))
    return {"campaign_id": campaign_id, "tenants": tenants}
