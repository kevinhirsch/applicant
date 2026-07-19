import json
import os
import urllib.error
import urllib.request

from helpers.api import ApiHandler
from flask import Request


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


# ── Applicant sections catalog ───────────────────────────────────

APPLICANT_SECTIONS: tuple = (
    {
        "key": "chat",
        "title": "Chat",
        "requirement": "llm_configured",
        "dormant_key": "interviews",
        "nav_ids": ["chat-pane", "chat-iframe"],
    },
    {
        "key": "resumes",
        "title": "Resumes / CVs",
        "requirement": "resume_ready",
        "dormant_key": "resumes",
        "nav_ids": ["resume-pane"],
    },
    {
        "key": "jobs",
        "title": "Jobs",
        "requirement": "jobs_ready",
        "dormant_key": "jobs",
        "nav_ids": ["jobs-pane"],
    },
    {
        "key": "applications",
        "title": "Applications",
        "requirement": "apply_ready",
        "dormant_key": "applications",
        "nav_ids": ["applications-pane"],
    },
)


# ── Helpers ───────────────────────────────────────────────────────


def _requirement_met(reason: str, status: dict | None) -> bool:
    """True when the gate predicate is satisfied in status."""
    if status is None:
        return False
    val = status.get(reason)
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "yes", "1")
    return bool(val)


def _dormant_live(dormant_key: str, dormant: dict[str, dict] | None) -> bool:
    """True if the dormant surface key is present and live."""
    if dormant is None:
        return False
    entry = dormant.get(dormant_key)
    if entry is None:
        return False
    return entry.get("live", False) is True


def _section_state(
    section: dict,
    status: dict | None,
    dormant: dict[str, dict] | None,
) -> dict:
    """Return the enriched section dict with computed state."""
    key = section["key"]
    title = section["title"]
    req_field = section["requirement"]
    dormant_key = section["dormant_key"]
    nav_ids = section["nav_ids"]

    # disabled shortcut — special flag
    present_but_disabled = section.get("present_but_disabled", False)

    if present_but_disabled:
        lane = STATE_DISABLED
    elif status is None:
        lane = STATE_LOCKED
    else:
        gate_met = _requirement_met(req_field, status)
        backing_live = _dormant_live(dormant_key, dormant)
        if not gate_met:
            lane = STATE_LOCKED
        elif backing_live:
            lane = STATE_ACTIVE
        else:
            lane = STATE_CONFIGURED

    out = dict(section)
    out["state"] = lane
    return out


# ── Public entry point ────────────────────────────────────────────


def compute_features() -> dict:
    """Build the feature-gating payload. Never raises."""

    # 1. Fetch setup status
    status_resp = _forward("GET", "/api/setup/status")
    fresh_status: dict | None = status_resp.get("data") if status_resp.get("ok") else None

    # 2. Fetch dormant surfaces
    dormant_resp = _forward("GET", "/api/dormant-surfaces")
    raw_dormant = dormant_resp.get("data") if dormant_resp.get("ok") else None
    fresh_dormant: dict[str, dict] | None = None
    if isinstance(raw_dormant, list):
        fresh_dormant = {d["key"]: d for d in raw_dormant if isinstance(d, dict) and d.get("key")}
    elif isinstance(raw_dormant, dict):
        fresh_dormant = raw_dormant

    # 3. Engine availability
    engine_up = fresh_status is not None

    # 4. Compute sections
    sections = [_section_state(s, fresh_status, fresh_dormant) for s in APPLICANT_SECTIONS]

    return {
        "engine_available": engine_up,
        "engine_url": _engine(),
        "sections": sections,
    }


# ── API handler ───────────────────────────────────────────────────


class Features(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return compute_features()
