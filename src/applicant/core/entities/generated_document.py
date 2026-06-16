"""GeneratedDocument entity (FR-RESUME-1/10, FR-ANSWER-1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from applicant.core.ids import ApplicationId, CampaignId, GeneratedDocumentId


class DocumentType(str, Enum):
    """Kind of generated artifact."""

    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    SCREENING_ANSWER = "screening_answer"


@dataclass(frozen=True)
class GeneratedDocument:
    """A generated resume / cover-letter / screening-answer artifact.

    ``approved`` gates submission via the review gate (FR-RESUME-8). Generated
    material is never auto-submitted.
    """

    id: GeneratedDocumentId
    campaign_id: CampaignId
    application_id: ApplicationId
    type: DocumentType
    content: str | None = None
    storage_path: str | None = None
    approved: bool = False
