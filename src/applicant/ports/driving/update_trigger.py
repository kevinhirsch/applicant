"""UpdateTrigger driving port (FR-OOBE-4, FR-INSTALL-2).

Invoke the one-liner update script (DB backup, migrations, rollback) from the UI.
Live in Phase 4 (grayed until then).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class UpdateResult:
    started: bool
    message: str


@runtime_checkable
class UpdateTriggerPort(Protocol):
    """Inbound port for the in-UI Update button."""

    def trigger_update(self) -> UpdateResult: ...
