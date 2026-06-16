"""ViabilityScoring entity — can the user reasonably get this role? (FR-AGENT-3)."""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.ids import JobPostingId


@dataclass(frozen=True)
class ViabilityScoring:
    """Scores whether the user could reasonably get the role, from the JD.

    Distinct from ``ResumeFitScoring`` (coverage of a variant vs a JD).
    """

    posting_id: JobPostingId
    score: float  # 0.0..1.0
    rationale: str = ""
