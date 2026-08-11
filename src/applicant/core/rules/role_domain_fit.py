"""Role domain-fit gate — is this role even IN Kevin's target profile?

Viability scoring's LLM rubric (``application/services/scoring_service.py``'s
``_llm_base`` ``system_text``, GATE 2) already carries natural-language
instructions telling the model to score off-domain roles low. In production
against a real discovery queue that instruction was NOT reliable enough on
its own: nearly every posting scored 85-100 regardless of role, including
titles with zero plausible relationship to agile delivery — "Key Accounts
Executive", "Senior Product Security Engineer II", "Sr. Video Editor
(short-form)", "Applied AI Architect", "Research Advisor" all landed in the
90s alongside real Scrum Master / RTE postings. Prompt-only calibration was
attempted twice and failed both times to hold under the full real-queue
distribution (a narrow labeled eval passing 0 FP/0 FN does not guarantee the
rubric generalizes to titles the eval never saw).

This module is a SECOND, DETERMINISTIC, no-LLM, no-IO line of defense,
mirroring :mod:`applicant.core.rules.posting_quality`'s design: given a
posting's title (primary signal) and description (fallback), it classifies
the ROLE — not the posting's authenticity, which is ``posting_quality``'s
job — into one of three buckets against Kevin's candidate taxonomy (a senior
Agile delivery leader: Scrum Master, RTE, Agile Coach, Delivery Manager,
Iteration Manager, agile-flavored TPM/Program Manager):

* **IN_DOMAIN** — the title plainly names one of Kevin's target role
  families. Caller should let the LLM/embedding fit score proceed normally
  (including the LeSS > SAFe taste preference) — this gate never lifts or
  boosts a score, it only ever prevents one.
* **OUT_OF_DOMAIN** — the title plainly names a role family that is
  categorically not agile-delivery work (IC/engineering-management software
  roles, product management/design, data science, sales, legal, finance,
  marketing, video editing, generic research). The caller should hard-cap
  the score low WITHOUT an LLM call — that is the whole point: a keyword-
  dense, senior-sounding, well-paid off-domain JD must never talk the LLM
  into a high score again.
* **UNCLASSIFIED** — neither list matches (an unfamiliar or ambiguous
  title, e.g. a bare "Program Manager" with no agile/delivery context
  anywhere). Caller should fall through to the normal LLM/embedding scoring
  path, unmodified — this gate is conservative by design and only fires
  on a clear signal, never on absence of one.

Precedence: IN_DOMAIN is checked before OUT_OF_DOMAIN, so a title carrying
both signals (e.g. "generic Engineering Manager" is out-of-domain per the
taxonomy, but "Engineering Manager, Agile Delivery" also contains the
in-domain phrase "Agile Delivery") resolves IN_DOMAIN — this mirrors the
product requirement that a generic Engineering Manager title is only
off-domain "unless explicitly agile-delivery".

Like ``posting_quality``, this is intentionally a curated pattern set, not an
ML classifier — extend the tuples below as new false positives/negatives are
observed in the live queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A role plainly IN Kevin's target profile — checked FIRST (see module
#: docstring precedence note). ``(label, pattern)`` pairs; the label is for
#: observability only, never branched on by callers.
_IN_DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Scrum Master", re.compile(r"\bscrum\s*master\b", re.IGNORECASE)),
    ("Release Train Engineer / RTE", re.compile(r"\brelease\s+train\s+engineer\b|\brte\b", re.IGNORECASE)),
    ("Agile Coach", re.compile(r"\bagile\s+coach\b", re.IGNORECASE)),
    ("Agile Delivery", re.compile(r"\bagile\s+delivery\b", re.IGNORECASE)),
    ("Delivery Manager / Lead", re.compile(r"\bdelivery\s+(manager|lead)\b", re.IGNORECASE)),
    ("Iteration Manager", re.compile(r"\biteration\s+manager\b", re.IGNORECASE)),
    ("Technical Program Manager / TPM", re.compile(r"\btechnical\s+program\s+manager\b|\btpm\b", re.IGNORECASE)),
    ("Agile Program Manager", re.compile(r"\bagile\s+program\s+manager\b", re.IGNORECASE)),
    ("Team Coach (SAFe SM/TC)", re.compile(r"\bteam\s+coach\b", re.IGNORECASE)),
)

#: A bare "Program Manager" (no Technical/Agile qualifier — those are matched
#: unconditionally above) is only IN_DOMAIN when agile/delivery CONTEXT is
#: present somewhere in the title or description — see module docstring.
#: "Program Manager, Robotics" or "Program Manager, Supply Chain" alone must
#: NOT be swept into scope just for containing the words "program manager".
_BARE_PROGRAM_MANAGER_RE = re.compile(r"\bprogram\s+manager\b", re.IGNORECASE)
_AGILE_DELIVERY_CONTEXT_RE = re.compile(
    r"\bagile\b|\bscrum\b|\bkanban\b|\bscaled\s+agile\b|\brelease\s+train\b|"
    r"\bpi\s+planning\b|\bagile\s+transformation\b|\bsafe\s+rte\b|"
    r"\bsafe\s+scrum\s+master\b",
    re.IGNORECASE,
)

#: A role plainly OUT of Kevin's target profile — checked only after the
#: IN_DOMAIN patterns above find nothing. ``(label, pattern)`` pairs.
_OUT_OF_DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # IC / engineering-discipline "<discipline> Engineer" titles — the
    # discipline word must be adjacent to "Engineer" (a bare "Engineer" with
    # no discipline stays UNCLASSIFIED, not OUT_OF_DOMAIN, on purpose: too
    # many neutral test/placeholder titles and legitimately ambiguous real
    # titles use "Engineer" alone).
    (
        "software/IC engineering discipline",
        re.compile(
            r"\b(software|security|devops|dev\s*ops|frontend|front-end|"
            r"backend|back-end|full[- ]?stack|data|platform|storage|"
            r"infrastructure|ml|machine\s+learning|site\s+reliability|sre)\s+"
            r"engineers?\b",
            re.IGNORECASE,
        ),
    ),
    ("Data Scientist / Data Science", re.compile(r"\bdata\s+scientists?\b|\bdata\s+science\b", re.IGNORECASE)),
    (
        "Applied AI Scientist/Architect/Researcher",
        re.compile(r"\bapplied\s+ai\s+(scientist|architect|researcher)s?\b", re.IGNORECASE),
    ),
    # PRODUCT manager/designer/UX — deliberately narrow so it never matches a
    # PROGRAM manager title (Program Manager may be in-domain; Product
    # Manager never is — see module docstring).
    ("Product Manager / Designer / UX", re.compile(r"\bproduct\s+(manager|designer)s?\b|\bux\s+(designer|researcher)s?\b", re.IGNORECASE)),
    ("Video Editor", re.compile(r"\bvideo\s+editors?\b", re.IGNORECASE)),
    ("Accounting / Finance", re.compile(r"\baccountants?\b|\baccounts?\s+payable\b|\bfinance\s+manager\b", re.IGNORECASE)),
    ("Legal / Counsel", re.compile(r"\bcounsels?\b|\blegal\b|\battorneys?\b", re.IGNORECASE)),
    ("Sales / Account Executive", re.compile(r"\bsales\b|\baccount\s+executives?\b|\bkey\s+accounts?\b", re.IGNORECASE)),
    ("Marketing", re.compile(r"\bmarketing\b|\bpaid\s+media\b", re.IGNORECASE)),
    ("Research Advisor", re.compile(r"\bresearch\s+advisors?\b", re.IGNORECASE)),
    # Generic software-engineering MANAGEMENT — "unless explicitly
    # agile-delivery" (handled by the IN_DOMAIN-checked-first precedence).
    (
        "generic Engineering Manager",
        re.compile(
            r"\bengineering\s+managers?\b|"
            r"\bmanager,?\s+software\s+engineering\b|"
            r"\b(senior\s+)?manager,\s*software\s+engineering\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class RoleDomainVerdict:
    """Outcome of the role domain-fit gate.

    ``in_domain`` is a tri-state, not a bool: ``True`` = plainly in Kevin's
    target profile, ``False`` = plainly out of it, ``None`` = unclassified
    (neither list matched — callers must treat this exactly like ``True``
    for gating purposes: only ``False`` should ever suppress a score).
    """

    in_domain: bool | None
    reason: str
    #: Short machine-readable tag for the signal that fired ("" when
    #: unclassified). For observability/debugging, not for branching on.
    signal: str = ""


def classify_role_domain(title: str, description: str = "") -> RoleDomainVerdict:
    """Classify ``title`` (primary) + ``description`` (fallback context)
    against Kevin's agile-delivery-leader target profile.

    Pure, deterministic, no IO. Checks the title first; the description is
    consulted only for the narrow "bare Program Manager needs agile/delivery
    context" case (module docstring) since the taxonomy's other categories
    are all unambiguous from the title alone in practice. Precedence:
    IN_DOMAIN patterns are checked before OUT_OF_DOMAIN ones, so a title
    that plainly names both (e.g. "Engineering Manager, Agile Delivery")
    resolves IN_DOMAIN.
    """
    title = (title or "").strip()
    description = (description or "").strip()

    if title:
        for label, pattern in _IN_DOMAIN_PATTERNS:
            if pattern.search(title):
                return RoleDomainVerdict(
                    in_domain=True,
                    reason=f'Title matches the in-domain role family "{label}": "{title}".',
                    signal="in_domain_title",
                )
        if _BARE_PROGRAM_MANAGER_RE.search(title):
            haystack = f"{title} {description}"
            if _AGILE_DELIVERY_CONTEXT_RE.search(haystack):
                return RoleDomainVerdict(
                    in_domain=True,
                    reason=(
                        'Title contains "Program Manager" AND agile/delivery '
                        f'context is present: "{title}".'
                    ),
                    signal="in_domain_program_manager_with_context",
                )
            # Bare Program Manager with NO agile/delivery context anywhere:
            # deliberately left UNCLASSIFIED (not OUT_OF_DOMAIN) — the
            # taxonomy names no generic-Program-Manager denylist entry, so
            # this falls through to the normal LLM/embedding path.
            return RoleDomainVerdict(
                in_domain=None,
                reason=(
                    'Title contains "Program Manager" but no agile/delivery '
                    f'context was found in the title or description: "{title}".'
                ),
                signal="",
            )
        for label, pattern in _OUT_OF_DOMAIN_PATTERNS:
            if pattern.search(title):
                return RoleDomainVerdict(
                    in_domain=False,
                    reason=f'Title matches the out-of-domain role family "{label}": "{title}".',
                    signal="out_of_domain_title",
                )

    return RoleDomainVerdict(
        in_domain=None,
        reason="No in-domain or out-of-domain role-family signal detected in the title.",
        signal="",
    )
