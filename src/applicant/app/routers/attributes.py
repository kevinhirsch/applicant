"""Attributes router (FR-ATTR-1/3/4/6, FR-FB-3).

# STAGE B — owned by Phase 1.

Per-campaign attribute-cloud CRUD with two core-rule gates enforced in the pure core,
not here:

- **confirmation gate** (FR-FB-3): an integral change requires ``confirm=true`` or the
  core raises ``ConfirmationRequired`` -> HTTP 409;
- **sensitive-field policy** (FR-ATTR-6): values for EEO/demographic attributes are
  taken only from the user's explicit answer, never AI-guessed; the core rejects a guess
  with ``SensitiveFieldViolation`` -> HTTP 422.

Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured
from applicant.core.entities.attribute import Attribute
from applicant.core.errors import ConfirmationRequired, SensitiveFieldViolation
from applicant.core.ids import AttributeId, new_id
from applicant.core.rules import sensitive_fields
from applicant.core.rules.confirmation_gate import ensure_change_allowed

router = APIRouter(
    prefix="/api/attributes", tags=["attributes"], dependencies=[Depends(require_llm_configured)]
)


class UpsertAttributeIn(BaseModel):
    campaign_id: str
    name: str
    value: str
    aliases: list[str] = []
    is_integral: bool = False
    is_sensitive: bool = False
    confirm: bool = False
    ai_suggested: str | None = None  # if set for a sensitive attr -> rejected (FR-ATTR-6)


@router.get("")
def index() -> dict:
    return {"surface": "attributes", "phase": 1, "status": "live"}


@router.get("/{campaign_id}")
def list_attributes(campaign_id: str, container: Container = Depends(get_container)) -> dict:
    attrs = container.storage.attributes.list_for_campaign(campaign_id)  # type: ignore[arg-type]
    return {
        "campaign_id": campaign_id,
        "items": [
            {
                "id": a.id,
                "name": a.name,
                "value": a.value,
                "aliases": list(a.aliases),
                "is_integral": a.is_integral,
                "is_sensitive": a.is_sensitive,
            }
            for a in attrs
        ],
    }


@router.post("", status_code=201)
def upsert_attribute(body: UpsertAttributeIn, container: Container = Depends(get_container)) -> dict:
    """Add/update an attribute through the confirmation + sensitive-field gates."""
    existing = container.storage.attributes.list_for_campaign(body.campaign_id)  # type: ignore[arg-type]
    prior = next((a for a in existing if a.name.lower() == body.name.lower()), None)

    # Confirmation gate (FR-FB-3): integral change needs explicit confirmation.
    is_integral_change = body.is_integral or (prior is not None and prior.is_integral)
    is_value_change = prior is None or prior.value != body.value
    try:
        if is_value_change:
            ensure_change_allowed(is_integral=is_integral_change, user_confirmed=body.confirm)
    except ConfirmationRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Sensitive-field policy (FR-ATTR-6): never accept an AI guess for sensitive attrs.
    sensitive = body.is_sensitive or sensitive_fields.is_sensitive_field(body.name)
    try:
        decision = sensitive_fields.decide_sensitive_fill(
            body.name if sensitive else "non-sensitive",
            body.value,
            ai_suggested=body.ai_suggested,
        )
    except SensitiveFieldViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    attr = Attribute(
        id=prior.id if prior else AttributeId(new_id()),
        campaign_id=body.campaign_id,  # type: ignore[arg-type]
        name=body.name,
        value=decision.value if sensitive else body.value,
        aliases=tuple(body.aliases),
        is_integral=body.is_integral,
        is_sensitive=sensitive,
    )
    container.storage.attributes.add(attr)
    container.storage.commit()
    return {
        "id": attr.id,
        "name": attr.name,
        "value": attr.value,
        "is_integral": attr.is_integral,
        "is_sensitive": attr.is_sensitive,
    }
