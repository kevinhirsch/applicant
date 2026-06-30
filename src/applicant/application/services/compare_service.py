"""Cross-entity comparison engine — compare applications/postings side-by-side.

Issue #297: Backs the present-but-disabled Compare surface (#184). Provides
logic to compare attributes, scores, and outcomes across multiple entities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from applicant.observability.logging import get_logger

log = get_logger(__name__)


@dataclass
class ComparisonDimension:
    """One dimension of comparison."""
    key: str
    label: str
    values: dict[str, str]
    diff: str | None = None


@dataclass
class ComparisonResult:
    """Result of comparing multiple entities."""
    entity_ids: list[str]
    entity_labels: dict[str, str]
    dimensions: list[ComparisonDimension] = field(default_factory=list)
    summary: str | None = None


class CompareService:
    """Cross-entity comparison engine."""

    def __init__(self, storage: Any) -> None:
        self._storage = storage

    def compare_applications(
        self, application_ids: list[str], campaign_id: str | None = None
    ) -> ComparisonResult:
        # Campaign scoping (FR-CRIT-4): when a campaign is given, only the requested
        # ids that actually belong to that campaign are eligible — an id from another
        # campaign is excluded so a caller cannot compare across campaigns.
        allowed: set[str] | None = None
        if campaign_id is not None:
            allowed = {
                str(a.id)
                for a in self._storage.applications.list_for_campaign(campaign_id)
            }
        apps: list[Any] = []
        for aid in application_ids:
            if allowed is not None and str(aid) not in allowed:
                continue
            app = self._storage.applications.get(aid)
            if app is not None and (
                campaign_id is None or str(getattr(app, "campaign_id", "")) == str(campaign_id)
            ):
                apps.append(app)

        result = ComparisonResult(
            entity_ids=[str(a.id) for a in apps],
            entity_labels={str(a.id): getattr(a, "role_name", str(a.id)) or str(a.id) for a in apps},
        )

        if len(apps) < 2:
            result.summary = "Need at least 2 applications to compare."
            return result

        statuses = {str(a.id): str(getattr(a, "status", "unknown")) for a in apps}
        unique = set(statuses.values())
        result.dimensions.append(ComparisonDimension(
            key="status", label="Status", values=statuses,
            diff="All same" if len(unique) == 1 else f"{len(unique)} different statuses",
        ))

        job_titles = {str(a.id): getattr(a, "job_title", "N/A") or "N/A" for a in apps}
        result.dimensions.append(ComparisonDimension(
            key="job_title", label="Job Title", values=job_titles,
        ))

        result.summary = f"Compared {len(apps)} applications across {len(result.dimensions)} dimensions."
        return result

    def compare_postings(
        self, posting_ids: list[str], campaign_id: str | None = None
    ) -> ComparisonResult:
        # Campaign scoping (FR-CRIT-4): same guard as applications — a posting id
        # from another campaign is excluded from the comparison set.
        allowed: set[str] | None = None
        if campaign_id is not None:
            allowed = {
                str(p.id)
                for p in self._storage.postings.list_for_campaign(campaign_id)
            }
        postings: list[Any] = []
        for pid in posting_ids:
            if allowed is not None and str(pid) not in allowed:
                continue
            p = self._storage.postings.get(pid)
            if p is not None and (
                campaign_id is None or str(getattr(p, "campaign_id", "")) == str(campaign_id)
            ):
                postings.append(p)

        result = ComparisonResult(
            entity_ids=[str(p.id) for p in postings],
            entity_labels={str(p.id): getattr(p, "title", str(p.id)) for p in postings},
        )

        if len(postings) < 2:
            result.summary = "Need at least 2 postings to compare."
            return result

        titles = {str(p.id): getattr(p, "title", "N/A") for p in postings}
        result.dimensions.append(ComparisonDimension(key="title", label="Title", values=titles))

        companies = {str(p.id): getattr(p, "company", "N/A") for p in postings}
        result.dimensions.append(ComparisonDimension(key="company", label="Company", values=companies))

        locations = {str(p.id): getattr(p, "location", "N/A") or "N/A" for p in postings}
        result.dimensions.append(ComparisonDimension(key="location", label="Location", values=locations))

        result.summary = f"Compared {len(postings)} postings across {len(result.dimensions)} dimensions."
        return result
