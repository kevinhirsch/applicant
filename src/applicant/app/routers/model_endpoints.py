"""Model-endpoint router — add a model source and auto-list its models.

Backs the setup page's "Add Models" section (ported from the Applicant settings flow):
the user pastes a base URL (local Ollama or a cloud API) plus an optional key, and
the server lists the models available at that address. The contract matches what the
ported settings JS expects:

  * GET    /api/model-endpoints                 -> list (UI records, no keys)
  * POST   /api/model-endpoints                 -> add + live-list models (form data)
  * POST   /api/model-endpoints/test            -> probe without saving (form data)
  * PATCH  /api/model-endpoints/{id}            -> enable/disable toggle
  * DELETE /api/model-endpoints/{id}            -> remove
  * GET    /api/model-endpoints/{id}/models     -> live model list for one endpoint

The route is ungated (it is part of opening the setup gate). The server performs the
live model fetch so the browser never holds the raw provider key.
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from applicant.app.deps import get_container
from applicant.core.errors import InvalidInput


class ModelType(str, Enum):
    LLM = "llm"
    EMBEDDING = "embedding"
    IMAGE = "image"
    RERANK = "rerank"
    STT = "stt"
    TTS = "tts"


class EndpointConfig(BaseModel):
    """Typed model for endpoint configuration."""
    base_url: str = ""
    api_key: str = ""
    name: str = ""
    model_type: ModelType = ModelType.LLM
    skip_probe: bool = False


router = APIRouter(prefix="/api/model-endpoints", tags=["model-endpoints"])


def _service(container):
    return container.model_endpoint_service


@router.get("")
def list_endpoints(refresh: bool = False, container=Depends(get_container)) -> JSONResponse:
    """List configured endpoints with their live models (the dropdowns read this)."""
    return JSONResponse(_service(container).list_endpoints(refresh=refresh))


@router.post("")
def add_endpoint(
    base_url: str = Form(""),
    api_key: str = Form(""),
    name: str = Form(""),
    model_type: ModelType = Form(ModelType.LLM),
    skip_probe: str = Form("false"),
    container=Depends(get_container),
) -> JSONResponse:
    """Add an endpoint and live-list its models on save (the form's "Add")."""
    # Build the typed model for validation
    config = EndpointConfig(
        base_url=base_url,
        api_key=api_key,
        name=name,
        model_type=model_type,
        skip_probe=str(skip_probe).lower() in ("true", "1", "yes"),
    )
    try:
        result = _service(container).add_endpoint(
            base_url=config.base_url,
            api_key=config.api_key,
            name=config.name,
            model_type=config.model_type.value,
            probe=not config.skip_probe,
        )
    except InvalidInput as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return JSONResponse(result)


# This module uses ``from __future__ import annotations`` (PEP 563), so every
# annotation is stored as a STRING. The ``model_type`` Form parameter is genuinely
# constrained to the ``ModelType`` enum (#319), but ``inspect.signature`` would
# otherwise report the bare string ``"ModelType"`` and hide that constraint from
# introspection. Reify the real enum class on the annotation so the constraint is
# visible to ``inspect.signature(add_endpoint)`` without needing ``eval_str=True``.
add_endpoint.__annotations__["model_type"] = ModelType


@router.post("/test")
def test_endpoint(
    base_url: str = Form(""),
    api_key: str = Form(""),
    container=Depends(get_container),
) -> JSONResponse:
    """Probe an endpoint without saving it (the form's "Test")."""
    try:
        result = _service(container).test_endpoint(base_url=base_url, api_key=api_key)
    except InvalidInput as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return JSONResponse(result)


@router.patch("/{endpoint_id}")
def patch_endpoint(endpoint_id: str, container=Depends(get_container)) -> JSONResponse:
    """Toggle an endpoint enabled/disabled (matches the Applicant PATCH toggle)."""
    svc = _service(container)
    if svc.get_endpoint(endpoint_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown endpoint")
    svc.toggle_enabled(endpoint_id)
    return JSONResponse({"ok": True})


@router.delete("/{endpoint_id}")
def delete_endpoint(endpoint_id: str, container=Depends(get_container)) -> JSONResponse:
    _service(container).delete_endpoint(endpoint_id)
    return JSONResponse({"ok": True})


@router.get("/{endpoint_id}/models")
def endpoint_models(
    endpoint_id: str, refresh: bool = False, container=Depends(get_container)
) -> JSONResponse:
    """Return the live model list for one endpoint."""
    svc = _service(container)
    if svc.get_endpoint(endpoint_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown endpoint")
    return JSONResponse(svc.models_for_id(endpoint_id, refresh=refresh))
