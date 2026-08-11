"""Role domain-fit gate — is this role even IN Kevin's target profile?

Viability scoring's LLM rubric (``application/services/scoring_service.py``'s
``_llm_base`` ``system_text``, GATE 2) already carries natural-language
instructions telling the model to score off-domain roles low. In production
that instruction was NOT reliable enough on its own — TWICE. The first
incident: nearly every posting scored 85-100 regardless of role, including
titles with zero plausible relationship to agile delivery ("Key Accounts
Executive", "Senior Product Security Engineer II", "Sr. Video Editor
(short-form)", "Applied AI Architect", "Research Advisor" all in the 90s).
A first fix added this module as a DENYLIST (named off-domain families —
"Software Engineer", "Product Manager", "Legal/Counsel", etc. — were capped;
everything else fell through to the LLM). That was deployed and re-scored
against the live queue, and the queue was STILL dominated by garbage the
denylist had no name for: YC "is hiring" announcements, a bare platform name
("LinkedIn") captured as a title, "Sr. Zendesk Developer", "Senior Salesforce
Engineer", "Affiliate EAP Counsellor", "Market Manager", "Startup
Partnerships Lead", "Partner Director - EMEA" — none of these match any
denylist entry, so they fell through UNCLASSIFIED to the LLM, which scored
them ~100 too. The LLM simply cannot discriminate reliably for this narrow a
profile — a growing denylist will always be one unseen title behind it.

**This module is therefore an ALLOWLIST, not a denylist.** A posting can
reach a viable score ONLY if its title plainly names one of Kevin's target
role families. Every other title — whether it plainly names a KNOWN
off-domain family (kept, for a more specific/legible rejection reason) or is
simply unrecognized — is capped. The LLM never sees a title this gate didn't
allow through, and never gets a chance to lift one back up; it only ever
RANKS among postings the allowlist already let through — both the LeSS >
SAFe taste preference, and (round 3) the deterministic ranking factors in
:mod:`applicant.core.rules.ranking_factors` (recency/pay/seniority/SAFe
penalty + the US-remote hard gate), which rank WITHIN this allowlisted set.

ROUND 3 WIDENING: Kevin is burnt out and now open to ANY fully-remote role
he can credibly do — not just agile-delivery-core titles. The allowlist
widened accordingly to also admit Program/Project Manager (bare — no longer
requires agile context, unlike the round-2 design), PMO, Portfolio/Program
Delivery Manager, and Delivery/Product/Program Operations, PLUS a
conditional bucket (Chief of Staff, Operations Manager/Lead, Business
Operations Lead) that requires delivery/program/agile CONTEXT in the title
or description, since those titles are too generic to admit unconditionally.
The denylist also grew two categories explicitly still out of scope: medical/
clinical and the skilled trades. US-remote-ness is now enforced entirely by
``ranking_factors.classify_remote`` as a SEPARATE hard gate in
``ScoringService`` — this module answers ONLY "is the role family right",
never location.

Given a posting's title (primary signal) and description (fallback, used
for the CONDITIONAL bucket's context check), :func:`classify_role_domain`
returns a tri-state verdict:

* **IN_DOMAIN** (``in_domain=True``) — the title plainly names a target role
  family (:data:`_IN_DOMAIN_PATTERNS`, unconditional) or a conditional one
  WITH context present (:data:`_CONDITIONAL_IN_DOMAIN_PATTERNS`). The caller
  lets the LLM/embedding fit score (then the ranking factors) proceed
  normally — this gate never lifts or boosts a score, it only ever prevents
  one.
* **OUT_OF_DOMAIN** (``in_domain=False``) — the title plainly names a KNOWN
  off-domain family (IC/engineering-management software roles, product
  management/design, data science, sales/partnerships, legal, finance,
  marketing, research, medical/clinical, trades). Kept as its own bucket
  purely for a more specific rejection ``reason`` string; gated identically
  to UNCLASSIFIED below.
* **UNCLASSIFIED** (``in_domain=None``) — neither list matches, OR a
  conditional title matched but no context was found. Under the OLD
  denylist posture this fell through to the LLM; under the CURRENT
  allowlist posture it is gated exactly like OUT_OF_DOMAIN — see
  :func:`is_allowlisted`, the single source of truth callers must use.

Precedence: IN_DOMAIN (unconditional) is checked before the CONDITIONAL
bucket, which is checked before OUT_OF_DOMAIN, so a title carrying multiple
signals (e.g. "generic Engineering Manager" is out-of-domain per the
taxonomy, but "Engineering Manager, Agile Delivery" also contains the
in-domain phrase "Agile Delivery") resolves IN_DOMAIN — this mirrors the
product requirement that a generic Engineering Manager title is only
off-domain "unless explicitly agile-delivery".

Like ``posting_quality``, the pattern lists are curated, not an ML
classifier — extend :data:`_IN_DOMAIN_PATTERNS` FIRST as new real in-profile
title phrasings are observed (a false negative here silently buries a real
role — the allowlist must stay comprehensive); extend
:data:`_OUT_OF_DOMAIN_PATTERNS` only for a nicer rejection reason, since an
unnamed off-domain title is already gated as UNCLASSIFIED regardless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A role plainly IN Kevin's target profile — checked FIRST (see module
#: docstring precedence note). ``(label, pattern)`` pairs; the label is for
#: observability only, never branched on by callers. Seniority prefixes
#: ("Senior"/"Lead"/"Principal"/"Sr.") need no separate entries — every
#: pattern here is a substring match, so e.g. "Senior Scrum Master" already
#: matches the bare "Scrum Master" pattern.
_IN_DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Scrum Master", re.compile(r"\bscrum\s*master\b", re.IGNORECASE)),
    ("Release Train Engineer / RTE", re.compile(r"\brelease\s+train\s+engineer\b|\brte\b", re.IGNORECASE)),
    (
        "Agile/Agility/Scrum/Kanban Coach",
        re.compile(r"\b(agile|agility|scrum|kanban)\s+coach\b", re.IGNORECASE),
    ),
    ("Agile Delivery", re.compile(r"\bagile\s+delivery\b", re.IGNORECASE)),
    ("Delivery Manager / Lead", re.compile(r"\bdelivery\s+(manager|lead)\b", re.IGNORECASE)),
    ("Iteration Manager", re.compile(r"\biteration\s+manager\b", re.IGNORECASE)),
    ("Technical Program Manager / TPM", re.compile(r"\btechnical\s+program\s+manager\b|\btpm\b", re.IGNORECASE)),
    ("Agile Program Manager", re.compile(r"\bagile\s+program\s+manager\b", re.IGNORECASE)),
    ("Team Coach (SAFe SM/TC)", re.compile(r"\bteam\s+coach\b", re.IGNORECASE)),
    ("Agile Transformation", re.compile(r"\bagile\s+transformation\b", re.IGNORECASE)),
    ("Ways of Working", re.compile(r"\bways\s+of\s+working\b", re.IGNORECASE)),
    # === ROUND 3 WIDENING: Program/Project management, admitted UNCONDITIONALLY
    # now (no longer requires agile/delivery context — Kevin is open to any
    # fully-remote role he can credibly do, and generic program/project
    # management is squarely in that range). "Portfolio Manager" is
    # DELIBERATELY not matched bare — it collides with a common FINANCE/
    # investment-management title; only the unambiguous compound "Program/
    # Portfolio Delivery Manager" phrasing is covered, via the "Delivery
    # Manager" pattern above.
    ("Program Manager", re.compile(r"\bprogram\s+managers?\b", re.IGNORECASE)),
    ("Project Manager", re.compile(r"\bproject\s+managers?\b", re.IGNORECASE)),
    ("PMO", re.compile(r"\bpmo\b", re.IGNORECASE)),
    (
        "Delivery/Product/Program Operations",
        re.compile(r"\b(delivery|product|program)\s+operations\b", re.IGNORECASE),
    ),
)

#: ROUND 3 WIDENING: titles too generic to admit unconditionally, but
#: plausibly in-domain when the title OR description shows real
#: delivery/program/agile substance. "Business Operations Lead"/"Business
#: Operations Manager" are covered by the same "Operations (Manager|Lead)"
#: pattern (substring match), no separate entry needed.
_CONDITIONAL_IN_DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Chief of Staff", re.compile(r"\bchief\s+of\s+staff\b", re.IGNORECASE)),
    ("Operations Manager / Lead", re.compile(r"\boperations\s+(manager|lead)s?\b", re.IGNORECASE)),
)
_DELIVERY_PROGRAM_CONTEXT_RE = re.compile(
    r"\bagile\b|\bscrum\b|\bkanban\b|\bscaled\s+agile\b|\brelease\s+train\b|"
    r"\bpi\s+planning\b|\bagile\s+transformation\b|\bsafe\s+rte\b|"
    r"\bsafe\s+scrum\s+master\b|\bdelivery\b|\bprogram\s+management\b|"
    r"\bpmo\b|\bportfolio\b|\bcross-functional\s+program\b|\bproduct\s+operations\b",
    re.IGNORECASE,
)

#: A role plainly, NAMEABLY out of Kevin's target profile — checked only
#: after the IN_DOMAIN patterns above find nothing. ``(label, pattern)``
#: pairs. NOTE: under the allowlist posture (see module docstring) this
#: bucket is gated IDENTICALLY to UNCLASSIFIED — it exists only to give a
#: more specific, legible rejection reason for known-common off-domain
#: families, not because matching it changes the outcome.
_OUT_OF_DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # IC / engineering-discipline "<discipline> Engineer" titles — the
    # discipline word must be adjacent to "Engineer".
    (
        "software/IC engineering discipline",
        re.compile(
            r"\b(software|security|devops|dev\s*ops|frontend|front-end|"
            r"backend|back-end|full[- ]?stack|data|platform|storage|"
            r"infrastructure|ml|machine\s+learning|site\s+reliability|sre|"
            r"salesforce|zendesk|qa|test|quality\s+assurance)\s+"
            r"engineers?\b|\bdevelopers?\b",
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
    (
        "Legal / Counsel",
        re.compile(r"\bcounsels?\b|\bcounsellors?\b|\bcounselors?\b|\blegal\b|\battorneys?\b", re.IGNORECASE),
    ),
    (
        "Sales / Account Executive / Partnerships",
        re.compile(
            r"\bsales\b|\baccount\s+executives?\b|\bkey\s+accounts?\b|\baes?\b|"
            r"\bpartnerships?\s+(lead|manager|director)\b|\bpartner\s+director\b",
            re.IGNORECASE,
        ),
    ),
    ("Marketing", re.compile(r"\bmarketing\b|\bpaid\s+media\b|\bmarket\s+manager\b", re.IGNORECASE)),
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
    # === ROUND 3 WIDENING: two more categories explicitly still out of scope.
    (
        "Medical / Clinical",
        re.compile(
            r"\bnurse\b|\bnursing\b|\bphysician\b|\bclinical\b|\btherapist\b|"
            r"\bpharmacist\b|\bdietitian\b|\bmedical\s+(director|assistant|officer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Trades",
        re.compile(
            r"\belectrician\b|\bplumber\b|\bcarpenter\b|\bwelder\b|\bhvac\b|"
            r"\bmechanic\b|\bmachinist\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class RoleDomainVerdict:
    """Outcome of the role domain-fit gate.

    ``in_domain`` is a tri-state, not a bool: ``True`` = plainly in Kevin's
    target profile, ``False`` = plainly, NAMEABLY out of it, ``None`` =
    unclassified (neither list matched). Do NOT branch on ``in_domain``
    directly for gating — use :func:`is_allowlisted`, which correctly
    treats ``False`` and ``None`` the same way (see module docstring: this
    is an ALLOWLIST, so only ``True`` passes).
    """

    in_domain: bool | None
    reason: str
    #: Short machine-readable tag for the signal that fired ("" when
    #: unclassified). For observability/debugging, not for branching on.
    signal: str = ""


def classify_role_domain(title: str, description: str = "") -> RoleDomainVerdict:
    """Classify ``title`` (primary) + ``description`` (fallback context)
    against Kevin's target profile.

    Pure, deterministic, no IO. Checks the title first; the description is
    consulted only for the CONDITIONAL bucket's context check (module
    docstring) since the unconditional/denylist categories are all
    unambiguous from the title alone in practice. Precedence: unconditional
    IN_DOMAIN patterns, then the CONDITIONAL bucket (with-context), then
    OUT_OF_DOMAIN — so a title that plainly names both an unconditional
    in-domain phrase and an out-of-domain one (e.g. "Engineering Manager,
    Agile Delivery") resolves IN_DOMAIN.

    Callers making a gating decision should use :func:`is_allowlisted` on
    the result rather than inspecting ``in_domain`` directly.
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
        for label, pattern in _CONDITIONAL_IN_DOMAIN_PATTERNS:
            if pattern.search(title):
                haystack = f"{title} {description}"
                if _DELIVERY_PROGRAM_CONTEXT_RE.search(haystack):
                    return RoleDomainVerdict(
                        in_domain=True,
                        reason=(
                            f'Title matches the conditional role family "{label}" AND '
                            f'delivery/program/agile context is present: "{title}".'
                        ),
                        signal="in_domain_conditional_with_context",
                    )
                # A conditional title matched but NO delivery/program/agile
                # context was found anywhere: UNCLASSIFIED, not an explicit
                # OUT_OF_DOMAIN denylist hit — but still gated by
                # is_allowlisted() exactly the same either way.
                return RoleDomainVerdict(
                    in_domain=None,
                    reason=(
                        f'Title matches the conditional role family "{label}" but no '
                        f'delivery/program/agile context was found in the title or '
                        f'description: "{title}".'
                    ),
                    signal="",
                )
        for label, pattern in _OUT_OF_DOMAIN_PATTERNS:
            if pattern.search(title):
                return RoleDomainVerdict(
                    in_domain=False,
                    reason=f'Title matches the known out-of-domain role family "{label}": "{title}".',
                    signal="out_of_domain_title",
                )

    return RoleDomainVerdict(
        in_domain=None,
        reason=(
            "Title does not plainly match any in-domain agile-delivery role "
            "family on the allowlist — gated (not a known match) rather than "
            "passed through to the LLM."
        ),
        signal="",
    )


def is_allowlisted(verdict: RoleDomainVerdict) -> bool:
    """The single source of truth for gating decisions (ALLOWLIST posture).

    ``True`` only when ``verdict.in_domain is True`` — an unclassified role
    (``None``) is gated exactly like an explicitly out-of-domain one
    (``False``); only a title that plainly matched the in-domain allowlist
    is let through to the LLM/embedding fit score. See the module docstring
    for why this replaced an earlier denylist-only posture (it left too many
    real off-domain titles — YC "is hiring" announcements, "Sr. Zendesk
    Developer", "Market Manager", "Partner Director - EMEA", etc. —
    unclassified and therefore un-gated).
    """
    return verdict.in_domain is True
