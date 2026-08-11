import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from flask import Request
from helpers.api import ApiHandler


# ── State constants ──────────────────────────────────────────────

STATE_ACTIVE: str = "active"
STATE_CONFIGURED: str = "configured"
STATE_LOCKED: str = "locked"
STATE_DISABLED: str = "disabled"


# ── Engine helpers (mirrors onboarding.py) ───────────────────────


def _engine() -> str:
    return os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")


def _forward(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    """Call the engine; return normalized envelope (never raises)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(f"{_engine()}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
            return {"ok": True, "status": r.status, "data": json.loads(raw) if raw.strip() else {}}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode()[:300]}
    except Exception as e:
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}


# ── Applicant sections catalog (ported from workspace/src/applicant_features.py) ──

APPLICANT_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "documents",
        "lane": "A",
        "title": "Documents / resume library",
        "nav_ids": ["rail-archive", "tool-library-btn", "overflow-doc-btn"],
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
    {
        "key": "debug",
        "lane": None,
        "title": "Activity / debug",
        "nav_ids": ["tool-debug-btn", "rail-debug"],
        "dormant_keys": ["debug_surface", "tool_toggle_registry"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    {
        "key": "update",
        "lane": None,
        "title": "Update Applicant",
        "nav_ids": ["rail-update"],
        "dormant_keys": ["update_button"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    {
        "key": "takeover",
        "lane": None,
        "title": "Live remote view / takeover",
        "nav_ids": ["settings-open-remote"],
        "dormant_keys": ["remote_takeover"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    {
        "key": "vault",
        "lane": None,
        "title": "Credential vault",
        "nav_ids": ["settings-open-vault"],
        "dormant_keys": [],
        "requires": "onboarding_complete",
        "present_but_disabled": False,
    },
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
        "nav_ids": [],
        "dormant_keys": ["multi_campaign_switcher"],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    {
        "key": "gallery",
        "lane": None,
        "title": "Gallery — screenshots & materials",
        "nav_ids": ["tool-applicant-gallery-btn", "rail-applicant-gallery"],
        "dormant_keys": [],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    {
        "key": "compare",
        "lane": None,
        "title": "Compare",
        "nav_ids": ["rail-compare", "tool-compare-btn", "rail-applicant-compare"],
        "dormant_keys": [],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
    {
        "key": "results",
        "lane": None,
        "title": "Results — your funnel & what converts",
        "nav_ids": ["rail-results", "tool-results-btn"],
        "dormant_keys": [],
        "requires": "llm_configured",
        "present_but_disabled": False,
    },
)


# ── Helpers (ported from workspace/src/applicant_features.py) ─────


def _requirement_met(requires: Optional[str], status: dict) -> bool:
    """Evaluate a section's gate predicate against the engine setup status.
    Unknown / missing predicate -> treated as met.
    """
    if not requires:
        return True
    return bool(status.get(requires))


def _dormant_live(dormant_keys: list[str], dormant_by_key: dict[str, dict]) -> bool:
    """A section's engine backing counts as present only if EVERY dormant
    surface reports status == "live" in the engine registry. Empty list -> True.
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
    """Resolve one section to a state string."""
    if section.get("present_but_disabled"):
        return STATE_DISABLED

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


# ── Public entry point ────────────────────────────────────────────


def compute_features() -> dict:
    """Build the feature-gating payload. Never raises."""

    # 1. Fetch setup status
    status_resp = _forward("GET", "/api/setup/status")
    engine_up: bool = status_resp.get("ok", False)
    fresh_status: Optional[dict] = status_resp.get("data") if engine_up else None

    # 2. Fetch dormant surfaces
    fresh_dormant: Optional[dict[str, dict]] = None
    if engine_up:
        dormant_resp = _forward("GET", "/api/dormant-surfaces")
        if dormant_resp.get("ok"):
            raw = dormant_resp.get("data")
            if isinstance(raw, list):
                fresh_dormant = {
                    d["key"]: d
                    for d in raw
                    if isinstance(d, dict) and d.get("key")
                }
            elif isinstance(raw, dict):
                fresh_dormant = raw

    # 3. Compute sections (output is a dict keyed by section key)
    sections: dict[str, dict] = {}
    for section in APPLICANT_SECTIONS:
        sections[section["key"]] = {
            "key": section["key"],
            "title": section["title"],
            "lane": section["lane"],
            "state": _section_state(
                section,
                engine_up=engine_up,
                status=fresh_status,
                dormant_by_key=fresh_dormant,
            ),
            "nav_ids": list(section["nav_ids"]),
            "requirement": section.get("requires"),
            "present_but_disabled": bool(section["present_but_disabled"]),
        }

    return {
        "engine_available": engine_up,
        "engine_url": _engine(),
        "sections": sections,
    }


# ── API handler ───────────────────────────────────────────────────


class Features(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return compute_features()
