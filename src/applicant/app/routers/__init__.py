"""Router registry — wires every driving-port router into the app.

``register_routers`` is called by ``main.create_app``. Each driving port has one
router (setup, campaigns, attributes, digest, documents, chat, remote, outcomes,
pending_actions, admin, update, ui).
"""

from __future__ import annotations

from fastapi import FastAPI

from applicant.app.routers import (
    admin,
    attributes,
    campaigns,
    chat,
    digest,
    documents,
    outcomes,
    pending_actions,
    remote,
    setup,
    ui,
    update,
)


def register_routers(app: FastAPI) -> None:
    # setup first (the LLM gate); ui is ungated (opens the gate).
    app.include_router(setup.router)
    app.include_router(ui.router)
    # gated driving-port routers
    app.include_router(campaigns.router)
    app.include_router(attributes.router)
    app.include_router(digest.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(remote.router)
    app.include_router(outcomes.router)
    app.include_router(pending_actions.router)
    app.include_router(admin.router)
    app.include_router(update.router)
