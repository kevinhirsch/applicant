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
class VariantSubmission:
    """One submission of a variant to a posting, with its interview outcome (#289).

    The cross-surface link the document library needs: which posting this variant was
    sent to, and whether it led to an interview. ``converted`` flips True when the
    application reached an interview so the variant's conversion rate can be derived.
    """

    posting_id: JobPostingId
    converted: bool = False


@dataclass(frozen=True)
class ResumeVariant:
    """A forked resume variant with parent lineage (FR-RESUME-6).

    Only ``approved`` variants are reusable as parents. ``parent_id`` is ``None``
    for the base/root variant.

    ``submissions`` records the per-posting submission/outcome history (#289) so the
    document library has cross-surface visibility into which job each variant was
    submitted to and how it converted — exposed via the always-present (never ``None``)
    :attr:`submitted_posting_id` and :attr:`conversion_rate` accessors.
    """

    id: ResumeVariantId
    campaign_id: CampaignId
    storage_path: str  # docx/tex source
    parent_id: ResumeVariantId | None = None  # lineage
    targeted_jd_signature: str | None = None
    approved: bool = False
    fit_scores: dict = field(default_factory=dict)
    submissions: tuple[VariantSubmission, ...] = ()

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def submitted_posting_id(self) -> tuple[JobPostingId, ...]:
        """The postings this variant was submitted to (#289), newest first.

        Always a tuple (never ``None``) so the library can render "submitted to" without
        a null check; empty when the variant has never been submitted.
        """
        return tuple(s.posting_id for s in self.submissions)

    @property
    def conversion_rate(self) -> float:
        """Share of this variant's submissions that led to an interview (#289).

        ``0.0`` when there are no submissions yet — always a number, never ``None``, so
        the document library can surface a conversion signal per variant.
        """
        if not self.submissions:
            return 0.0
        converted = sum(1 for s in self.submissions if s.converted)
        return converted / len(self.submissions)
