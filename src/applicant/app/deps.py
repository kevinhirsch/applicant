"""FastAPI dependency providers sourced from the container.

The container lives on ``app.state.container`` (built in ``main.create_app``).
The LLM gate dependency (FR-UI-5) blocks downstream routes with 409 until the LLM
is configured.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from applicant.app.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_setup_service(container: Container = Depends(get_container)):
    return container.setup_service


def get_campaign_service(container: Container = Depends(get_container)):
    return container.campaign_service


def get_onboarding_service(container: Container = Depends(get_container)):
    return container.onboarding_service


def get_font_service(container: Container = Depends(get_container)):
    return container.font_service


def get_conversion_service(container: Container = Depends(get_container)):
    return container.conversion_service


def get_storage(container: Container = Depends(get_container)):
    return container.storage


def get_tool_registry(container: Container = Depends(get_container)):
    return container.tool_registry


def require_llm_configured(container: Container = Depends(get_container)) -> None:
    """Gate dependency: 409 until the LLM is configured (FR-UI-5, FR-OOBE-1).

    Apply to any router that must not run before OOBE LLM setup completes.
    """
    if not container.setup_service.is_setup_gate_open():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LLM is not configured. Complete the OOBE LLM-settings gate first (FR-UI-5).",
        )
