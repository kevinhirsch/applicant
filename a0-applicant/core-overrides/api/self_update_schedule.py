"""Applicant override of the framework's self-update ACTION handler.

Upstream `self_update_schedule` writes a pending-update trigger file that, at the
next restart, git-checks-out UPSTREAM agent-zero over /a0 — which would BREAK the
Applicant fork (replace the fork's framework with upstream). Applicant ships its
OWN updater: panel -> /api/update/trigger -> updater sidecar -> scripts/update.sh
--apply, which rebuilds THIS fork's images from the local checkout (safe-sync never
drops unpushed commits). This override redirects the built-in Update action to that
safe updater so the familiar button can NEVER pull upstream over the fork.

Installed over /a0/api/self_update_schedule.py at image-build time (see
docker/Dockerfile.a0). Kept API-compatible with the self-update UI store, which
reads {success, message|error}.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from helpers.api import ApiHandler, Request, Response


def _engine() -> str:
    return os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")


class SelfUpdateSchedule(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        # Trigger Applicant's own updater; never write the upstream pending-update file.
        req = urllib.request.Request(
            f"{_engine()}/api/update/trigger",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode() or "{}")
            return {
                "success": True,
                "pending": False,
                "message": (
                    "Applicant update started — it rebuilds this fork from your local "
                    "checkout and reloads when ready. Track progress in Settings → "
                    "Self Update, or the sidebar Update panel."
                ),
                "applicant_update": data,
            }
        except Exception as e:
            return {
                "success": False,
                "error": (
                    f"Could not start the Applicant updater ({type(e).__name__}: {e}). "
                    "The built-in framework self-update is disabled here to protect your fork."
                ),
            }
