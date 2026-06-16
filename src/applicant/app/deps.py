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


def get_criteria_service(container: Container = Depends(get_container)):
    return container.criteria_service


def get_agent_run_service(container: Container = Depends(get_container)):
    return container.agent_run_service


def get_discovery_service(container: Container = Depends(get_container)):
    return container.discovery_service


def get_storage(container: Container = Depends(get_container)):
    return container.storage


def get_tool_registry(container: Container = Depends(get_container)):
    return container.tool_registry


def require_tool_enabled(tool_key: str):
    """Build a dependency that 403s if ``tool_key`` is toggled off (FR-UI-4).

    Apply to a capability router so an operator's toggle authoritatively disables
    the capability at the dispatch boundary — the toggle is enforced, not advisory.
    """

    def _dep(container: Container = Depends(get_container)) -> None:
        from applicant.adapters.tools.tool_registry import ToolDisabledError

        try:
            container.tool_registry.ensure_enabled(tool_key)
        except ToolDisabledError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return _dep


def require_llm_configured(container: Container = Depends(get_container)) -> None:
    """Gate dependency: 409 until the LLM is configured (FR-UI-5, FR-OOBE-1).

    Apply to any router that must not run before OOBE LLM setup completes.
    """
    if not container.setup_service.is_setup_gate_open():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LLM is not configured. Complete the OOBE LLM-settings gate first (FR-UI-5).",
        )


def require_automated_work(container: Container = Depends(get_container)) -> None:
    """Gate dependency: 409 until automated work may begin (FR-ONBOARD-2, FR-OOBE-3).

    Automated work is blocked until ALL of the OOBE preconditions hold: the LLM is
    configured (FR-UI-5), notification channels are configured (FR-OOBE-3), and the
    onboarding intake is complete (FR-ONBOARD-2). Apply this to every router that
    triggers automated work (discovery runs, scoring, digest, prefill/remote,
    agent-runs); do NOT apply it to the setup/onboarding/channels routers that must
    work BEFORE the gate opens.
    """
    if not container.setup_service.is_automated_work_allowed():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Automated work is blocked until onboarding is complete and the LLM + "
                "notification channels are configured (FR-ONBOARD-2, FR-OOBE-3)."
            ),
        )
