"""AZ3 (#845) — Help proxy: single source of truth for help content per surface.

The Help panel and chat both render from the same help_content.yaml config keyed
by surface id, keeping the content model DRY.

Two actions dispatched by "action": "list" (returns all surface id+title pairs),
"get" (returns {title, steps, prerequisites} for one surface).

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/"_load"
logic is module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from helpers.api import ApiHandler
from flask import Request


_CONTENT: dict | None = None


def _config_path() -> Path | None:
    for cand in [
        Path(os.getenv("HELP_CONTENT_PATH", "")),
        Path(__file__).resolve().parent.parent / "config" / "help_content.yaml",
        Path(__file__).resolve().parent / ".." / "config" / "help_content.yaml",
    ]:
        if cand.exists():
            return cand
    return None


def load() -> dict:
    """Load help content from yaml; returns {surface_id: {title, steps, prerequisites}, ...}."""
    global _CONTENT
    if _CONTENT is not None:
        return _CONTENT
    path = _config_path()
    if path is None:
        _CONTENT = {}
        return _CONTENT
    with open(path, "r", encoding="utf-8") as f:
        _CONTENT = yaml.safe_load(f) or {}
    return _CONTENT


def dispatch(input: dict) -> dict:
    action = str((input or {}).get("action") or "list").strip().lower()
    content = load()

    if action == "list":
        surfaces = [
            {"id": sid, "title": (s.get("title") or sid)}
            for sid, s in content.items()
        ]
        surfaces.sort(key=lambda x: x["id"])
        return {"ok": True, "status": 200, "data": {"surfaces": surfaces}}

    if action == "get":
        surface = str((input or {}).get("surface") or "").strip()
        if not surface:
            return {"ok": False, "status": 400, "error": "'surface' parameter is required"}
        s = content.get(surface)
        if s is None:
            return {"ok": False, "status": 404, "error": f"unknown surface {surface!r}"}
        return {
            "ok": True,
            "status": 200,
            "data": {
                "title": s.get("title", surface),
                "steps": s.get("steps", []),
                "prerequisites": s.get("prerequisites", "none"),
            },
        }

    return {"ok": False, "status": 400, "error": f"unknown help action {action!r}"}


class Help(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
