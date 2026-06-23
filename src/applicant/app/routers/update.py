"""Update router — in-UI Update button via the `updater` sidecar (FR-OOBE-4, FR-INSTALL-2, NFR-ZEROCLI-1).

The `api` container CANNOT rebuild the stack itself: it has no Docker access, no
git checkout, and the update would restart the `api` container mid-run. So a
dedicated **`updater` sidecar** (Docker-socket access, the host repo bind-mounted)
watches a shared control volume and runs ``scripts/update.sh --apply`` against the
host Docker. This router is just the control plane:

  * ``POST /api/update/trigger`` — drop a request flag the sidecar picks up.
  * ``GET  /api/update``         — report the sidecar's state + recent log.

Control files live under ``UPDATE_CONTROL_DIR`` (default ``/control``, a named
volume shared with the updater):

  * ``request``       — touched by us; the updater consumes it and starts a run.
  * ``status.json``   — ``{state, message, started_at, finished_at}`` (updater writes).
  * ``update.log``    — ``update.sh`` output (updater writes).
  * ``updater.alive`` — heartbeat the updater touches each loop; its presence +
                        freshness is how we know the one-click updater is deployed.

Safe by default: with no fresh heartbeat (e.g. the updater isn't deployed yet, as
in tests/dev) the trigger is a no-op that explains how to enable it — nothing
destructive ever runs from this process. Gated behind the LLM-settings gate (FR-UI-5).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends

from applicant.app.deps import require_llm_configured
from applicant.ports.driving.update_trigger import UpdateResult

router = APIRouter(prefix="/api/update", tags=["update"], dependencies=[Depends(require_llm_configured)])

#: The updater touches ``updater.alive`` every few seconds; treat it as deployed
#: only while that heartbeat is fresh.
_ALIVE_WINDOW_S = 60
#: How many trailing lines of the update log the UI shows.
_LOG_TAIL_LINES = 60


def _default_control_dir() -> Path:
    return Path(os.environ.get("UPDATE_CONTROL_DIR", "/control"))


class UpdateTrigger:
    """``UpdateTriggerPort`` adapter — the control plane for the updater sidecar.

    Writes a request flag the sidecar consumes and reads back its state + log.
    When the sidecar isn't deployed (no fresh heartbeat) the trigger is a safe
    no-op so tests/dev and un-bootstrapped deployments never mutate anything.
    """

    def __init__(self, control_dir: Path | None = None) -> None:
        self._dir = Path(control_dir) if control_dir is not None else _default_control_dir()

    # -- control-file helpers ---------------------------------------------
    def _updater_alive(self) -> bool:
        beat = self._dir / "updater.alive"
        try:
            return beat.is_file() and (time.time() - beat.stat().st_mtime) < _ALIVE_WINDOW_S
        except OSError:
            return False

    def _read_status(self) -> dict:
        try:
            data = json.loads((self._dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"state": "idle", "message": "", "started_at": None, "finished_at": None}
        if not isinstance(data, dict):
            return {"state": "idle", "message": "", "started_at": None, "finished_at": None}
        return data

    def _log_tail(self) -> list[str]:
        try:
            text = (self._dir / "update.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return text.splitlines()[-_LOG_TAIL_LINES:]

    # -- driving API -------------------------------------------------------
    def status(self) -> dict:
        """Full update-surface status for the UI (soft — never raises)."""
        st = self._read_status()
        return {
            "surface": "update",
            "state": st.get("state", "idle"),
            "message": st.get("message", ""),
            "started_at": st.get("started_at"),
            "finished_at": st.get("finished_at"),
            "log_tail": self._log_tail(),
            "updater_available": self._updater_alive(),
        }

    def trigger_update(self) -> UpdateResult:
        if not self._updater_alive():
            return UpdateResult(
                started=False,
                message=(
                    "The one-click updater isn't running yet. Update once the normal way "
                    "(scripts/update.sh --apply on the host) to deploy it; after that this "
                    "button updates Applicant for you."
                ),
            )
        if self._read_status().get("state") == "running":
            return UpdateResult(started=False, message="An update is already in progress.")
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / "request").write_text(str(time.time()), encoding="utf-8")
        except OSError as exc:
            return UpdateResult(started=False, message=f"Could not request an update: {exc}")
        return UpdateResult(started=True, message="Update requested — Applicant is updating in the background.")


@router.get("")
def index() -> dict:
    """Update-surface status (FR-OOBE-4) — drives the in-UI Update button."""
    return UpdateTrigger().status()


@router.post("/trigger")
def trigger() -> dict:
    """Request a one-click update (FR-OOBE-4). Safe by default (no-op without the updater)."""
    result = UpdateTrigger().trigger_update()
    return {"started": result.started, "message": result.message}
