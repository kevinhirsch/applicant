"""ATS abstraction + Workday adapter (FR-PREFILL-2).

A clean :class:`AtsAdapter` interface models the *shape* of an ATS application
flow as an ordered list of pages, each exposing detectable fields and flagging the
irreducible-human-step pages (account-create, final submit). The maximal-pre-fill
loop is therefore ATS-agnostic: a new ATS is a new :class:`AtsAdapter` subclass
registered in :data:`ATS_REGISTRY` with NO change to the core or the pre-fill
service (FR-PREFILL-2, NFR-EXT-1).

The :class:`WorkdayAts` adapter models the real Workday multi-page flow shape:
account-create -> personal info -> experience -> screening questions -> voluntary
EEO -> review/final-submit. Field metadata distinguishes sensitive EEO fields
(so the sensitive-field policy is exercised) and screening questions (factual vs
essay) so the pre-fill service can route them (FR-ANSWER-1 handoff).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.ports.driven.browser_automation import DetectedField


@dataclass
class FakePage:
    """An in-memory model of a single rendered page (NO real browser)."""

    url: str
    fields: tuple[DetectedField, ...] = ()
    detection_signals: tuple[str, ...] = ()
    #: selector -> filled value (mutated by the fake page source).
    filled: dict[str, str] = field(default_factory=dict)
    #: whether this page is an account-creation form (boundary applies).
    is_account_create: bool = False
    #: whether this page is the final-submit step (boundary applies).
    is_final_submit: bool = False
    #: whether this page is a post-submission confirmation page (FR-LOG-4).
    is_confirmation: bool = False
    #: visible page text (drives confirmation-page heuristics, FR-LOG-4).
    text: str = ""


class AtsAdapter:
    """Base ATS abstraction (FR-PREFILL-2): an ATS knows its page sequence.

    Concrete ATS adapters (Workday first) model the pages an application walks
    through and the fields each exposes, so the maximal-pre-fill loop is ATS
    agnostic. This is the swappable seam: new ATS = new subclass, no core change.
    """

    name = "generic"

    def matches(self, url: str) -> bool:  # pragma: no cover - overridden
        """True if this adapter handles ``url`` (used by :func:`resolve_ats`)."""
        return False

    def pages(self, url: str) -> list[FakePage]:  # pragma: no cover - overridden
        raise NotImplementedError

    def tenant_key(self, url: str) -> str:
        """Per-tenant profile key (FR-STEALTH-3). Default: the URL host."""
        host = url.split("//", 1)[-1].split("/", 1)[0]
        return f"{self.name}:{host}"


# Field-type tags the pre-fill service routes on (beyond the raw HTML type).
SCREENING_FACTUAL = "screening_factual"  # fill from stored attributes (FR-ANSWER-1)
SCREENING_ESSAY = "screening_essay"  # deferred to Phase 3 generation (FR-ANSWER-1)


class WorkdayAts(AtsAdapter):
    """Workday ATS adapter shape (FR-PREFILL-2: MVP-1 MUST work on Workday).

    Models the canonical Workday flow: an account-creation page (per-tenant),
    personal-info / experience / screening-question / voluntary-EEO pages, then
    final submit. Fields include sensitive EEO fields and both screening-question
    kinds so the full pre-fill policy surface is exercised.
    """

    name = "workday"

    def matches(self, url: str) -> bool:
        low = url.lower()
        return "workday" in low or "myworkdayjobs" in low

    def tenant_key(self, url: str) -> str:
        host = url.split("//", 1)[-1].split("/", 1)[0]
        return f"workday:{host}"

    def pages(self, url: str) -> list[FakePage]:
        return [
            FakePage(
                url=f"{url}/account/create",
                is_account_create=True,
                fields=(
                    DetectedField("#email", "Email Address", "text"),
                    DetectedField("#password", "Password", "password"),
                    DetectedField("#verify-password", "Verify Password", "password"),
                ),
            ),
            FakePage(
                url=f"{url}/application/personal",
                fields=(
                    DetectedField("#first-name", "First Name", "text"),
                    DetectedField("#last-name", "Last Name", "text"),
                    DetectedField("#phone", "Phone", "text"),
                    DetectedField("#address", "Address", "text"),
                ),
            ),
            FakePage(
                url=f"{url}/application/experience",
                fields=(
                    DetectedField("#current-title", "Current Job Title", "text"),
                    DetectedField("#years-exp", "Years of Experience", "text"),
                    DetectedField(
                        "#work-auth",
                        "Are you authorized to work?",
                        "select",
                        options=("Yes", "No"),
                    ),
                ),
            ),
            FakePage(
                # In-form screening questions: a factual one (fillable) and an
                # essay one (deferred to Phase 3 generation) (FR-ANSWER-1).
                url=f"{url}/application/questions",
                fields=(
                    DetectedField(
                        "#q-relocate",
                        "Are you willing to relocate?",
                        SCREENING_FACTUAL,
                        options=("Yes", "No"),
                    ),
                    DetectedField(
                        "#q-why",
                        "Why do you want to work here?",
                        SCREENING_ESSAY,
                    ),
                ),
            ),
            FakePage(
                # Voluntary self-identification (EEO) — sensitive fields here.
                url=f"{url}/application/voluntary-disclosures",
                fields=(
                    DetectedField(
                        "#gender",
                        "Gender",
                        "select",
                        options=("Male", "Female", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "#race",
                        "Race/Ethnicity",
                        "select",
                        options=("...", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "#veteran",
                        "Protected Veteran Status",
                        "select",
                        options=("Yes", "No", "Decline to self-identify"),
                    ),
                ),
            ),
            FakePage(
                url=f"{url}/application/review-submit",
                is_final_submit=True,
                fields=(),
            ),
        ]


class GreenhouseAts(AtsAdapter):
    """A SECOND ATS adapter, proving the abstraction is extensible (NFR-EXT-1).

    Not an MVP-1 target; it exists so the "new ATS = new subclass, no core change"
    claim is demonstrable. Greenhouse typically has no separate account-create page.
    """

    name = "greenhouse"

    def matches(self, url: str) -> bool:
        return "greenhouse" in url.lower() or "boards.greenhouse" in url.lower()

    def pages(self, url: str) -> list[FakePage]:
        return [
            FakePage(
                url=f"{url}/apply",
                fields=(
                    DetectedField("#first_name", "First Name", "text"),
                    DetectedField("#last_name", "Last Name", "text"),
                    DetectedField("#email", "Email", "text"),
                ),
            ),
            FakePage(url=f"{url}/review", is_final_submit=True, fields=()),
        ]


class LeverAts(AtsAdapter):
    """A THIRD ATS adapter shape, further proving the abstraction (NFR-EXT-1).

    Lever's hosted apply flow (``jobs.lever.co/<tenant>/<id>``) is a single
    application page (name/email/resume/links) plus tenant "additional questions",
    then a review/submit. Like Greenhouse it has no separate account-create page.
    Added purely by SUBCLASSING + registry entry — NO core or port change is
    required (FR-PREFILL-2 / NFR-EXT-1): the maximal-pre-fill loop walks ``pages``
    exactly as it does for Workday. Field-mapping knowledge (the per-label selectors)
    lives here and is shareable across campaigns via ``field_mappings`` (FR-ATTR-2).
    """

    name = "lever"

    def matches(self, url: str) -> bool:
        low = url.lower()
        return "lever.co" in low or "jobs.lever" in low

    def tenant_key(self, url: str) -> str:
        # jobs.lever.co/<tenant>/<posting-id> — the tenant is the first path segment.
        rest = url.split("lever.co/", 1)[-1]
        tenant = rest.split("/", 1)[0] if "/" in rest else rest
        return f"lever:{tenant}"

    def pages(self, url: str) -> list[FakePage]:
        return [
            FakePage(
                url=f"{url}/apply",
                fields=(
                    DetectedField("input[name=name]", "Full name", "text"),
                    DetectedField("input[name=email]", "Email", "text"),
                    DetectedField("input[name=phone]", "Phone", "text"),
                    DetectedField("input[name=org]", "Current company", "text"),
                    DetectedField("input[name=urls[LinkedIn]]", "LinkedIn URL", "text"),
                ),
            ),
            FakePage(
                # Lever "additional information" custom questions per tenant.
                url=f"{url}/apply/questions",
                fields=(
                    DetectedField(
                        "input[name=cards[work-auth]]",
                        "Are you authorized to work?",
                        SCREENING_FACTUAL,
                        options=("Yes", "No"),
                    ),
                    DetectedField(
                        "textarea[name=cards[why]]",
                        "Why are you interested in this role?",
                        SCREENING_ESSAY,
                    ),
                    # Lever surfaces EEO via its own self-identification card.
                    DetectedField(
                        "select[name=eeo[gender]]",
                        "Gender",
                        "select",
                        options=("Male", "Female", "Decline to self-identify"),
                    ),
                ),
            ),
            FakePage(url=f"{url}/apply/review", is_final_submit=True, fields=()),
        ]


#: Registry of ATS adapters keyed by name (extensible — FR-PREFILL-2 / NFR-EXT-1).
ATS_REGISTRY: dict[str, type[AtsAdapter]] = {
    WorkdayAts.name: WorkdayAts,
    GreenhouseAts.name: GreenhouseAts,
    LeverAts.name: LeverAts,
}


def resolve_ats(url: str) -> AtsAdapter:
    """Pick an ATS adapter from a URL (Workday default for MVP-1)."""
    for cls in ATS_REGISTRY.values():
        adapter = cls()
        if adapter.matches(url):
            return adapter
    return WorkdayAts()  # MVP-1 ships Workday; unknown ATSes default to it.
