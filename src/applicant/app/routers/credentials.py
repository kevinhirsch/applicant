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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured
from applicant.application.services.prefill_service import (
    GOOGLE_CREDENTIAL_KEY,
    PREDEFINED_CREDENTIAL_KEY,
)
from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId
from applicant.ports.driven.credential_store import Credential

router = APIRouter(
    prefix="/api/credentials",
    tags=["credentials"],
    dependencies=[Depends(require_llm_configured)],
)

#: The two account-level credential kinds the user sets once in Settings and that
#: apply to every job search (stored under the global SYSTEM campaign): their Google
#: sign-in (for "Sign in with Google" gates) and the default set used to create a
#: brand-new account when a site requires one (ADR-0004).
_ACCOUNT_KEYS = (GOOGLE_CREDENTIAL_KEY, PREDEFINED_CREDENTIAL_KEY)


class BankIn(BaseModel):
    campaign_id: str
    tenant_key: str
    username: str
    secret: str


class AccountIn(BaseModel):
    kind: str  # one of _ACCOUNT_KEYS
    username: str
    secret: str


class CaptureIn(BaseModel):
    campaign_id: str
    tenant_key: str
    username: str
    secret: str


def _require_existing_campaign(container: Container, campaign_id: str) -> CampaignId:
    """Validate the campaign exists before banking under it.

    ``credentials.campaign_id`` is a NOT-NULL FK to ``campaigns``; banking under a
    campaign that doesn't exist raises a ForeignKeyViolation on a real DB (the
    in-memory store has no FK, so this only surfaces in production). Return a clean
    404 instead of a 500 for the front-door."""
    cid = CampaignId(campaign_id)
    if container.storage.campaigns.get(cid) is None:
        raise HTTPException(status_code=404, detail="No such campaign for this credential.")
    return cid


@router.post("", status_code=201)
def bank_manual(body: BankIn, container: Container = Depends(get_container)) -> dict:
    """Manually bank a credential set in the vault (FR-VAULT-2, preferred upfront)."""
    cid = _require_existing_campaign(container, body.campaign_id)
    container.credentials.store(
        cid,
        Credential(tenant_key=body.tenant_key, username=body.username, secret=body.secret),
    )
    return {"campaign_id": body.campaign_id, "tenant_key": body.tenant_key, "source": "manual"}


@router.post("/capture", status_code=201)
def capture(body: CaptureIn, container: Container = Depends(get_container)) -> dict:
    """Auto-capture credentials entered during live account-creation (FR-VAULT-2)."""
    cid = _require_existing_campaign(container, body.campaign_id)
    container.credentials.capture(cid, body.tenant_key, body.username, body.secret)
    return {"campaign_id": body.campaign_id, "tenant_key": body.tenant_key, "source": "captured"}


@router.post("/account", status_code=201)
def bank_account(body: AccountIn, container: Container = Depends(get_container)) -> dict:
    """Bank a GLOBAL account credential (Google / the default new-account set).

    Stored under the SYSTEM campaign so it applies to every job search — set once,
    reused everywhere (FR-VAULT-2). Rejects unknown kinds so only the two well-known
    account credentials can be banked here; per-site credentials use the campaign path.
    """
    if body.kind not in _ACCOUNT_KEYS:
        raise HTTPException(status_code=422, detail="Unknown account credential kind")
    container.credentials.store(
        CampaignId(SYSTEM_CAMPAIGN_ID),
        Credential(tenant_key=body.kind, username=body.username, secret=body.secret),
    )
    return {"kind": body.kind, "scope": "global", "source": "manual"}


@router.get("/account")
def account_status(container: Container = Depends(get_container)) -> dict:
    """Which global account credentials are set (no secrets/usernames returned)."""
    tenants = set(container.credentials.list_tenants(CampaignId(SYSTEM_CAMPAIGN_ID)))
    return {
        "google": GOOGLE_CREDENTIAL_KEY in tenants,
        "predefined_account": PREDEFINED_CREDENTIAL_KEY in tenants,
    }


@router.get("/{campaign_id}/tenants")
def list_tenants(campaign_id: str, container: Container = Depends(get_container)) -> dict:
    """List tenant keys with stored credentials (no secrets returned) (NFR-PRIV-1)."""
    tenants = container.credentials.list_tenants(CampaignId(campaign_id))
    return {"campaign_id": campaign_id, "tenants": tenants}


@router.post("/rotate-key")
def rotate_master_key(container: Container = Depends(get_container)) -> dict:
    """Rotate the vault master key — re-encrypt every secret under a NEW key (#361).

    Mints a fresh master key, re-seals every stored credential under it, and persists
    the re-sealed records, so the new key decrypts and the old key no longer does
    (FR-VAULT-3). The key-file is rotated in place at the configured path. No secrets
    are returned (NFR-PRIV-1) — only the count of records re-sealed.
    """
    store = container.credentials
    if not hasattr(store, "rotate_master_key"):
        raise HTTPException(status_code=501, detail="The vault does not support key rotation.")
    keyfile = container.settings.credential_keyfile
    rotated = store.rotate_master_key(keyfile)
    return {"rotated": True, "records": rotated}
