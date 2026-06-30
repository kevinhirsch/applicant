# src/applicant_features.py
"""Applicant feature-state layer.

The workspace already ships a coarse on/off feature mechanism (``/api/auth/features``
+ ``data/features.json``, see ``src/settings.py`` and ``static/app.js``). That stays
exactly as-is for the owner's own app features.

This module adds a SEPARATE, derived layer for the *Applicant-mapped* sections —
the workspace surfaces that Stage 2 wires to the engine. Their state is NOT a
hand-set toggle; it is computed from:

* the engine's setup/gate status (``GET /api/setup/status``), and
* the engine's dormant-surface registry (``GET /api/dormant-surfaces``).

so each section activates *progressively* as the engine is configured, instead of
shipping dead UI that 500s when clicked.

Per-section state is one of:

* ``"active"``    — engine reachable AND this section's backing is configured/live.
* ``"configured"`` — backing is configured but the engine is not currently reachable
                     (transient; the surface is real, just temporarily offline).
* ``"locked"``    — backing not yet configured (e.g. onboarding incomplete) — the
                     surface stays greyed until configured.
* ``"disabled"``  — present-but-DISABLED by product decision (no Applicant backing).
                     Compare ships here: visible, greyed, never wired to the engine.

This layer is read-only and best-effort: if the engine can't be reached we degrade
to ``configured``/``locked`` (never raise), so the nav still renders. User
management / auth is entirely untouched.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.applicant_engine import (
    EngineError,
    engine_available_sync,
    get_sync,
)

logger = logging.getLogger(__name__)

# Section state values.
STATE_ACTIVE = "active"
STATE_CONFIGURED = "configured"
STATE_LOCKED = "locked"
STATE_DISABLED = "disabled"  # present-but-disabled (no Applicant backing)


#: The Applicant section map. One entry per workspace surface that Stage 2 wires
#: to the engine. Each entry:
#:
#:   key            stable id used by the frontend + the contract doc.
#:   lane           which Stage-2 lane owns the wiring (A/B/C/D, or None).
#:   title          human label.
#:   nav_ids        DOM element ids the frontend greys/locks for this section
#:                  (sidebar rail + toolbar/overflow buttons in static/index.html).
#:   dormant_keys   engine dormant-surface keys whose status backs this section.
#:   requires       gate predicate name evaluated against the engine setup status
#:                  (see ``_requirement_met``); None = no extra gate.
#:   present_but_disabled  True -> always reported ``disabled`` (no surface uses
#:                  this today; the machinery stays for any future stopgap surface).
APPLICANT_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "documents",
        "lane": "A",
        "title": "Documents / resume library",
        "nav_ids": ["rail-documents", "tool-library-btn", "overflow-doc-btn"],
        "dormant_keys": ["redline_surface"],
        "requires": "onboarding_complete",
        "present_but_disabled": False,
    },
    {
        "key": "memory",
        "lane": "B",
        "title": "Memory / skills (attributes + learning)",
        "nav_ids": ["rail-memory", "tool-memory-btn"],
        "dormant_keys": ["attribute_editor", "criteria_editor"],
        "requires": "onboarding_complete",
        "present_but_disabled": False,
    },
    {
        "key": "chat",
        "lane": "C",
        "title": "Chat / assistant (job actions)",
        "nav_ids": ["tool-assistant-btn", "rail-assistant"],
        "dormant_keys": ["chatbot"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    # FR-MIND — the agent-learning substrate surfaced in the front door: "what the
    # assistant remembers", "saved playbooks", and the learning-curation approvals.
    # Reachable via the workspace /api/applicant/mind/* proxy over the engine's
    # /api/agent-memory router (gated behind the engine LLM gate), so it activates
    # once a model is connected. Shares the memory rail with the attribute/learning
    # section — both light up under the same nav.
    {
        "key": "mind",
        "lane": "B",
        "title": "What the assistant remembers / saved playbooks",
        "nav_ids": ["rail-memory", "tool-memory-btn"],
        "dormant_keys": ["assistant_memory", "saved_playbooks", "curation_approvals"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    {
        "key": "email",
        "lane": "D",
        "title": "Email / notifications & digests",
        "nav_ids": ["rail-email", "tool-email-btn"],
        "dormant_keys": ["digest_in_app"],
        "requires": "channels_configured",
        "present_but_disabled": False,
    },
    # CRIT-ops: Debug / Activity surface — read-only observability (history,
    # screenshots, redacted logs, workflow state, variant library) plus the
    # operator controls (update / run mode / discovery sources). The admin/ops
    # engine routers are gated behind the engine's LLM gate, so this activates
    # once a model is configured. nav_ids match the launcher in index.html.
    {
        "key": "debug",
        "lane": None,
        "title": "Activity / debug",
        "nav_ids": ["tool-debug-btn"],
        # #199: gate the launcher off the live operator surfaces it exposes — the
        # read-only observability (debug_surface) AND the tool-toggle registry whose
        # controls live inside this same Activity/debug panel. Both report ``live`` in
        # the engine registry, so the section stays active once a model is configured.
        "dormant_keys": ["debug_surface", "tool_toggle_registry"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    # end CRIT-ops
    # #199/#201 — Update surface: the in-rail one-click Update button
    # (#rail-update -> applicantUpdate.js _wireLauncher). Backed by the engine's
    # ``update_button`` live surface (UpdateTrigger port + update script). Greys via
    # the shared nav-gating in app.js refreshApplicantFeatures until the engine is
    # reachable and the surface reports live.
    {
        "key": "update",
        "lane": None,
        "title": "Update Applicant",
        "nav_ids": ["rail-update"],
        "dormant_keys": ["update_button"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    # #199/#201 — Live remote view / takeover: the "Open live session" launcher in
    # Settings (#settings-open-remote -> settings.js -> window.openApplicantRemoteSession
    # -> applicantRemote.js). Backed by the engine's ``remote_takeover`` live surface
    # (RemoteSessionControl + Sandbox/RemoteView). Gated off that key so the control
    # greys until the sandbox/remote backing is live.
    {
        "key": "takeover",
        "lane": None,
        "title": "Live remote view / takeover",
        "nav_ids": ["settings-open-remote"],
        "dormant_keys": ["remote_takeover"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    # #201 — Credential vault: the "Manage saved sign-ins" launcher in Settings
    # (#settings-open-vault -> settings.js -> window.openApplicantVault ->
    # applicantVault.js). The engine seals credentials at rest; there is no separate
    # dormant-surface key for the vault, so it gates on the onboarding gate alone
    # (a configured profile) and activates with the rest of the front door.
    {
        "key": "vault",
        "lane": None,
        "title": "Credential vault",
        "nav_ids": ["settings-open-vault"],
        "dormant_keys": [],
        "requires": "onboarding_complete",
        "present_but_disabled": False,
    },
    # Desktop help (FR-CUA) — the opt-in "let the assistant help on the desktop"
    # control lives inside the live-session surface + the Automation settings card.
    # It STAYS locked until the desktop helper is baked into the sandbox image and
    # the engine flips the ``desktop_assist`` dormant surface to live, so the feature
    # layer greys it off that key exactly like the other dormant surfaces. The
    # controls have no standalone nav entry (they're embedded), so nav_ids is empty;
    # the gate predicate is the live-session gate (a model configured).
    {
        "key": "desktop_assist",
        "lane": None,
        "title": "Desktop help (live session)",
        "nav_ids": [],
        "dormant_keys": ["desktop_assist"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    {
        "key": "multi_campaign_switcher",
        "lane": None,
        "title": "Multi-campaign switcher",
        "nav_ids": ["rail-campaigns", "tool-campaigns-btn"],
        "dormant_keys": ["multi_campaign_switcher"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    # Compare is engine-backed (#297): the engine's CompareService diffs two or
    # more applications/postings side-by-side (engine /api/compare → the
    # /api/applicant/compare proxy → applicantCompare.js). It lights up once a model
    # is configured, exactly like the other engine-backed surfaces.
    {
        "key": "compare",
        "lane": None,
        "title": "Compare",
        "nav_ids": ["rail-compare", "tool-compare-btn"],
        "dormant_keys": [],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
)


def _requirement_met(requires: Optional[str], status: dict) -> bool:
    """Evaluate a section's gate predicate against the engine setup status.

    Unknown / missing predicate -> treated as met (the section has no extra gate
    beyond the engine being reachable). A falsey/absent status field -> not met.
    """
    if not requires:
        return True
    return bool(status.get(requires))


def _dormant_live(dormant_keys: list[str], dormant_by_key: dict[str, dict]) -> bool:
    """A section's engine backing counts as present only if EVERY dormant surface
    it depends on reports ``status == "live"`` in the engine registry.

    If we have no registry data at all (engine unreachable), callers fall back to
    the gate predicate alone — see :func:`compute_features`.
    """
    if not dormant_keys:
        return True
    for k in dormant_keys:
        entry = dormant_by_key.get(k)
        if not entry or entry.get("status") != "live":
            return False
    return True


def _section_state(
    section: dict,
    *,
    engine_up: bool,
    status: Optional[dict],
    dormant_by_key: Optional[dict[str, dict]],
) -> str:
    """Resolve one section to a state string (see module docstring)."""
    if section.get("present_but_disabled"):
        return STATE_DISABLED

    # No engine data (unreachable / errored): we cannot prove the backing is
    # configured, so degrade to locked. The surface stays greyed but present.
    if status is None:
        return STATE_LOCKED

    gate_ok = _requirement_met(section.get("requires"), status)
    backing_live = (
        _dormant_live(section.get("dormant_keys", []), dormant_by_key)
        if dormant_by_key is not None
        else True
    )
    configured = gate_ok and backing_live
    if not configured:
        return STATE_LOCKED
    return STATE_ACTIVE if engine_up else STATE_CONFIGURED


def compute_features(
    *,
    base_url: Optional[str] = None,
    transport: Any = None,
) -> dict:
    """Compute the Applicant feature-state payload (read-only, never raises).

    Returns::

        {
          "engine_available": bool,
          "engine_url": str,
          "sections": {
            "<key>": {
              "key", "title", "lane", "state", "nav_ids",
              "requirement": <predicate or null>,
              "present_but_disabled": bool,
            }, ...
          },
        }

    ``transport`` (an httpx Mock/Base transport) is forwarded to the engine
    client for hermetic tests.
    """
    engine_up = engine_available_sync(base_url=base_url, transport=transport)

    status: Optional[dict] = None
    dormant_by_key: Optional[dict[str, dict]] = None
    if engine_up:
        try:
            raw_status = get_sync("/api/setup/status", base_url=base_url, transport=transport)
            if isinstance(raw_status, dict):
                status = raw_status
        except EngineError as exc:
            logger.debug("engine setup status unavailable: %s", exc)
        try:
            raw_dormant = get_sync("/api/dormant-surfaces", base_url=base_url, transport=transport)
            if isinstance(raw_dormant, list):
                dormant_by_key = {
                    d.get("key"): d for d in raw_dormant if isinstance(d, dict) and d.get("key")
                }
        except EngineError as exc:
            logger.debug("engine dormant surfaces unavailable: %s", exc)

    sections: dict[str, dict] = {}
    for section in APPLICANT_SECTIONS:
        sections[section["key"]] = {
            "key": section["key"],
            "title": section["title"],
            "lane": section["lane"],
            "state": _section_state(
                section,
                engine_up=engine_up,
                status=status,
                dormant_by_key=dormant_by_key,
            ),
            "nav_ids": list(section["nav_ids"]),
            "requirement": section["requires"],
            "present_but_disabled": bool(section["present_but_disabled"]),
        }

    from src.applicant_engine import engine_base_url

    return {
        "engine_available": engine_up,
        "engine_url": base_url or engine_base_url(),
        "sections": sections,
    }
