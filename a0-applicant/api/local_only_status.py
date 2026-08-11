"""AZ1-1 (#829) — Local-only status endpoint for the UI.

Exposes action "get" returning {"ok": True, "local_only": is_local_only()}.
The is_local_only() logic is inlined here (duplicate of the version in
_55_local_only_gate.py) to avoid cross-directory import fragility.
Both copies must stay in sync.

Self-contained (no sibling imports); the pure dispatch function is
module-level so it is unit-testable without the framework.
"""
from __future__ import annotations

import os

from helpers.api import ApiHandler
from flask import Request


def is_local_only() -> bool:
    """Return True when LLM_LOCAL_ONLY is set to a truthy value (case-insensitive).

    Duplicated from _55_local_only_gate.py; both copies must stay in sync.
    """
    val = os.environ.get("LLM_LOCAL_ONLY", "").strip().lower()
    return val in ("true", "1", "yes")


def dispatch(input: dict) -> dict:
    action = str((input or {}).get("action") or "").strip().lower()
    if action == "get":
        return {"ok": True, "local_only": is_local_only()}
    return {"ok": False, "status": 400, "error": f"unknown local_only_status action {action!r}"}


class LocalOnlyStatus(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
