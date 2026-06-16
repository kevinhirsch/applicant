"""Attributes router (FR-ATTR-1/2/3/4/5/6, FR-FB-3).

# STAGE B — owned by Phase 1.

Per-campaign attribute-cloud CRUD plus field-mapping binding (FR-ATTR-2), dynamic
AI-add (FR-ATTR-4), and the missing-attribute soft-error/resolve flow (FR-ATTR-5).
Two core-rule gates are enforced in the pure core, not here:

- **confirmation gate** (FR-FB-3): an integral change requires ``confirm=true`` or the
  core raises ``ConfirmationRequired`` -> HTTP 409;
- **sensitive-field policy** (FR-ATTR-6): values for EEO/demographic attributes are
  taken only from the user's explicit answer, never AI-guessed; the core rejects a
  guess with ``SensitiveFieldViolation`` -> HTTP 422.

Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured
from applicant.core.errors import ConfirmationRequired, SensitiveFieldViolation

router = APIRouter(
    prefix="/api/attributes", tags=["attributes"], dependencies=[Depends(require_llm_configured)]
)


def _svc(container: Container):
    return container.attribute_cloud_service


class UpsertAttributeIn(BaseModel):
    campaign_id: str
    name: str
    value: str
    aliases: list[str] = []
    is_integral: bool = False
    is_sensitive: bool = False
    confirm: bool = False
    ai_suggested: str | None = None  # if set for a sensitive attr -> rejected (FR-ATTR-6)


class BindFieldIn(BaseModel):
    site_key: str
    field_selector: str
    attribute_id: str | None = None
    campaign_id: str | None = None
    shared: bool = False  # global, cross-campaign mapping knowledge (FR-ATTR-2)
    metadata: dict = {}


class AiAddIn(BaseModel):
    campaign_id: str
    name: str
    value: str
    confirm: bool = False


class AcquireMissingIn(BaseModel):
    campaign_id: str
    name: str
    value: str
    confirm: bool = False


@router.get("")
def index() -> dict:
    return {"surface": "attributes", "phase": 1, "status": "live"}


@router.get("/{campaign_id}")
def list_attributes(campaign_id: str, container: Container = Depends(get_container)) -> dict:
    attrs = _svc(container).list_attributes(campaign_id)  # type: ignore[arg-type]
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
    try:
        attr = _svc(container).upsert(
            body.campaign_id,  # type: ignore[arg-type]
            body.name,
            body.value,
            aliases=tuple(body.aliases),
            is_integral=body.is_integral,
            is_sensitive=body.is_sensitive,
            confirm=body.confirm,
            ai_suggested=body.ai_suggested,
        )
    except ConfirmationRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SensitiveFieldViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": attr.id,
        "name": attr.name,
        "value": attr.value,
        "is_integral": attr.is_integral,
        "is_sensitive": attr.is_sensitive,
    }


@router.post("/ai-add", status_code=201)
def ai_add(body: AiAddIn, container: Container = Depends(get_container)) -> dict:
    """AI/learning dynamically adds a non-sensitive attribute (FR-ATTR-4)."""
    try:
        attr = _svc(container).ai_add_attribute(
            body.campaign_id, body.name, body.value, confirm=body.confirm  # type: ignore[arg-type]
        )
    except ConfirmationRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"id": attr.id, "name": attr.name, "value": attr.value}


@router.post("/bindings", status_code=201)
def bind_field(body: BindFieldIn, container: Container = Depends(get_container)) -> dict:
    """Bind an attribute to a specific ATS form field for pre-fill (FR-ATTR-2)."""
    mapping = _svc(container).bind_field(
        body.site_key,
        body.field_selector,
        attribute_id=body.attribute_id,  # type: ignore[arg-type]
        campaign_id=body.campaign_id,  # type: ignore[arg-type]
        shared=body.shared,
        metadata=body.metadata,
    )
    return {
        "id": mapping.id,
        "site_key": mapping.site_key,
        "field_selector": mapping.field_selector,
        "is_shared": mapping.is_shared,
        "attribute_id": mapping.attribute_id,
    }


@router.post("/acquire-missing", status_code=201)
def acquire_missing(body: AcquireMissingIn, container: Container = Depends(get_container)) -> dict:
    """Store a detail the user supplied for a previously-missing attribute (FR-ATTR-5)."""
    try:
        attr = _svc(container).acquire_missing(
            body.campaign_id, body.name, body.value, confirm=body.confirm  # type: ignore[arg-type]
        )
    except ConfirmationRequired as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SensitiveFieldViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": attr.id, "name": attr.name, "value": attr.value}
