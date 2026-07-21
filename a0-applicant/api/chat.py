"""AZ2 (#837) — Chat proxy: send messages, confirm attribute/criteria changes per campaign.

Extends AZ3 (#845) with help-intent detection: when the user asks "how do I..."
the dispatch short-circuits and returns help content from the help module
instead of forwarding to the engine.

The Chat UI is served by the a0 shell, but the Applicant engine is internal-only
("api:8000"). This handler forwards the UI's calls to the engine's "/api/chat"
API, keeping the engine the single source of truth for conversation state.
Three actions dispatched by "action": "send" (POST), "confirm" (POST), "confirm_criteria" (POST).

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_forward"
logic is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from helpers.api import ApiHandler
from flask import Request


def _engine() -> str:
    return os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")


def _detect_help_intent(message: str, content: dict | None = None) -> str | None:
    """Detect a "how do I…" / "how does X work" style help intent in message.

    Returns the matched surface id (str) or None if no intent or no match.

    When *content* is None (production), loads from api.help at runtime via a
    lazy import.  When *content* is provided (tests), uses it directly so the
    function is unit-testable without the framework.
    """
    if not isinstance(message, str) or not message.strip():
        return None

    # Simple regex: "how do I…", "how does X work", "how to…"
    if not re.search(r"how (do|does|to)\b.*\?", message, re.IGNORECASE):
        return None

    # Load help content
    if content is None:
        try:
            from api.help import load as load_help_content
            content = load_help_content()
        except Exception:
            return None

    if not isinstance(content, dict):
        return None

    msg_lower = message.lower()
    best_match: str | None = None
    for sid, surface in content.items():
        title = (surface.get("title") if isinstance(surface, dict) else "") or ""
        if title and title.lower() in msg_lower:
            best_match = sid
            break

    return best_match


def _forward(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    """Call the engine; return a normalized ``{ok, status, data|error}`` envelope (never raises)."""
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


def dispatch(input: dict) -> dict:
    cid = str((input or {}).get("campaign_id") or "__system__").strip() or "__system__"
    action = str((input or {}).get("action") or "send").strip().lower()

    if action == "send":
        message = (input or {}).get("message") or ""
        if not message.strip():
            return {"ok": False, "status": 400, "error": "message required"}

        # AZ3 (#845): short-circuit help-intent messages before forwarding to engine
        surface_id = _detect_help_intent(message)
        if surface_id is not None:
            try:
                from api.help import load as _load_help
                content = _load_help()
                surface = (content or {}).get(surface_id)
            except Exception:
                surface = None
            if surface and isinstance(surface, dict):
                steps = surface.get("steps", [])
                answer_text = "\n".join(steps) if isinstance(steps, list) else str(steps)
            else:
                answer_text = (
                    f"I found a guide for \"{surface_id}\" — "
                    "please open the Help panel or try asking more specifically."
                )
            return {
                "ok": True,
                "status": 200,
                "data": {
                    "answer": answer_text,
                    "surface": surface_id,
                    "deep_link": f"help.html?surface={surface_id}",
                },
            }

        body = {
            "campaign_id": cid,
            "message": message,
        }
        return _forward("POST", "/api/chat", body)

    if action == "confirm":
        body = {
            "campaign_id": cid,
            "name": input.get("name"),
            "value": input.get("value"),
        }
        return _forward("POST", "/api/chat/confirm", body)

    if action == "confirm_criteria":
        body = {
            "campaign_id": cid,
            "changes": input.get("changes", {}),
        }
        return _forward("POST", "/api/chat/confirm-criteria", body)

    return {"ok": False, "status": 400, "error": f"unknown chat action {action!r}"}


class Chat(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
