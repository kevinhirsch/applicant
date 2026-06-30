"""Research router — company/role deep research API endpoint (#299)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from applicant.application.services.research_service import ResearchService

router = APIRouter(prefix="/api/research", tags=["research"])


def _get_service(request: Any) -> ResearchService:
    return request.app.state.container.research_service


@router.post("/company")
def research_company(
    company: str, role: str | None = None, svc: ResearchService = Depends(_get_service)
) -> dict[str, Any]:
    return svc.research_company(company, role)
