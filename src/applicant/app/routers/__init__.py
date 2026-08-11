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
    audit,
    campaigns,
    chat,
    compare,
    conversion,
    credentials,
    criteria,
    dev_seed,
    digest,
    discovery_sources,
    documents,
    easy_apply,
    explain,
    feedback,
    fonts,
    gallery,
    health,
    intake,
    model_endpoints,
    notifications,
    onboarding,
    outcomes,
    pending_actions,
    post_submission,
    realtime,
    remote,
    research,
    review,
    setup,
    stealth,
    ui,
    update,
)


def register_routers(app: FastAPI) -> None:
    # setup first (the LLM gate); ui + model-endpoints are ungated (they open the gate).
    app.include_router(setup.router)
    app.include_router(model_endpoints.router)
    # EPIC STEALTH: the dedicated Stealth settings surface (FR-STEALTH-1/-4). Ungated
    # like setup/model-endpoints/ui — it IS a settings surface (it configures the
    # anti-detect/egress posture), needs no LLM gate, and reuses container.settings +
    # container.setup_service, so no new container binding is required. The a0 shell
    # reaches it through the stealth proxy (a0-applicant/api/stealth.py) + panel
    # (a0-applicant/webui/stealth.html), auto-discovered by basename.
    app.include_router(stealth.router)
    app.include_router(ui.router)
    # health/capabilities (P1-3): ungated, like the trio above — an owner must be
    # able to see WHY automated work hasn't started before the gate even opens.
    app.include_router(health.router)
    # Realtime WebSocket backbone (realtime-websocket.md, Phase 1): a multiplexed
    # duplex socket per session speaking the {chan,type,seq,data} envelope. Ungated
    # like the pre-gate group above — presence/round-trip must work before the LLM
    # gate opens; every UPSTREAM command is still authorized server-side by the core
    # seam (default-deny), so it adds no new authority.
    app.include_router(realtime.router)
    # gated driving-port routers
    app.include_router(campaigns.router)
    app.include_router(criteria.router)
    app.include_router(discovery_sources.router)
    # P1-9: direct-URL intake (save a job from any page) — same gates as discovery.
    app.include_router(intake.router)
    app.include_router(agent_runs.router)
    app.include_router(agent_status.router)
    app.include_router(onboarding.router)
    app.include_router(fonts.router)
    app.include_router(conversion.router)
    app.include_router(attributes.router)
    app.include_router(digest.router)
    # EXPLAIN backend: per-posting weighted greens/reds score breakdown, read-only
    # this round (no dedicated panel yet — reached via the a0 explain proxy).
    app.include_router(explain.router)
    app.include_router(feedback.router)
    # EPIC REVIEW-UX (RUX-1/2/3): the Pending-Reviews decide/refine workflow. Gated
    # behind require_llm_configured internally (like feedback/digest), so its order
    # among the gated routers does not matter. Its UI reuses documents.html; the a0
    # shell reaches it through the review proxy (a0-applicant/api/review.py).
    app.include_router(review.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(remote.router)
    app.include_router(outcomes.router)
    app.include_router(post_submission.router)
    # P2-14: Easy Apply assisted-mode brief (deep-link + checklist + prepared
    # materials pointer) -- gated server-side on the recorded consent record.
    app.include_router(easy_apply.router)
    app.include_router(compare.router)
    app.include_router(credentials.router)
    app.include_router(pending_actions.router)
    app.include_router(agent_memory.router)
    app.include_router(notifications.router)
    app.include_router(research.router)
    app.include_router(admin.router)
    app.include_router(audit.router)
    app.include_router(gallery.router)
    app.include_router(update.router)
    # Dev/demo seed (audit §6 quick-win #49): registered unconditionally, but every
    # route on it self-gates 404 unless DEMO_MODE=1 (alias APPLICANT_ALLOW_SEED=1) —
    # see dev_seed.py.
    app.include_router(dev_seed.router)
    # The MCP surface is mounted by ``mount_mcp(app)`` (app/main.py) so the native
    # tool routes appear as flat /mcp APIRoutes (#308); not included here.
