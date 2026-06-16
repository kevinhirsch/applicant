"""Dormant-surface registry (FR-UI-2; docs/dormant-surfaces.md).

One entry per grayed-out surface. ``seed_dormant_surfaces`` writes them to the
``dormant_surface_backlog`` table on startup so no dead UI ships as if live.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DormantSurface:
    key: str
    surface_name: str
    requirement_ids: tuple[str, ...]
    wiring_notes: str
    live_phase: int


#: The backlog from docs/dormant-surfaces.md (§3.19, FR-UI-2).
DORMANT_SURFACES: tuple[DormantSurface, ...] = (
    DormantSurface(
        key="resume_aggressiveness",
        surface_name="Resume aggressiveness / tuning control",
        requirement_ids=("FR-RESUME-9",),
        wiring_notes="Bind aggressiveness scale to generation params; never relax truthfulness.",
        live_phase=3,
    ),
    DormantSurface(
        key="digest_in_app",
        surface_name="Digest surface (in-app)",
        requirement_ids=("FR-DIG-1", "FR-DIG-3", "FR-DIG-4", "FR-DIG-5", "FR-UI-6"),
        wiring_notes="Bind to DigestReview port + decisions table.",
        live_phase=1,
    ),
    DormantSurface(
        key="redline_surface",
        surface_name="Redline / revision surface",
        requirement_ids=("FR-RESUME-8", "FR-ANSWER-1", "FR-NOTIF-4", "FR-UI-6"),
        wiring_notes="Bind to DocumentReview port + RevisionSession/generated_materials + renderer.",
        live_phase=3,
    ),
    DormantSurface(
        key="debug_surface",
        surface_name="Debug surface",
        requirement_ids=("FR-OBS-2", "FR-LOG-3", "FR-UI-6"),
        wiring_notes="Bind to AdminQuery port + structlog/OTel + screenshots + DBOS state.",
        live_phase=4,
    ),
    DormantSurface(
        key="tool_toggle_registry",
        surface_name="Tool-toggle registry",
        requirement_ids=("FR-UI-4",),
        wiring_notes="Bind to ToolRegistry port + tool_settings table; enforce at dispatch.",
        live_phase=4,
    ),
    DormantSurface(
        key="chatbot",
        surface_name="Chatbot",
        requirement_ids=("FR-CHAT-1", "FR-FB-2", "FR-UI-6"),
        wiring_notes="Bind to Chat port + LLM + attribute/criteria stores with confirmation gate.",
        live_phase=4,
    ),
    DormantSurface(
        key="multi_campaign_switcher",
        surface_name="Multi-campaign switcher",
        requirement_ids=("FR-CRIT-4", "NFR-EXT-1"),
        wiring_notes="Schema already campaign-scoped; wire CampaignManagement multi-ops + switcher.",
        live_phase=4,
    ),
    DormantSurface(
        key="update_button",
        surface_name="Update button (in-settings)",
        requirement_ids=("FR-OOBE-4", "FR-INSTALL-2"),
        wiring_notes="Bind to UpdateTrigger port + update script.",
        live_phase=4,
    ),
    DormantSurface(
        key="remote_takeover",
        surface_name="Remote-session takeover",
        requirement_ids=("FR-SANDBOX-2", "FR-SANDBOX-3", "FR-PREFILL-4", "FR-PREFILL-5", "FR-UI-6"),
        wiring_notes="Bind to RemoteSessionControl port + Sandbox/RemoteView sub-port.",
        live_phase=2,
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
                status="dormant",
                wiring_notes={"notes": surface.wiring_notes, "live_phase": surface.live_phase},
            )
        )
    return len(DORMANT_SURFACES)
