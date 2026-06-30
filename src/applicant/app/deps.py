"""FastAPI dependency providers sourced from the container.

The container lives on ``app.state.container`` (built in ``main.create_app``).
The LLM gate dependency (FR-UI-5) blocks downstream routes with 409 until the LLM
is configured.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status

from applicant.app.container import Container
from applicant.core.ids import validate_id as _validate_id


def ValidatedPathParam(value: str) -> str:
    """FastAPI dependency that validates a path parameter.

    Usage::

        @router.get("/{campaign_id}")
        def get(campaign_id: str = Depends(ValidatedPathParam)):
            ...

    Rejects empty, NUL-byte, and path-traversal values before they reach the handler.
    """
    return _validate_id(value)


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_request_services(
    request: Request, container: Container = Depends(get_container)
) -> Iterator[dict | None]:
    """Build the PER-REQUEST storage-bound service bundle (CONC-REQ-1).

    SQLAlchemy Sessions are NOT thread-safe, and sync routers run in FastAPI's
    threadpool, so sharing one container-level ``SqlAlchemyStorage(session)`` across
    concurrent requests interleaves DB work on a single Session. When a real DB is
    configured the container exposes ``request_services_factory`` which builds a fresh
    ``SqlAlchemyStorage(session_factory())`` + its storage-bound services for THIS
    request; the Session is closed in ``finally``. With no DB (tests / first boot) the
    in-memory storage is shared (there is no Session to isolate) and ``None`` is
    yielded so the service getters fall back to the container singletons.

    The bundle is cached on ``request.state`` so multiple service deps in one request
    reuse the same Session-backed storage (a single unit of work per request).
    """
    cached = getattr(request.state, "_request_services", None)
    if cached is not None:
        yield cached
        return
    factory = getattr(container, "request_services_factory", None)
    if factory is None:
        # No DB configured — share the (thread-safe-enough) in-memory storage.
        request.state._request_services = None
        yield None
        return
    services = factory()
    request.state._request_services = services
    try:
        yield services
    finally:
        session = services.get("_session")
        if session is not None:
            try:
                session.close()
            except Exception:  # pragma: no cover - close must never break the response
                pass
        request.state._request_services = None


def _resolved(services: dict | None, container: Container, name: str):
    """Return the per-request service when present, else the container singleton."""
    if services is not None and name in services:
        return services[name]
    return getattr(container, name)


def get_setup_service(container: Container = Depends(get_container)):
    return container.setup_service


def get_campaign_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "campaign_service")


def get_data_lifecycle_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    """The campaign-delete purge + PII retention service (#363, CONC-REQ-1)."""
    return _resolved(services, container, "data_lifecycle_service")


def get_onboarding_service(container: Container = Depends(get_container)):
    return container.onboarding_service


def get_font_service(container: Container = Depends(get_container)):
    return container.font_service


def get_conversion_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "conversion_service")


def get_criteria_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "criteria_service")


def get_agent_run_service(container: Container = Depends(get_container)):
    return container.agent_run_service


def get_scheduler(container: Container = Depends(get_container)):
    """The 24/7 scheduler singleton — its live heartbeat backs the status endpoint
    and its per-campaign lock backs the on-demand 'Run now' (FR-AGENT-7/FR-OBS-2)."""
    return container.scheduler


def get_discovery_service(container: Container = Depends(get_container)):
    return container.discovery_service


def get_notification_service(container: Container = Depends(get_container)):
    """The shared notification service (container singleton).

    Singleton (not per-request) so its in-app inbox + escalation ladder persist
    across requests — the notification center reads the same live sink the
    scheduler/agent loop write into.
    """
    return container.notification_service


def get_storage(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    """Return a PER-REQUEST Session-backed storage when a DB is configured (CONC-REQ-1).

    Falls back to the shared in-memory storage when no DB is configured.
    """
    return _resolved(services, container, "storage")


def get_tool_registry(container: Container = Depends(get_container)):
    return container.tool_registry


def get_research_service(container: Container = Depends(get_container)):
    """Lane B (Stage 2.5): the capped deep-research tool (container singleton).

    Singleton (not per-request) so its per-campaign budget + dedupe cache persist
    across requests — re-running an identical query is free and the cap holds.
    """
    return container.research_service


# --- per-request storage-bound services (CONC-REQ-1) --------------------------
def get_material_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "material_service")


def get_submission_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "submission_service")


def get_pending_actions_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "pending_actions_service")


def get_attribute_cloud_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "attribute_cloud_service")


def get_feedback_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "feedback_service")


def get_chat_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "chat_service")


def get_digest_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "digest_service")


def get_admin_query_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "admin_query_service")


def get_prefill_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "prefill_service")


def get_learning_service(
    container: Container = Depends(get_container),
    services: dict | None = Depends(get_request_services),
):
    return _resolved(services, container, "learning_service")


def get_agent_memory(container: Container = Depends(get_container)):
    """The curated-memory / skills / recall adapter trio (FR-MIND-1/2/3).

    Process-lived (the stores hold the durable substrate or the bridge client), so
    it is the container singleton — not a per-request rebuild.
    """
    return container.agent_memory


def get_curation_service(container: Container = Depends(get_container)):
    """The closed-loop curation service (FR-MIND-7). Container singleton."""
    return container.curation_service


def get_curation_ledger(container: Container = Depends(get_container)):
    """The process-lived curation ledger holding staged proposals (FR-MIND-9/-10)."""
    return container.curation_ledger


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
            detail="Connect an AI model first to continue. You can do this in the setup wizard or under Settings.",
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
