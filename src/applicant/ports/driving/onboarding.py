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

Conversational gather/refine (redesign-conversational-onboarding.md): after the
first-run wizard pass, the chat agent proactively asks about whatever required
fields are still blank. Two out-of-band tracking lists make that possible without
touching the completeness semantics above: ``omitted_sections`` (a whole section
the user explicitly declined — satisfies REQUIRED_SECTIONS without writing
anything into ``intake``, so it never reaches the attribute-cloud/criteria
bridges) and ``omitted_fields`` (per-section field keys the user declined, so the
gather loop stops asking about that one field without affecting section
completeness). ``INTAKE_FIELD_CATALOG`` is the single source of truth for field
labels/hints the gather loop phrases its questions with, mirroring the wizard's
own ``SECTIONS`` array (a0-applicant/webui/main.html) so the two never drift on
the field *set* (labels/hints may read slightly differently since one is a form
UI string and the other a spoken chat prompt).
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
class FieldSpec:
    """One catalog field: the key the intake dict stores it under, plus copy."""

    key: str
    label: str
    hint: str = ""


@dataclass(frozen=True)
class SectionCatalogEntry:
    """A section's chat-facing copy (title/hint) + its field catalog."""

    title: str
    hint: str
    fields: tuple[FieldSpec, ...] = ()


#: Single source of truth for intake field labels/hints the conversational gather
#: loop (``OnboardingService.next_gather_target``) phrases its questions with.
#: Mirrors ``a0-applicant/webui/main.html``'s ``SECTIONS`` array field-for-field —
#: see the module docstring. ``BASE_RESUME`` has no fields: it is upload-only and
#: is special-cased out of the gather loop (a chat answer cannot satisfy it).
INTAKE_FIELD_CATALOG: dict[IntakeSection, SectionCatalogEntry] = {
    IntakeSection.IDENTITY: SectionCatalogEntry(
        title="Identity",
        hint="How employers reach you.",
        fields=(
            FieldSpec("full_name", "Full legal name"),
            FieldSpec("email", "Email"),
            FieldSpec("phone", "Phone"),
        ),
    ),
    IntakeSection.WORK_AUTHORIZATION: SectionCatalogEntry(
        title="Work authorization",
        hint="Used only to filter roles you're eligible for — never AI-answered on applications.",
        fields=(
            FieldSpec("authorized", "Authorized to work?"),
            FieldSpec("sponsorship", "Need visa sponsorship?"),
        ),
    ),
    IntakeSection.LOCATION: SectionCatalogEntry(
        title="Location & work mode",
        hint="Where you'll work from and how.",
        fields=(
            FieldSpec("locations", "Preferred locations"),
            FieldSpec("work_mode", "Work mode"),
        ),
    ),
    IntakeSection.TARGET_ROLES: SectionCatalogEntry(
        title="Target roles",
        hint="The titles you want to be matched against.",
        fields=(FieldSpec("roles", "Roles / titles"),),
    ),
    IntakeSection.COMPENSATION: SectionCatalogEntry(
        title="Compensation",
        hint="Your minimum acceptable salary — used to screen postings.",
        fields=(FieldSpec("salary_floor", "Minimum salary"),),
    ),
    IntakeSection.WORK_HISTORY: SectionCatalogEntry(
        title="Work history",
        hint="Recent roles. A short summary is fine to start.",
        fields=(FieldSpec("summary", "Recent roles", "Company — Title — dates; …"),),
    ),
    IntakeSection.EDUCATION: SectionCatalogEntry(
        title="Education",
        hint="Highest degree and where.",
        fields=(
            FieldSpec("degree", "Highest degree"),
            FieldSpec("school", "School"),
        ),
    ),
    IntakeSection.REFERENCES: SectionCatalogEntry(
        title="References",
        hint="Optional — skip if you'd rather add these later.",
        fields=(FieldSpec("references", "References", "Name — relationship — contact"),),
    ),
    IntakeSection.CERTIFICATIONS: SectionCatalogEntry(
        title="Certifications",
        hint="Optional — any licenses or certifications.",
        fields=(FieldSpec("certifications", "Certifications"),),
    ),
    IntakeSection.KEY_ATTRIBUTES: SectionCatalogEntry(
        title="Key skills & attributes",
        hint="Skills that should surface in tailored materials.",
        fields=(FieldSpec("skills", "Key skills"),),
    ),
    IntakeSection.EEO: SectionCatalogEntry(
        title="Voluntary EEO",
        hint="Entirely optional and never AI-answered. Defaults to decline (FR-ATTR-6).",
        fields=(
            FieldSpec("race_ethnicity", "Race / ethnicity"),
            FieldSpec("gender", "Gender"),
            FieldSpec("veteran_status", "Veteran status"),
            FieldSpec("disability_status", "Disability status"),
        ),
    ),
    IntakeSection.BASE_RESUME: SectionCatalogEntry(
        title="Your Résumé",
        hint="Upload-only — a chat answer can't satisfy this; the agent can only remind you to upload it.",
        fields=(),
    ),
    IntakeSection.CAMPAIGN_CRITERIA: SectionCatalogEntry(
        title="Search criteria",
        hint="Confirms the titles / locations / salary floor this campaign searches on.",
        fields=(
            FieldSpec("titles", "Job titles"),
            FieldSpec("locations", "Locations"),
            FieldSpec("salary_floor", "Salary floor"),
        ),
    ),
}


