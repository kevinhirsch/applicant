"""Update router — in-UI Update button (FR-OOBE-4, FR-INSTALL-2, NFR-ZEROCLI-1).

# STAGE B — owned by Phase 4. Implements the ``UpdateTriggerPort``: the in-settings
# Update button invokes the one-liner update script (DB backup, migrations, rollback)
# without SSH/CLI (NFR-ZEROCLI-1).
#
# SAFETY: the script call is **stubbed and guarded**. It NEVER runs by default;
# the operator must set APPLICANT_UPDATE_ENABLED=1 *and* the script must exist for
# a real invocation to be dispatched. Otherwise we return a non-destructive "would
# run" result so the surface is testable without touching a real deployment.
Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured
from applicant.ports.driving.update_trigger import UpdateResult

router = APIRouter(prefix="/api/update", tags=["update"], dependencies=[Depends(require_llm_configured)])

#: Path to the one-liner update script (scripts/update.sh). Resolved from repo root.
_UPDATE_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "update.sh"


class UpdateTrigger:
    """``UpdateTriggerPort`` adapter — dispatches the guarded update script.

    Real dispatch is opt-in (APPLICANT_UPDATE_ENABLED=1) so tests and dev never
    mutate a deployment. The dry-run path reports what *would* happen (FR-OOBE-4).
    """

    def __init__(self, script_path: Path = _UPDATE_SCRIPT) -> None:
        self._script = script_path

    def trigger_update(self) -> UpdateResult:
        enabled = os.environ.get("APPLICANT_UPDATE_ENABLED") == "1"
        if not self._script.exists():
            return UpdateResult(started=False, message="Update script not found; nothing run.")
        if not enabled:
            return UpdateResult(
                started=False,
                message=(
                    f"Dry run: would invoke {self._script.name} "
                    "(backup DB, run migrations, support rollback). "
                    "Set APPLICANT_UPDATE_ENABLED=1 to enable."
                ),
            )
        # Real (opt-in) dispatch — detached so the UI returns immediately.
        import subprocess  # local import: only loaded on real dispatch

        subprocess.Popen(  # noqa: S603 - script path is repo-fixed, not user input
            ["/bin/bash", str(self._script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return UpdateResult(started=True, message=f"Started {self._script.name} (background).")


@router.get("")
def index() -> dict:
    return {"surface": "update", "status": "live", "phase": 4}


@router.post("/trigger")
def trigger() -> dict:
    """Invoke the guarded one-liner update (FR-OOBE-4). Safe by default (dry-run)."""
    result = UpdateTrigger().trigger_update()
    return {"started": result.started, "message": result.message}
