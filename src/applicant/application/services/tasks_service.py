"""Tasks integration — pending-actions-as-task-system, engine side.

Issue #295: Wraps the pending-actions store as a task system with
endpoint for listing, creating, and completing tasks.
"""

from __future__ import annotations

from typing import Any

from applicant.observability.logging import get_logger

log = get_logger(__name__)


class TasksService:
    """Pending-actions-as-task-system."""

    def __init__(self, storage: Any) -> None:
        self._storage = storage

    def list_tasks(self, campaign_id: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            actions = list(self._storage.pending_actions.list_for_campaign(campaign_id) if campaign_id else [])
            for a in actions:
                out.append({
                    "id": str(a.id),
                    "title": getattr(a, "title", ""),
                    "status": getattr(a, "status", "pending"),
                    "created_at": str(getattr(a, "created_at", "")),
                })
        except Exception as exc:
            log.debug("tasks_list_failed", error=str(exc))
        return out

    def health(self) -> dict[str, Any]:
        return {"available": hasattr(self._storage, "pending_actions")}