@dataclass(frozen=True)
class GatherTarget:
    """The next thing the conversational gather loop should ask about.

    ``missing_fields`` is a list of ``{"key", "label", "hint"}`` dicts (catalog
    fields not yet answered and not marked omitted) for ``section``.
    """

    section: str
    title: str
    hint: str
    missing_fields: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class OnboardingState:
    """Snapshot of the resumable intake (FR-ONBOARD-2)."""

    campaign_id: str
    complete: bool
    sections_complete: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    intake: dict[str, Any] = field(default_factory=dict)
    #: True once the first-run wizard has been shown at least once (redesign
    #: §3.1) — gates the auto-popup banner, not the conversational gather loop.
    oobe_shown: bool = False
    #: Whole sections the user explicitly declined to answer (redesign §3.2.1).
    omitted_sections: list[str] = field(default_factory=list)
    #: Per-section field keys the user explicitly declined to answer, keyed by
    #: ``IntakeSection.value`` (redesign §3.2.1).
    omitted_fields: dict[str, list[str]] = field(default_factory=dict)


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
    # HONESTY: the number of details actually extracted from THIS parse (name /
    # email / phone found + skills + work-history + education entries) — NOT the
    # campaign's total attribute-cloud size, which includes details gathered
    # elsewhere and would inflate the "I read N details from your résumé" claim.
    parsed_field_count: int = 0
    # Resume-health self-check at upload: whether the uploaded resume's own
    # extractable text + parsed contact fields look ATS-recoverable, and why not
    # if they don't. Surfaced immediately at upload so a formatting problem (a
    # text-as-image render, a missing name/contact line, no recognizable section
    # headers) is an instant, actionable signal rather than a silent downstream
    # failure. Defaults are CONSERVATIVE: an unpopulated result must never read
    # as a healthy résumé.
    parseable: bool = False
    parseability_issues: list[str] = field(default_factory=list)
    #: Computed verdict ("good" / "issues" / "unreadable"); "unknown" only when
    #: the health check genuinely did not run.
    health_verdict: str = "unknown"


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

    def mark_shown(self, campaign_id: str) -> OnboardingState:
        """Record that the first-run wizard has been shown at least once (§3.1)."""
        ...

    def save_field(
        self, campaign_id: str, section: IntakeSection, field: str, value: Any
    ) -> OnboardingState:
        """Read-merge-write a single field into a section (conversational answer, §3.2.3).

        Unlike ``save_section`` (whole-section overwrite), this only touches the
        one named field — the rest of the section's already-saved fields survive.
        Answering a field that was previously marked omitted un-defers it.
        """
        ...

    def mark_field_omitted(
        self, campaign_id: str, section: IntakeSection, field: str, note: str = ""
    ) -> OnboardingState:
        """Record that the user explicitly declined one field (§3.2.1/§3.2.3)."""
        ...

    def mark_section_omitted(
        self, campaign_id: str, section: IntakeSection, note: str = ""
    ) -> OnboardingState:
        """Record that the user explicitly declined a whole section (§3.2.1/§3.2.3)."""
        ...

    def next_gather_target(self, campaign_id: str) -> GatherTarget | None:
        """The next required section (in fixed order) still owed an answer, or ``None``.

        Skips sections already complete or omitted, and ``BASE_RESUME`` (upload-only).
        Returns ``None`` once every required section is done-or-omitted (§3.2.3).
        """
        ...
