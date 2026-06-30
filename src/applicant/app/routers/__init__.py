"""Router registry — wires every driving-port router into the app.

``register_routers`` is called by ``main.create_app``. Each driving port has one
router (setup, campaigns, attributes, digest, documents, chat, remote, outcomes,
pending_actions, admin, update, ui).
"""

from __future__ import annotations

from fastapi import FastAPI

from applicant.app.routers import (
    admin,
    agent_memory,
    agent_runs,
    agent_status,
    attributes,
    campaigns,
    chat,
    conversion,
    credentials,
    criteria,
    digest,
    discovery_sources,
    documents,
    feedback,
    fonts,
    model_endpoints,
    notifications,
    onboarding,
    outcomes,
    pending_actions,
    remote,
    research,
    setup,
    ui,
    update,
    mcp,
)


def register_routers(app: FastAPI) -> None:
    # setup first (the LLM gate); ui + model-endpoints are ungated (they open the gate).
    app.include_router(setup.router)
    app.include_router(model_endpoints.router)
    app.include_router(ui.router)
    # gated driving-port routers
    app.include_router(campaigns.router)
    app.include_router(criteria.router)
    app.include_router(discovery_sources.router)
    app.include_router(agent_runs.router)
    app.include_router(agent_status.router)
    app.include_router(onboarding.router)
    app.include_router(fonts.router)
    app.include_router(conversion.router)
    app.include_router(attributes.router)
    app.include_router(digest.router)
    app.include_router(feedback.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(remote.router)
    app.include_router(outcomes.router)
    app.include_router(credentials.router)
    app.include_router(pending_actions.router)
    app.include_router(agent_memory.router)
    app.include_router(notifications.router)
    app.include_router(research.router)
    app.include_router(admin.router)
    app.include_router(update.router)
    app.include_router(mcp.router)
