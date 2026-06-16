"""ResumeParser port (FR-ONBOARD-3, FR-ATTR-1).

Parses an uploaded base resume to bootstrap the per-campaign attribute cloud:
identity, work history (titles/companies/dates), education, and skills. Supports
docx and txt at minimum (PDF where cheap). The parsed structure is reconciled with
the interview answers by the onboarding service (auto-apply non-integral; require
confirmation for integral changes, FR-FB-3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class WorkHistoryEntry:
    title: str = ""
    company: str = ""
    start_date: str = ""
    end_date: str = ""
    location: str = ""


@dataclass(frozen=True)
class EducationEntry:
    degree: str = ""
    institution: str = ""
    start_year: str = ""
    end_year: str = ""


@dataclass(frozen=True)
class ParsedResume:
    """Structured data extracted from a base resume (FR-ONBOARD-3)."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    work_history: tuple[WorkHistoryEntry, ...] = ()
    education: tuple[EducationEntry, ...] = ()
    skills: tuple[str, ...] = ()
    detected_fonts: tuple[str, ...] = ()
    raw_text: str = ""
    extra: dict = field(default_factory=dict)


@runtime_checkable
class ResumeParserPort(Protocol):
    """Outbound port for base-resume parsing."""

    def parse(self, document_path: str) -> ParsedResume:
        """Parse a resume file (docx/txt/pdf) into structured data (FR-ONBOARD-3)."""
        ...
