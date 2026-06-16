"""DocumentReview driving port (FR-RESUME-8, FR-ANSWER-1).

Interactive redline review + add/subtract/free-text revision loop for resume,
cover letter, and screening answers. No submission until approved.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.generated_document import GeneratedDocument
from applicant.core.entities.revision_session import RevisionSession
from applicant.core.ids import GeneratedDocumentId


@runtime_checkable
class DocumentReviewPort(Protocol):
    """Inbound port for the interactive review/revision gate."""

    def open_review(self, document_id: GeneratedDocumentId) -> RevisionSession: ...
    def submit_turn(self, document_id: GeneratedDocumentId, kind: str, instruction: str) -> RevisionSession:
        """Apply an add/subtract/free-text turn and return the updated session."""
        ...
    def approve(self, document_id: GeneratedDocumentId) -> GeneratedDocument:
        """Approve the material (passes the review gate, FR-RESUME-8)."""
        ...
    def decline(self, document_id: GeneratedDocumentId) -> GeneratedDocument: ...
