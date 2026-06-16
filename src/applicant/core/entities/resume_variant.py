"""ResumeVariant (+ lineage) and ResumeFitScoring entities (FR-RESUME-6/7)."""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.ids import CampaignId, JobPostingId, ResumeVariantId


@dataclass(frozen=True)
class ResumeFitScoring:
    """Coverage check of a variant against a JD (FR-RESUME-7).

    A coverage check, never a fabrication target (FR-RESUME-2).
    """

    variant_id: ResumeVariantId
    posting_id: JobPostingId
    coverage: float  # 0.0..1.0
    missing_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResumeVariant:
    """A forked resume variant with parent lineage (FR-RESUME-6).

    Only ``approved`` variants are reusable as parents. ``parent_id`` is ``None``
    for the base/root variant.
    """

    id: ResumeVariantId
    campaign_id: CampaignId
    storage_path: str  # docx/tex source
    parent_id: ResumeVariantId | None = None  # lineage
    targeted_jd_signature: str | None = None
    approved: bool = False
    fit_scores: dict = field(default_factory=dict)

    @property
    def is_root(self) -> bool:
        return self.parent_id is None
