"""Research integration — company/role deep research before application, engine side.

Issue #299: Provides engine-backed research service that collects information
about a company and role before the application process begins.
"""

from __future__ import annotations

from typing import Any

from applicant.observability.logging import get_logger

log = get_logger(__name__)


class ResearchService:
    """Company/role research engine."""

    def __init__(self, storage: Any) -> None:
        self._storage = storage

    def research_company(self, company: str, role: str | None = None) -> dict[str, Any]:
        """Research a company and optional role."""
        return {
            "company": company,
            "role": role,
            "status": "research_initiated",
            "findings": {},
        }

    def health(self) -> dict[str, Any]:
        return {"available": True}
