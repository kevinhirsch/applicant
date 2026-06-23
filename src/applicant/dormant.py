"""Dormant-surface registry (FR-UI-2; docs/dormant-surfaces.md).

One entry per grayed-out surface. ``seed_dormant_surfaces`` writes them to the
``dormant_surface_backlog`` table on startup so no dead UI ships as if live.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Surface status values for the backlog (FR-UI-2).
STATUS_LIVE = "live"  # backend exists and the surface is wired
STATUS_DORMANT = "dormant"  # present-but-grayed; backend not yet wired


@dataclass(frozen=True)
class DormantSurface:
    key: str
    surface_name: str
    requirement_ids: tuple[str, ...]
    wiring_notes: str
    live_phase: int
    #: Current wiring status. As phases land, surfaces whose backend now exists are
    #: switched from ``dormant`` to ``live`` (FR-UI-2). Anything still genuinely
    #: dormant stays ``dormant`` (present-but-grayed) with its backlog entry.
    status: str = STATUS_DORMANT


#: The backlog from docs/dormant-surfaces.md (§3.19, FR-UI-2).
DORMANT_SURFACES: tuple[DormantSurface, ...] = (
    DormantSurface(
        key="resume_aggressiveness",
        surface_name="Resume aggressiveness / tuning control",
        requirement_ids=("FR-RESUME-9",),
        wiring_notes=(
            "Generation accepts the aggressiveness param (Phase 3 MaterialService); "
            "per FR-RESUME-9 the control still SHIPS GRAYED for MVP-1. Stays dormant."
        ),
        live_phase=3,
        status=STATUS_DORMANT,
    ),
    DormantSurface(
        key="digest_in_app",
        surface_name="Digest surface (in-app)",
        requirement_ids=("FR-DIG-1", "FR-DIG-3", "FR-DIG-4", "FR-DIG-5", "FR-UI-6"),
        wiring_notes="Wired to DigestReview port + decisions table (Phase 1).",
        live_phase=1,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="redline_surface",
        surface_name="Redline / revision surface",
        requirement_ids=("FR-RESUME-8", "FR-ANSWER-1", "FR-NOTIF-4", "FR-UI-6"),
        wiring_notes="Wired to DocumentReview port + RevisionSession/generated_materials + renderer (Phase 3).",
        live_phase=3,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="debug_surface",
        surface_name="Debug surface",
        requirement_ids=("FR-OBS-2", "FR-LOG-3", "FR-UI-6"),
        wiring_notes="Wired to AdminQuery service + structlog ring buffer + screenshots + DBOS state (Phase 4).",
        live_phase=4,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="tool_toggle_registry",
        surface_name="Tool-toggle registry",
        requirement_ids=("FR-UI-4",),
        wiring_notes="Wired to ToolRegistry port + tool_settings table; enforced at dispatch (Phase 4).",
        live_phase=4,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="chatbot",
        surface_name="Chatbot",
        requirement_ids=("FR-CHAT-1", "FR-FB-2", "FR-UI-6"),
        wiring_notes="Wired to ChatService (LLM + attribute/criteria stores) with confirmation gate (Phase 4).",
        live_phase=4,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="criteria_editor",
        surface_name="Criteria editor",
        requirement_ids=("FR-CRIT-1", "FR-CRIT-2", "FR-CRIT-3", "FR-FB-3", "FR-UI-6"),
        wiring_notes=(
            "Wired to CriteriaService via /api/criteria: human-readable + editable, "
            "learned adjustments surfaced + overridable, integral edits gated (409). "
            "Live (Phase 5)."
        ),
        live_phase=5,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="attribute_editor",
        surface_name="Attribute-cloud editor",
        requirement_ids=("FR-ATTR-1", "FR-ATTR-2", "FR-ATTR-3", "FR-ATTR-4", "FR-ATTR-6", "FR-FB-3", "FR-UI-6"),
        wiring_notes=(
            "Wired to AttributeCloudService via /api/attributes: learned/AI-added "
            "values shown + overridable, integral edits gated (409), sensitive fields "
            "never AI-guessed (422). Live (Phase 5)."
        ),
        live_phase=5,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="multi_campaign_switcher",
        surface_name="Multi-campaign switcher",
        requirement_ids=("FR-CRIT-4", "NFR-EXT-1"),
        wiring_notes=(
            "Schema + services are campaign-scoped and multi-campaign readiness is "
            "verified (Phase 4a); MVP-1 runs a single campaign so the switcher UI "
            "ships grayed. Stays dormant."
        ),
        live_phase=4,
        status=STATUS_DORMANT,
    ),
    DormantSurface(
        key="update_button",
        surface_name="Update button (in-settings)",
        requirement_ids=("FR-OOBE-4", "FR-INSTALL-2"),
        wiring_notes="Wired to UpdateTrigger port + update script (safe dry-run default) (Phase 4).",
        live_phase=4,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="remote_takeover",
        surface_name="Remote-session takeover",
        requirement_ids=("FR-SANDBOX-2", "FR-SANDBOX-3", "FR-PREFILL-4", "FR-PREFILL-5", "FR-UI-6"),
        wiring_notes="Wired to RemoteSessionControl port + Sandbox/RemoteView sub-port (Phase 2).",
        live_phase=2,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="desktop_assist",
        surface_name="Desktop assist (live session)",
        requirement_ids=("FR-CUA-9", "FR-CUA-12"),
        wiring_notes=(
            "Wired end-to-end: ComputerUsePort + core guards + the real cua-driver "
            "MCP/stdio transport, exposed by app/routers/remote.py (desktop/health + "
            "per-session enable + guarded action), proxied at workspace "
            "/api/applicant/remote/desktop/*, surfaced as the live-session 'desktop "
            "help' toggle. Operability is CAPABILITY-gated at runtime, not by this flag: "
            "the control is offered only when COMPUTER_USE_BACKEND=cua AND the desktop "
            "driver is baked into the sandbox image so the health preflight passes; "
            "otherwise the front door renders it locked. Live (Phase 6)."
        ),
        live_phase=6,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="assistant_memory",
        surface_name="What the assistant remembers",
        requirement_ids=("FR-MIND-1", "FR-MIND-12"),
        wiring_notes=(
            "Wired end-to-end: MemoryStore port + in-memory/bridge adapters + "
            "curated-memory policy, exposed by app/routers/agent_memory.py "
            "(GET /api/agent-memory), proxied owner-scoped at workspace "
            "/api/applicant/mind/memory, and surfaced in the front-door memory panel. "
            "Default in_memory backend answers; the bridge (MIND_BACKEND=bridge) "
            "reaches the workspace substrate when configured. Live (Phase 6)."
        ),
        live_phase=6,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="saved_playbooks",
        surface_name="Saved playbooks",
        requirement_ids=("FR-MIND-2", "FR-MIND-3", "FR-MIND-12"),
        wiring_notes=(
            "Wired end-to-end: SkillStore + RecallIndex ports + in-memory/bridge "
            "adapters (progressive-disclosure L0/L1), exposed by "
            "app/routers/agent_memory.py (GET /api/agent-memory/skills[/{name}]), "
            "proxied at workspace /api/applicant/mind/skills, and surfaced as the "
            "'saved playbooks' panel. The workspace SKILL.md bridge backs it when "
            "MIND_BACKEND=bridge. Live (Phase 6)."
        ),
        live_phase=6,
        status=STATUS_LIVE,
    ),
    DormantSurface(
        key="curation_approvals",
        surface_name="Learning curation approvals",
        requirement_ids=("FR-MIND-7", "FR-MIND-9", "FR-MIND-12"),
        wiring_notes=(
            "Wired end-to-end: CurationService stages proposed memory/skill writes to "
            "a process-lived CurationLedger (review-before-write default on), exposed "
            "by app/routers/agent_memory.py (GET /api/agent-memory/curation + "
            "approve/deny), proxied at workspace /api/applicant/mind/curation, and "
            "surfaced as approve/deny items in the front-door memory panel reusing the "
            "existing toast machinery. Approving is the only path that writes a "
            "proposal; advisory-not-authorization is preserved. Live (Phase 6)."
        ),
        live_phase=6,
        status=STATUS_LIVE,
    ),
)


def seed_dormant_surfaces(storage_session: object | None) -> int:
    """Upsert the dormant-surface backlog into the DB (FR-UI-2).

    Returns the number of surfaces seeded. Tolerates ``None``/no-DB (returns the
    count of registered surfaces without persisting) so app boot works in tests.
    """
    if storage_session is None:
        return len(DORMANT_SURFACES)

    from applicant.adapters.storage.models import DormantSurfaceBacklogModel

    for surface in DORMANT_SURFACES:
        storage_session.merge(  # type: ignore[attr-defined]
            DormantSurfaceBacklogModel(
                id=surface.key,
                surface_name=surface.surface_name,
                requirement_ids=list(surface.requirement_ids),
                status=surface.status,
                wiring_notes={"notes": surface.wiring_notes, "live_phase": surface.live_phase},
            )
        )
    return len(DORMANT_SURFACES)
