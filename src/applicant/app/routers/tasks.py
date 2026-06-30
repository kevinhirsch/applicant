"""Tasks router — pending-actions-as-task-system API endpoint (#295)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from applicant.application.services.tasks_service import TasksService

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _get_service(request: Any) -> TasksService:
    return request.app.state.container.tasks_service


@router.get("/list")
def list_tasks(campaign_id: str | None = None, svc: TasksService = Depends(_get_service)) -> dict[str, Any]:
    return {"tasks": svc.list_tasks(campaign_id)}
