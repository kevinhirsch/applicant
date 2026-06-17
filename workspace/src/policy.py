"""Risk-tier action policy (Smokey parity, ADR-010 analogue).

Classifies agent/awareness actions into risk tiers and decides when an action
needs explicit confirmation. Applicant already gates *capabilities* via
per-user privileges (can/can't); this adds graduated *per-action* risk so the
agent can act freely on low-risk reads while outward/irreversible actions
(send email, control the home, shell, bulk delete) are confirmed.

Phase 0 ships the classifier + decision logic only. Enforcement is wired into
the agent tool dispatch in a later phase and is gated behind the
``APPLICANT_RISK_POLICY`` env flag (default off), so this module changes no
behavior on its own.

Pure standard-library — safe to import anywhere and unit-test without app deps.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

# Tiers, lowest to highest.
LOW = "low"
MEDIUM = "medium"
HIGH = "high"

TIER_ORDER: Dict[str, int] = {LOW: 0, MEDIUM: 1, HIGH: 2}

# Unknown actions are treated as MEDIUM — cautious but not blocking.
DEFAULT_TIER = MEDIUM

# Action/tool name -> tier. Data-driven so it can be overridden per user later.
#   low    = read-only / informational
#   medium = writes to the user's own data (reversible)
#   high   = outward-facing, irreversible, costly, or environment-affecting
ACTION_TIERS: Dict[str, str] = {
    # --- low: reads / lookups ---
    "web_search": LOW,
    "web_fetch": LOW,
    "read_file": LOW,
    "list_models": LOW,
    "list_sessions": LOW,
    "list_emails": LOW,
    "read_email": LOW,
    "list_email_accounts": LOW,
    "resolve_contact": LOW,
    "list_served_models": LOW,
    "list_downloads": LOW,
    "list_cached_models": LOW,
    "search_hf_models": LOW,
    "list_serve_presets": LOW,
    "list_cookbook_servers": LOW,

    # --- medium: writes to the user's own data ---
    "create_document": MEDIUM,
    "edit_document": MEDIUM,
    "update_document": MEDIUM,
    "suggest_document": MEDIUM,
    "manage_memory": MEDIUM,
    "manage_entity": MEDIUM,
    "manage_notes": MEDIUM,
    "manage_calendar": MEDIUM,
    "manage_contact": MEDIUM,
    "manage_skills": MEDIUM,
    "manage_tasks": MEDIUM,
    "manage_awareness": MEDIUM,
    "create_session": MEDIUM,
    "manage_session": MEDIUM,
    "manage_settings": MEDIUM,
    "manage_gallery": MEDIUM,
    "generate_image": MEDIUM,
    "ui_control": MEDIUM,

    # --- high: outward / irreversible / environment-affecting / costly ---
    "bash": HIGH,
    "python": HIGH,
    "write_file": HIGH,
    "send_email": HIGH,
    "reply_to_email": HIGH,
    "bulk_email": HIGH,
    "archive_email": HIGH,
    "app_api": HIGH,            # generic internal loopback — broad reach
    "serve_model": HIGH,
    "stop_served_model": HIGH,
    "download_model": HIGH,
    "trigger_research": HIGH,   # spawns a long, multi-call background job
    # Home Assistant (Phase 4)
    "ha_call_service": HIGH,
    "ha_set_alarm": HIGH,
}


def classify_action(name: Optional[str]) -> str:
    """Return the risk tier for an action/tool name."""
    if not name:
        return DEFAULT_TIER
    return ACTION_TIERS.get(name, DEFAULT_TIER)


def is_enforced() -> bool:
    """Whether risk-tier confirmation is actively enforced.

    Off by default (Phase 0). Enable with ``APPLICANT_RISK_POLICY=1``.
    """
    return os.getenv("APPLICANT_RISK_POLICY", "0").strip().lower() in ("1", "true", "yes", "on")


def requires_confirmation(
    name: Optional[str],
    *,
    pre_authorized: bool = False,
    enforced: Optional[bool] = None,
    min_tier: str = HIGH,
) -> bool:
    """Decide whether an action needs explicit user confirmation.

    Returns ``True`` only when enforcement is on, the action's tier is at or
    above ``min_tier`` (default HIGH), and the user has not pre-authorized that
    action class. With enforcement off (the Phase 0 default) this is always
    ``False`` — no behavior change.
    """
    if enforced is None:
        enforced = is_enforced()
    if not enforced or pre_authorized:
        return False
    tier = classify_action(name)
    return TIER_ORDER[tier] >= TIER_ORDER.get(min_tier, TIER_ORDER[HIGH])
