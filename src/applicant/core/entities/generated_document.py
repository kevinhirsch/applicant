"""GeneratedDocument entity (FR-RESUME-1/10, FR-ANSWER-1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from applicant.core.ids import ApplicationId, CampaignId, GeneratedDocumentId


class DocumentType(str, Enum):
    """Kind of generated artifact.

    Beyond the three core generated kinds, the model also recognises **managed
    attachments** (#197): a ``PORTFOLIO`` and a generic ``ATTACHMENT`` kind cover the
    application materials a posting may demand that the engine does not itself author —
    portfolios, reference lists, transcripts, writing samples, certifications — so they
    can be carried per-campaign as first-class library documents.
    """

    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    SCREENING_ANSWER = "screening_answer"
    PORTFOLIO = "portfolio"
    ATTACHMENT = "attachment"

    @property
    def is_attachment(self) -> bool:
        """True for operator-supplied managed attachments (not engine-generated)."""
        return self in (DocumentType.PORTFOLIO, DocumentType.ATTACHMENT)


@dataclass(frozen=True)
class LearnedProvenance:
    """One learned item that actually shaped a generated draft (FR-MIND-5/-11).

    A small, descriptive transparency record surfaced as "What I drew on" in the
    review UI (FR-OBS-2). It is ADVISORY ONLY: it explains where the phrasing /
    approach came from, never confers authority and never implies a fact about
    the user (truthfulness FR-RESUME-2 is untouched — the fabrication guard still
    runs against the user's true source).

    ``kind`` is one of ``"memory"`` (a curated style/preference line), ``"playbook"``
    (a saved-playbook name), or ``"recall"`` (a prior similar application).
    ``label`` is the plain-language, first-person-friendly description shown to the
    user. ``ref`` is the stable item identifier (the memory line, the skill name,
    or the recall run-id) for traceability — never shown raw in the headline.
    """

    kind: str
    label: str
    ref: str = ""


@dataclass(frozen=True)
class GeneratedDocument:
    """A generated resume / cover-letter / screening-answer artifact.

    ``approved`` gates submission via the review gate (FR-RESUME-8). Generated
    material is never auto-submitted.

    ``provenance`` is a bounded, ADVISORY-ONLY transparency record (FR-MIND-5/-11,
    FR-OBS-2): which learned items (curated-memory lines, saved-playbook names, a
    prior-application recall) actually shaped this draft, surfaced in the review UI
    as "What I drew on". Descriptive, never authorization; defaults empty so
    behavior is byte-identical when no agent-memory substrate is wired.
    """

    id: GeneratedDocumentId
    campaign_id: CampaignId
    application_id: ApplicationId
    type: DocumentType
    content: str | None = None
    storage_path: str | None = None
    approved: bool = False
    provenance: tuple[LearnedProvenance, ...] = ()
