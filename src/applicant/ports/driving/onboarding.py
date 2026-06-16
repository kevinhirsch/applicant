"""Onboarding driving port (FR-ONBOARD-1/2/3, FR-ATTR-1/3/4).

The comprehensive Workday-ready intake (see docs/onboarding-intake.md): identity,
work authorization, location/work-mode, target roles, compensation, dated work
history, education, references, certifications, key attributes, explicit EEO
answers, base resume, and initial campaign criteria.

The intake is **persistent and resumable** across steps (FR-ONBOARD-2): partial
state is saved per step and a completion flag gates automated work. The base resume
bootstraps the per-campaign attribute cloud, reconciled with the interview answers
(FR-ONBOARD-3): non-integral changes auto-apply; integral changes require explicit
confirmation (FR-FB-3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class IntakeSection(str, Enum):
    """Resumable intake sections (docs/onboarding-intake.md §1-13)."""

    IDENTITY = "identity"
    WORK_AUTHORIZATION = "work_authorization"
    LOCATION = "location"
    TARGET_ROLES = "target_roles"
    COMPENSATION = "compensation"
    WORK_HISTORY = "work_history"
    EDUCATION = "education"
    REFERENCES = "references"
    CERTIFICATIONS = "certifications"
    KEY_ATTRIBUTES = "key_attributes"
    EEO = "eeo"
    BASE_RESUME = "base_resume"
    CAMPAIGN_CRITERIA = "campaign_criteria"


#: Sections that MUST be present (non-empty) for the intake to be complete and so
#: to satisfy the onboarding gate (FR-ONBOARD-2). The base resume is hard-required
#: (FR-ONBOARD-1): without it the attribute cloud cannot be bootstrapped and the
#: FR-ONBOARD-3 reconciliation would be silently skipped. References are part of the
#: Workday-ready comprehensive intake and are required too.
REQUIRED_SECTIONS: tuple[IntakeSection, ...] = (
    IntakeSection.IDENTITY,
    IntakeSection.WORK_AUTHORIZATION,
    IntakeSection.LOCATION,
    IntakeSection.TARGET_ROLES,
    IntakeSection.COMPENSATION,
    IntakeSection.WORK_HISTORY,
    IntakeSection.EDUCATION,
    IntakeSection.REFERENCES,
    IntakeSection.KEY_ATTRIBUTES,
    IntakeSection.EEO,
    IntakeSection.BASE_RESUME,
    IntakeSection.CAMPAIGN_CRITERIA,
)


@dataclass(frozen=True)
class OnboardingState:
    """Snapshot of the resumable intake (FR-ONBOARD-2)."""

    campaign_id: str
    complete: bool
    sections_complete: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    intake: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationConflict:
    """An integral parsed value that disagrees with an interview answer (FR-FB-3)."""

    attribute: str
    interview_value: str
    parsed_value: str


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of reconciling a parsed resume with interview answers (FR-ONBOARD-3)."""

    auto_applied: list[str] = field(default_factory=list)
    conflicts: list[ReconciliationConflict] = field(default_factory=list)
    attribute_count: int = 0


@runtime_checkable
class OnboardingPort(Protocol):
    """Inbound port for the Workday-ready onboarding intake."""

    def get_state(self, campaign_id: str) -> OnboardingState:
        """Return the resumable intake state (FR-ONBOARD-2)."""
        ...

    def save_section(
        self, campaign_id: str, section: IntakeSection, data: dict[str, Any]
    ) -> OnboardingState:
        """Persist one intake section's partial state (FR-ONBOARD-2)."""
        ...

    def complete(self, campaign_id: str) -> OnboardingState:
        """Set the completion flag iff every required section is present (FR-ONBOARD-2)."""
        ...

    def ingest_base_resume(
        self, campaign_id: str, document_path: str
    ) -> ReconciliationResult:
        """Parse the base resume and reconcile with interview answers (FR-ONBOARD-3)."""
        ...
