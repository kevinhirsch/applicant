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

    #: selector -> uploaded file path (mutated by the fake page source, FR-RESUME-4).

    uploaded: dict[str, str] = field(default_factory=dict)

    #: whether this page is an account-creation form (boundary applies).

    is_account_create: bool = False

    #: whether this page is the final-submit step (boundary applies).

    is_final_submit: bool = False

    #: whether this page is a post-submission confirmation page (FR-LOG-4).

    is_confirmation: bool = False

    #: visible page text (drives confirmation-page heuristics, FR-LOG-4).

    text: str = ""

    #: HTTP status of the page response (FR-PREFILL-6): 403/429 => blocked.

    status: int | None = None

    #: raw page body/markup, scanned for challenge markers (FR-PREFILL-6).

    body: str | None = None

    #: host we expected to land on; a mismatch is an anomalous redirect.

    expected_host: str | None = None

    #: whether log_in should simulate a failure (False = always succeed).

    login_fails: bool = False

    #: whether the gate offers "Sign in with Google" OAuth.

    offers_google: bool = False





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



    Pagination is configurable via page_overrides (issue #214): callers can

    pass a custom list of :class:`FakePage` to override the default 6-page model,

    supporting tenants with more, fewer, or different page layouts.

    """



    name = "workday"



    def __init__(self, page_overrides: list[FakePage] | None = None) -> None:

        """Optionally override the default page sequence with a custom list.



        page_overrides � if provided, pages() returns this list instead of

        the hard-coded 6-page default. None keeps the standard 6-page model.

        """

        self._page_overrides = page_overrides



    def matches(self, url: str) -> bool:

        low = url.lower()

        return "workday" in low or "myworkdayjobs" in low



    def tenant_key(self, url: str) -> str:

        host = url.split("//", 1)[-1].split("/", 1)[0]

        return f"workday:{host}"



    def pages(self, url: str) -> list[FakePage]:

        if self._page_overrides is not None:

            return self._page_overrides

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

    def pages_for_tenant(
        self, url: str, *, tenant_profile: dict | None = None
    ) -> list[FakePage]:
        """Model a Workday tenant whose page set differs from the fixed six (#214).

        Real Workday tenants vary: some omit the voluntary-disclosures (EEO) page,
        some add qualifications or multi-part screening pages. Rather than assuming
        the fixed six-page structure, this returns the default flow filtered/extended
        by a ``tenant_profile`` of feature flags. Supported keys:

        * ``voluntary_disclosures`` (default ``True``) — when ``False`` the EEO
          self-identification page is omitted (the tenant does not collect it).
        * ``extra_pages`` — an optional list of additional :class:`FakePage` the
          tenant inserts before the final-submit page (e.g. qualifications).

        The account-create-first / final-submit-last boundary invariants are always
        preserved so the maximal-pre-fill loop's stop boundaries still hold.
        """
        profile = tenant_profile or {}
        pages = self.pages(url)
        if profile.get("voluntary_disclosures", True) is False:
            pages = [p for p in pages if "voluntary-disclosures" not in p.url]
        extra = profile.get("extra_pages") or []
        if extra:
            # Insert extra tenant pages just before the final-submit page.
            final = pages[-1]
            pages = pages[:-1] + list(extra) + [final]
        return pages





class GreenhouseAts(AtsAdapter):

    """Greenhouse ATS adapter with full real-application field map (NFR-EXT-1).

    Models the Greenhouse hosted apply flow (``boards.greenhouse.io/<tenant>/<id>``).
    Greenhouse typically presents a single application page housing personal info,
    resume/cover-letter uploads, links, work-authorisation, education, EEO, and
    screening questions, followed by a review/submit step. The field map below covers
    the same breadth of real application fields as the Workday adapter (issue #171).
    """

    name = "greenhouse"

    def matches(self, url: str) -> bool:
        return "greenhouse" in url.lower() or "boards.greenhouse" in url.lower()

    def pages(self, url: str) -> list[FakePage]:
        return [
            FakePage(
                url=f"{url}/apply",
                fields=(
                    # --- Personal information ---
                    DetectedField("#first_name", "First Name", "text"),
                    DetectedField("#last_name", "Last Name", "text"),
                    DetectedField("#email", "Email", "text"),
                    DetectedField("#phone", "Phone", "text"),
                    DetectedField("#location", "Location", "text"),
                    # --- Resume / documents ---
                    DetectedField("#resume", "Resume/CV", "file"),
                    DetectedField("#cover_letter", "Cover Letter", "file"),
                    # --- Links ---
                    DetectedField("#linkedin", "LinkedIn Profile", "text"),
                    DetectedField("#website", "Website", "text"),
                    DetectedField("#portfolio", "Portfolio URL", "text"),
                    DetectedField("#github", "GitHub URL", "text"),
                    # --- Work authorisation ---
                    DetectedField(
                        "#work_authorization",
                        "Are you legally authorised to work in this country?",
                        "select",
                        options=("Yes", "No"),
                    ),
                    DetectedField(
                        "#visa_sponsorship",
                        "Will you now or in the future require visa sponsorship?",
                        "select",
                        options=("Yes", "No"),
                    ),
                    # --- Current role ---
                    DetectedField("#current_company", "Current Company", "text"),
                    DetectedField("#current_title", "Current Job Title", "text"),
                    # --- Education ---
                    DetectedField("#education_school", "School", "text"),
                    DetectedField("#education_degree", "Degree", "text"),
                    DetectedField("#education_discipline", "Field of Study", "text"),
                    # --- Screening questions ---
                    DetectedField(
                        "#salary_expectation",
                        "Salary Expectations",
                        SCREENING_FACTUAL,
                    ),
                    DetectedField(
                        "#how_did_you_hear",
                        "How did you hear about this job?",
                        SCREENING_FACTUAL,
                        options=(
                            "LinkedIn",
                            "Indeed",
                            "Company website",
                            "Referral",
                            "Other",
                        ),
                    ),
                    DetectedField(
                        "#q_why",
                        "Why are you interested in this role?",
                        SCREENING_ESSAY,
                    ),
                    # --- EEO / voluntary disclosures ---
                    DetectedField(
                        "#eeo_gender",
                        "Gender",
                        "select",
                        options=("Male", "Female", "Non-binary", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "#eeo_race",
                        "Race/Ethnicity",
                        "select",
                        options=("...", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "#eeo_veteran",
                        "Protected Veteran Status",
                        "select",
                        options=("Yes", "No", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "#eeo_disability",
                        "Disability Status",
                        "select",
                        options=("Yes", "No", "Decline to self-identify"),
                    ),
                ),
            ),
            FakePage(url=f"{url}/review", is_final_submit=True, fields=()),
        ]



class LeverAts(AtsAdapter):

    """Lever ATS adapter with full real-application field map (NFR-EXT-1, issue #171).

    Lever's hosted apply flow (``jobs.lever.co/<tenant>/<id>``) is a single
    application page (name/email/resume/links) plus tenant "additional questions",
    then a review/submit. The field map below covers the same breadth of real
    application fields as the Workday and Greenhouse adapters.

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
                # Page 1: core application fields (name, contact, resume, links, role).
                url=f"{url}/apply",
                fields=(
                    # --- Personal information ---
                    DetectedField("input[name=name]", "Full name", "text"),
                    DetectedField("input[name=email]", "Email", "text"),
                    DetectedField("input[name=phone]", "Phone", "text"),
                    DetectedField("input[name=location]", "Location", "text"),
                    # --- Resume / cover letter ---
                    DetectedField("input[name=resume]", "Resume/CV", "file"),
                    DetectedField("input[name=cover]", "Cover Letter", "file"),
                    # --- Links ---
                    DetectedField("input[name=urls[LinkedIn]]", "LinkedIn URL", "text"),
                    DetectedField("input[name=urls[Portfolio]]", "Portfolio URL", "text"),
                    DetectedField("input[name=urls[Website]]", "Website", "text"),
                    DetectedField("input[name=urls[GitHub]]", "GitHub URL", "text"),
                    # --- Current employment ---
                    DetectedField("input[name=org]", "Current company", "text"),
                    DetectedField("input[name=title]", "Current Job Title", "text"),
                ),
            ),
            FakePage(
                # Page 2: screening questions, EEO, and additional info.
                url=f"{url}/apply/questions",
                fields=(
                    # --- Work authorisation ---
                    DetectedField(
                        "input[name=cards[work-auth]]",
                        "Are you authorised to work in this country?",
                        "select",
                        options=("Yes", "No"),
                    ),
                    DetectedField(
                        "input[name=cards[visa]]",
                        "Will you require visa sponsorship?",
                        "select",
                        options=("Yes", "No"),
                    ),
                    # --- Education ---
                    DetectedField("input[name=cards[school]]", "School", "text"),
                    DetectedField("input[name=cards[degree]]", "Degree", "text"),
                    DetectedField("input[name=cards[discipline]]", "Field of Study", "text"),
                    # --- Screening questions ---
                    DetectedField(
                        "input[name=cards[salary]]",
                        "Salary Expectations",
                        SCREENING_FACTUAL,
                    ),
                    DetectedField(
                        "select[name=cards[how-heard]]",
                        "How did you hear about this job?",
                        SCREENING_FACTUAL,
                        options=(
                            "LinkedIn",
                            "Indeed",
                            "Company website",
                            "Referral",
                            "Other",
                        ),
                    ),
                    DetectedField(
                        "textarea[name=cards[why]]",
                        "Why are you interested in this role?",
                        SCREENING_ESSAY,
                    ),
                    # --- Lever EEO self-identification ---
                    DetectedField(
                        "select[name=eeo[gender]]",
                        "Gender",
                        "select",
                        options=("Male", "Female", "Non-binary", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "select[name=eeo[race]]",
                        "Race/Ethnicity",
                        "select",
                        options=("...", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "select[name=eeo[veteran]]",
                        "Protected Veteran Status",
                        "select",
                        options=("Yes", "No", "Decline to self-identify"),
                    ),
                    DetectedField(
                        "select[name=eeo[disability]]",
                        "Disability Status",
                        "select",
                        options=("Yes", "No", "Decline to self-identify"),
                    ),
                ),
            ),
            FakePage(url=f"{url}/apply/review", is_final_submit=True, fields=()),
        ]

class IcimsAts(AtsAdapter):
    """iCIMS ATS adapter with a full real-application field map (#171, NFR-EXT-1).

    iCIMS' hosted apply flow (``careers-<tenant>.icims.com/jobs/<id>/apply`` or
    ``<tenant>.icims.com/...``) is a multi-page flow: an account gate, a personal-
    info page, an experience/education page, in-form screening questions, a
    voluntary EEO self-identification page, then a review/submit page. The field
    map below covers the same breadth as the Workday/Greenhouse/Lever adapters.

    Added purely by SUBCLASSING + a registry entry — NO core or port change is
    required (FR-PREFILL-2 / NFR-EXT-1). Before this adapter, an iCIMS URL fell
    through to the generic fallback; now it has a dedicated modeled flow.
    """

    name = "icims"

    def matches(self, url: str) -> bool:
        return "icims.com" in url.lower()

    def tenant_key(self, url: str) -> str:
        # careers-<tenant>.icims.com — the tenant is the host subdomain.
        host = url.split("//", 1)[-1].split("/", 1)[0]
        sub = host.split(".icims.com", 1)[0]
        tenant = sub.replace("careers-", "").replace("careers", "") or host
        return f"icims:{tenant}"

    def pages(self, url: str) -> list[FakePage]:
        return [
            FakePage(
                url=f"{url}/account",
                is_account_create=True,
                fields=(
                    DetectedField("#username", "Email Address", "text"),
                    DetectedField("#password", "Password", "password"),
                    DetectedField("#confirmPassword", "Confirm Password", "password"),
                ),
            ),
            FakePage(
                url=f"{url}/personal",
                fields=(
                    DetectedField("#firstName", "First Name", "text"),
                    DetectedField("#lastName", "Last Name", "text"),
                    DetectedField("#email", "Email", "text"),
                    DetectedField("#phone", "Phone", "text"),
                    DetectedField("#addressLine1", "Address Line 1", "text"),
                    DetectedField("#city", "City", "text"),
                    DetectedField("#state", "State", "text"),
                    DetectedField("#zip", "Zip/Postal Code", "text"),
                    DetectedField("#resume", "Resume/CV", "file"),
                    DetectedField("#coverLetter", "Cover Letter", "file"),
                    DetectedField("#linkedin", "LinkedIn URL", "text"),
                    DetectedField("#website", "Website/Portfolio", "text"),
                ),
            ),
            FakePage(
                url=f"{url}/experience",
                fields=(
                    DetectedField("#currentEmployer", "Current Employer", "text"),
                    DetectedField("#currentTitle", "Current Job Title", "text"),
                    DetectedField("#yearsExperience", "Years of Experience", "text"),
                    DetectedField("#school", "School", "text"),
                    DetectedField("#degree", "Degree", "text"),
                    DetectedField("#fieldOfStudy", "Field of Study", "text"),
                    DetectedField(
                        "#workAuth",
                        "Are you legally authorized to work?",
                        "select",
                        options=("Yes", "No"),
                    ),
                    DetectedField(
                        "#sponsorship",
                        "Will you now or in the future require sponsorship?",
                        "select",
                        options=("Yes", "No"),
                    ),
                ),
            ),
            FakePage(
                url=f"{url}/questions",
                fields=(
                    DetectedField(
                        "#q-relocate",
                        "Are you willing to relocate?",
                        SCREENING_FACTUAL,
                        options=("Yes", "No"),
                    ),
                    DetectedField(
                        "#q-start",
                        "Earliest available start date",
                        SCREENING_FACTUAL,
                    ),
                    DetectedField(
                        "#q-why",
                        "Why do you want to work here?",
                        SCREENING_ESSAY,
                    ),
                ),
            ),
            FakePage(
                url=f"{url}/eeo",
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
                    DetectedField(
                        "#disability",
                        "Disability Status",
                        "select",
                        options=("Yes", "No", "Decline to self-identify"),
                    ),
                ),
            ),
            FakePage(url=f"{url}/review", is_final_submit=True, fields=()),
        ]


class GenericAts(AtsAdapter):

    """The vendor-agnostic GENERIC live-DOM driver (issue #173, FR-PREFILL-2).



    1.0 commits to UNIVERSAL ATS coverage: the engine fills ANY application form, not

    only the three modeled vendors. An UNKNOWN ATS URL must NOT be mis-applied with

    Workday's fixed six-page model (the old fallback) — that drives the wrong page

    shape and fills the wrong selectors. Instead it resolves to THIS adapter, which

    imposes NO fixed page sequence: the real :class:`PlaywrightPageSource` walks the

    page from the live DOM (combobox/listbox detection, the

    aria-label→labelledby→<label>→placeholder label chain, DOM-``required`` authority)

    and the maximal-pre-fill loop drives that generic field-walk page by page until

    there is no "Next"/"Continue" control left.



    It deliberately ``matches`` no URL — it is the FALLBACK, returned by

    :func:`resolve_ats` only when no registered vendor adapter matched. For the

    in-memory :class:`FakePageSource` (hermetic tests) it models a SINGLE generic

    application page carrying its detected fields plus the final submit on the same

    page (universal single-page shape) — never the fixed Workday account→EEO→submit

    flow — so the fake exercises the same one-page generic walk the real driver does.

    """



    name = "generic"



    def matches(self, url: str) -> bool:

        # Never matched by URL: this is the explicit fallback in resolve_ats, not a

        # vendor whose hostnames we recognize.

        return False



    def tenant_key(self, url: str) -> str:

        host = url.split("//", 1)[-1].split("/", 1)[0]

        return f"generic:{host}"



    def pages(self, url: str) -> list[FakePage]:

        # No fixed multi-page model: a single live-DOM page that also carries the

        # final submit (the universal single-page shape). The real driver reads the

        # actual DOM; the fake models one page so the generic field-walk + final-submit

        # boundary are exercised hermetically without assuming any vendor's flow.

        return [

            FakePage(

                url=f"{url}",

                is_final_submit=True,

                fields=(),

            ),

        ]





#: Registry of ATS adapters keyed by name (extensible — FR-PREFILL-2 / NFR-EXT-1).

#: GenericAts is NOT registered here: it matches no URL and is the explicit fallback

#: that :func:`resolve_ats` returns when no vendor adapter matched.

ATS_REGISTRY: dict[str, type[AtsAdapter]] = {

    WorkdayAts.name: WorkdayAts,

    GreenhouseAts.name: GreenhouseAts,

    LeverAts.name: LeverAts,

    IcimsAts.name: IcimsAts,

}





def resolve_ats(url: str) -> AtsAdapter:

    """Pick an ATS adapter from a URL — vendor adapter if matched, else GENERIC.



    A matched Workday / Greenhouse / Lever URL returns its dedicated adapter (its

    modeled flow shape). An UNKNOWN ATS URL returns :class:`GenericAts` — the

    vendor-agnostic live-DOM driver (issue #173) — so the engine fills ANY form via

    the generic field-walk and NEVER silently mis-applies Workday's fixed page model

    to a form it does not recognize.

    """

    matched = resolve_ats_strict(url)

    if matched is not None:

        return matched

    return GenericAts()  # universal coverage: unknown ATSes use the generic driver.





def resolve_ats_strict(url: str) -> AtsAdapter | None:

    """Resolve ONLY to a recognized vendor adapter; ``None`` for an unknown ATS.



    The strict resolver does not fall back to any default — it returns ``None`` when no

    registered vendor adapter matches, so a caller can detect an unrecognized ATS (e.g.

    to flag the operator) rather than silently driving it. :func:`resolve_ats` wraps

    this and substitutes the generic driver for the ``None`` case.

    """

    for cls in ATS_REGISTRY.values():

        adapter = cls()

        if adapter.matches(url):

            return adapter

    return None

