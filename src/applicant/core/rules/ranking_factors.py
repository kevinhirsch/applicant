"""Deterministic RANKING factors — within the allowlisted set, which roles are
actually good for Kevin? (round-3 fix on top of role_domain_fit's allowlist.)

``role_domain_fit`` (relevance) and ``posting_quality`` (authenticity) answer
"is this even a role Kevin could take" — they gate VIABILITY. They do NOT
answer "is this a GOOD instance of that role for Kevin right now", and
leaving that entirely to the LLM produced exactly the next miscalibration:
a real, allowlisted, in-domain role (SAFe-heavy, ~30 days stale, paying
below Kevin's floor, not particularly senior) still scored 95 — Kevin's own
words: "too low pay, heavily SAFe, posted ~a month ago, not high-impact, no
idea why it scored so high." The LLM does not reliably apply any of these
factors on its own; they must be deterministic.

This module is a THIRD, deterministic, no-LLM, no-IO layer, mirroring
``posting_quality``/``role_domain_fit``'s design, split into two kinds:

* A HARD GATE — :func:`classify_remote`. Kevin requires FULL US-REMOTE,
  no exceptions for an otherwise-appealing role: confirmed non-remote
  (onsite/hybrid/a named location with no remote language) OR confirmed
  remote-but-not-from-the-US (e.g. "Remote, Bangalore") both fail. Genuinely
  AMBIGUOUS cases (no location signal at all, or "Remote" with no country
  either way) are left UNKNOWN — not gated, only noted — so a scraper gap
  (``work_mode``/``location`` NULL, common even on real, good, US-remote
  postings — see ``posting_quality``/``role_domain_fit``'s own fixtures)
  never silently buries a genuinely good role. ``ScoringService`` treats a
  confirmed-False verdict as a pre-LLM short-circuit, exactly like the other
  two gates (cheap, and the LLM can never rescue it).

* SIX RANKING multipliers — :func:`recency_multiplier`,
  :func:`safe_penalty_multiplier`, :func:`pay_multiplier`,
  :func:`seniority_multiplier`, :func:`fit_to_profile_multiplier`, and
  :func:`degree_requirement_multiplier`. These do NOT change viability; they
  scale the score AFTER the LLM/embedding judgment (and any learning bias)
  has already run, so a stale/SAFe-heavy/underpaid/junior/off-fit/
  degree-gated role still passes the allowlist and remote gate but settles
  lower in the ranking than a fresh/agnostic-or-LeSS/well-paid/senior/
  exact-fit one — closing exactly the gap Kevin reported.

ROUND 4 (:func:`fit_to_profile_multiplier` / :func:`degree_requirement_multiplier`):
after reading Kevin's actual résumé, the round-3 allowlist widening (any
fully-remote role he could credibly do) still ranked a same-freshness TPM
alongside a Scrum Master, even though Kevin's real title history is
EXCLUSIVELY Scrum Master/Agile Coach (Lead Scrum Master @ Wells Fargo,
Scrum Master @ Slalom/Ally, Principal Service Delivery Scrum Master @ Dell
EMC/Boeing) with Scrum/Agile certs (CSP-SM, A-CSM, CSM, SAFe SSM, KMP — no
PMP), no TPM/PM title history, and no bachelor's degree.
:func:`fit_to_profile_multiplier` boosts his EXACT-match role families
(Scrum Master, Agile/Team/Enterprise Agile Coach, Delivery Manager/Lead,
Iteration Manager, RTE) above the round-3-widened STRETCH families (TPM,
Program/Project Manager, PMO, Delivery/Product/Program Operations, Chief of
Staff, Operations Manager/Lead) — both stay VIABLE, but the exact-match
family ranks higher for an equivalent-freshness pair.
:func:`degree_requirement_multiplier` penalizes a posting whose description
HARD-requires a degree Kevin doesn't have (distinguishing "required" from
"preferred"/"or equivalent experience", which he satisfies).

Like its siblings, every list here is curated and pattern-based, not an ML
classifier — extend as new real-queue cases are observed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class RankingFactor:
    """One deterministic multiplier on the post-LLM viability score.

    ``multiplier`` is applied via multiplication (``score *= multiplier``);
    ``1.0`` is neutral (no adjustment — always the answer when the input
    data needed to judge the factor is missing, per this module's "don't
    over-penalize unknowns" rule, consistent with ``role_domain_fit``/
    ``posting_quality``).
    """

    multiplier: float
    reason: str


@dataclass(frozen=True)
class RemoteVerdict:
    """Outcome of the US-remote HARD gate (:func:`classify_remote`).

    Tri-state, like ``RoleDomainVerdict.in_domain``: ``True`` = confirmed
    full US-remote, ``False`` = confirmed NOT (onsite/hybrid, a named
    non-remote location, or remote-but-not-from-the-US), ``None`` =
    genuinely ambiguous/unstated — callers must NOT gate on ``None``, only
    on an explicit ``False`` (see module docstring).
    """

    is_us_remote: bool | None
    reason: str


# === recency decay ==========================================================
#: Full weight through day 7; noticeable decay by day 30 (Kevin's own
#: complaint: "posted ~a month ago" scored as if brand-new); a floor so an
#: old-but-otherwise-great posting is de-prioritized, never zeroed out.
_RECENCY_FULL_WEIGHT_DAYS = 7.0
_RECENCY_DAY_30_MULTIPLIER = 0.75
_RECENCY_DAY_60_MULTIPLIER = 0.55
_RECENCY_FLOOR_MULTIPLIER = 0.50


def recency_multiplier(date_posted: datetime | None, *, now: datetime | None = None) -> RankingFactor:
    """Decay the ranking by ``date_posted`` age. Missing date -> neutral 1.0
    (never penalize a posting for a scraper that didn't capture a date)."""
    if date_posted is None:
        return RankingFactor(1.0, "no posted date available -- not penalized")
    now = now or datetime.now(UTC)
    dp = date_posted
    try:
        if dp.tzinfo is None:
            dp = dp.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        age_days = (now - dp).total_seconds() / 86400.0
    except Exception:  # pragma: no cover - defensive against odd datetime inputs
        return RankingFactor(1.0, "posted date could not be compared -- not penalized")
    age_days = max(0.0, age_days)

    if age_days <= _RECENCY_FULL_WEIGHT_DAYS:
        mult = 1.0
    elif age_days <= 30.0:
        frac = (age_days - _RECENCY_FULL_WEIGHT_DAYS) / (30.0 - _RECENCY_FULL_WEIGHT_DAYS)
        mult = 1.0 - (1.0 - _RECENCY_DAY_30_MULTIPLIER) * frac
    elif age_days <= 60.0:
        frac = (age_days - 30.0) / 30.0
        mult = _RECENCY_DAY_30_MULTIPLIER - (
            _RECENCY_DAY_30_MULTIPLIER - _RECENCY_DAY_60_MULTIPLIER
        ) * frac
    else:
        mult = _RECENCY_FLOOR_MULTIPLIER
    mult = max(_RECENCY_FLOOR_MULTIPLIER, min(1.0, mult))
    return RankingFactor(round(mult, 4), f"posted {age_days:.0f} day(s) ago")


# === SAFe penalty (LeSS/agnostic > SAFe, deterministic) =====================
#: Curated SAFe-specific CONCEPTS, one pattern each, deliberately built to
#: be NON-OVERLAPPING (no pattern's match span is a subset of another's) so
#: a single phrase never double-counts as two markers — e.g. "SAFe RTE"
#: must count as ONE "safe" hit, not "safe" + "safe rte"; "Release Train
#: Engineer" must count as ONE "release train" hit, not "release train" +
#: "release train engineer". Deliberately does NOT include a bare "RTE" or
#: "ART" (both collide too easily with unrelated abbreviations/words) —
#: relies on the fuller phrases instead, which are what real postings use.
_SAFE_MARKER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsafe\b", re.IGNORECASE),
    re.compile(r"\bscaled\s+agile\b", re.IGNORECASE),
    re.compile(r"\b(agile\s+)?release\s+train(\s+engineer)?\b", re.IGNORECASE),
    re.compile(r"\bpi\s+planning\b|\bprogram\s+increment\b", re.IGNORECASE),
    re.compile(r"\btransformation\s+delivery\s+train\b", re.IGNORECASE),
    re.compile(r"\bscrum\s+of\s+scrums\b", re.IGNORECASE),
)
_SAFE_HEAVY_MULTIPLIER = 0.85  # >= 2 distinct markers
_SAFE_LIGHT_MULTIPLIER = 0.95  # exactly 1 marker


def safe_penalty_multiplier(title: str, description: str = "") -> RankingFactor:
    """Penalize SAFe-flavored roles so they rank BELOW a comparable LeSS/
    framework-agnostic role — a ranking nudge, never a viability gate: RTE
    and other SAFe roles stay fully VIABLE (Kevin is SAFe/RTE-certified),
    just not top-of-queue. Mirrors the taste preference already in the LLM
    rubric's ``system_text``, but deterministic so it always applies."""
    haystack = f"{title or ''} {description or ''}"
    count = sum(1 for pattern in _SAFE_MARKER_PATTERNS if pattern.search(haystack))
    if count >= 2:
        return RankingFactor(
            _SAFE_HEAVY_MULTIPLIER, f"{count} SAFe markers present -- ranked below LeSS/agnostic roles"
        )
    if count == 1:
        return RankingFactor(_SAFE_LIGHT_MULTIPLIER, "1 SAFe marker present -- light ranking penalty")
    return RankingFactor(1.0, "no SAFe markers detected")


# === pay floor ===============================================================
#: Kevin's target compensation (module docstring / coordinator's numbers).
DEFAULT_TARGET_ANNUAL = 120_000.0
DEFAULT_TARGET_HOURLY = 75.0

_MONEY_RE = re.compile(
    r"\$\s*([\d]{1,3}(?:,\d{3})*(?:\.\d+)?)\s*([kK])?"
    r"(?:\s*(?:-|to|–|—)\s*\$?\s*([\d]{1,3}(?:,\d{3})*(?:\.\d+)?)\s*([kK])?)?"
    r"\s*(?:/\s*(hour|hr|yr|year|annum|annually))?"
)
#: Placeholder/non-numeric "salary" text -- treat exactly like an absent field.
_NO_SALARY_INFO_RE = re.compile(
    r"^\s*(competitive|doe|depends?\s+on\s+experience|negotiable|n/?a|tbd|-)?\s*$",
    re.IGNORECASE,
)


def _parse_first_amount(text: str) -> tuple[float, float, str | None] | None:
    """First ``$`` amount/range found in ``text`` -> ``(lo, hi, unit)`` where
    ``unit`` is ``"hour"``/``"year"``/``None`` (unit not stated -- inferred
    by the caller from magnitude). ``None`` if no parseable amount."""
    match = _MONEY_RE.search(text)
    if not match:
        return None
    lo_raw, lo_k, hi_raw, hi_k, unit_raw = match.groups()
    lo = float(lo_raw.replace(",", "")) * (1000.0 if lo_k else 1.0)
    if hi_raw:
        hi = float(hi_raw.replace(",", "")) * (1000.0 if hi_k else 1.0)
    else:
        hi = lo
    unit: str | None = None
    if unit_raw:
        unit = "hour" if unit_raw.lower() in ("hour", "hr") else "year"
    return lo, hi, unit


_PAY_CLEARLY_LOW_MULTIPLIER = 0.75  # < 80% of target
_PAY_SOMEWHAT_LOW_MULTIPLIER = 0.9  # 80-100% of target


def pay_multiplier(
    salary: str | None,
    description: str = "",
    *,
    target_annual: float = DEFAULT_TARGET_ANNUAL,
    target_hourly: float = DEFAULT_TARGET_HOURLY,
) -> RankingFactor:
    """Penalize pay clearly below Kevin's target; UNKNOWN pay is neutral
    (most ATS postings omit it -- never over-penalize a missing field).

    Prefers the structured ``salary`` field; falls back to parsing a ``$``
    figure out of ``description`` only when ``salary`` is absent/placeholder
    text ("Competitive", "DOE", ...), per the coordinator's instruction.
    """
    source = (salary or "").strip()
    if not source or _NO_SALARY_INFO_RE.match(source):
        source = description or ""
        if not _MONEY_RE.search(source):
            return RankingFactor(1.0, "no salary information available -- not penalized")

    parsed = _parse_first_amount(source)
    if parsed is None:
        return RankingFactor(1.0, "no parseable salary figure -- not penalized")
    lo, hi, unit = parsed
    mid = (lo + hi) / 2.0
    if unit is None:
        # Infer: a figure under ~1,000 is virtually always hourly ("$75"),
        # anything higher is annual ("$120,000" or "$120k" already expanded).
        unit = "hour" if mid < 1000 else "year"

    target = target_hourly if unit == "hour" else target_annual
    if target <= 0:
        return RankingFactor(1.0, "no target pay configured -- not penalized")
    ratio = mid / target

    if ratio < 0.8:
        return RankingFactor(
            _PAY_CLEARLY_LOW_MULTIPLIER,
            f"parsed pay (~{mid:,.0f}/{unit}) is clearly below target (~{target:,.0f}/{unit})",
        )
    if ratio < 1.0:
        return RankingFactor(
            _PAY_SOMEWHAT_LOW_MULTIPLIER,
            f"parsed pay (~{mid:,.0f}/{unit}) is somewhat below target (~{target:,.0f}/{unit})",
        )
    return RankingFactor(1.0, f"parsed pay (~{mid:,.0f}/{unit}) meets or exceeds target")


# === seniority / impact ======================================================
_SENIORITY_TOP_RE = re.compile(r"\b(principal|staff|director|head)\b", re.IGNORECASE)
_SENIORITY_MID_RE = re.compile(r"\b(lead|senior|sr\.?)\b", re.IGNORECASE)
_SENIORITY_JUNIOR_RE = re.compile(
    r"\b(associate|junior|jr\.?|entry[- ]level|intern(?:ship)?)\b", re.IGNORECASE
)
_SENIORITY_TOP_MULTIPLIER = 1.12
_SENIORITY_MID_MULTIPLIER = 1.06
_SENIORITY_JUNIOR_MULTIPLIER = 0.85


def seniority_multiplier(title: str) -> RankingFactor:
    """Small title-based boost for a higher-impact seniority band; a small
    penalty for an explicitly junior/associate one. Neutral (1.0) for a
    plain mid-level title with no seniority word either way."""
    title = title or ""
    if _SENIORITY_TOP_RE.search(title):
        return RankingFactor(_SENIORITY_TOP_MULTIPLIER, "Principal/Staff/Director/Head-level title")
    if _SENIORITY_MID_RE.search(title):
        return RankingFactor(_SENIORITY_MID_MULTIPLIER, "Lead/Senior-level title")
    if _SENIORITY_JUNIOR_RE.search(title):
        return RankingFactor(_SENIORITY_JUNIOR_MULTIPLIER, "Associate/Junior-level title")
    return RankingFactor(1.0, "no seniority signal in the title")


# === fit-to-profile (round 4) ================================================
#: STRONG fit — Kevin's EXACT title/cert history: Lead Scrum Master @ Wells
#: Fargo, Scrum Master @ Slalom/Ally, Principal Service Delivery Scrum
#: Master @ Dell EMC/Boeing; CSP-SM/A-CSM/CSM/SAFe SSM/KMP certs. Checked
#: FIRST so a title naming both a strong- and moderate-fit family (e.g. a
#: TPM title that also says "Agile Delivery") resolves STRONG.
_STRONG_FIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bscrum\s*master\b", re.IGNORECASE),
    re.compile(r"\brelease\s+train\s+engineer\b|\brte\b", re.IGNORECASE),
    # "Agile/Agility/Scrum/Kanban Coach", "Agile TEAM Coach", "Enterprise
    # Agile Coach" -- Kevin's coaching background, not just a literal
    # "Agile Coach" substring match.
    re.compile(r"\b(agile|agility|scrum|kanban)\b[\s\w]{0,20}\bcoach(es)?\b", re.IGNORECASE),
    re.compile(r"\bteam\s+coach\b", re.IGNORECASE),
    re.compile(r"\bagile\s+delivery\b", re.IGNORECASE),
    re.compile(r"\bdelivery\s+(manager|lead)\b", re.IGNORECASE),
    re.compile(r"\biteration\s+manager\b", re.IGNORECASE),
    re.compile(r"\bagile\s+transformation\b", re.IGNORECASE),
    re.compile(r"\bways\s+of\s+working\b", re.IGNORECASE),
)
#: MODERATE/STRETCH fit — round-3-widened families Kevin is open to and has
#: an adjacent hook for (his AI-dev-tooling delivery work), but no TITLE
#: history in: TPM/PM/PMO/Operations/Chief of Staff. Kept fully VIABLE, just
#: ranked below the strong-fit set for an equivalent-freshness pair.
_MODERATE_FIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\btechnical\s+program\s+manager\b|\btpm\b", re.IGNORECASE),
    re.compile(r"\bagile\s+program\s+manager\b", re.IGNORECASE),
    re.compile(r"\bprogram\s+managers?\b", re.IGNORECASE),
    re.compile(r"\bproject\s+managers?\b", re.IGNORECASE),
    re.compile(r"\bpmo\b", re.IGNORECASE),
    re.compile(r"\b(delivery|product|program)\s+operations\b", re.IGNORECASE),
    re.compile(r"\bchief\s+of\s+staff\b", re.IGNORECASE),
    re.compile(r"\boperations\s+(manager|lead)s?\b", re.IGNORECASE),
)
_STRONG_FIT_MULTIPLIER = 1.10
_MODERATE_FIT_MULTIPLIER = 0.85
#: REACH -- a title Kevin has NEVER held, at a LEVEL beyond his realistic reach:
#: a LEVELED **Technical Program Manager** (Senior / Sr / Lead / Staff / Principal
#: / Distinguished). Kevin has no TPM title history and no degree, and these are
#: overwhelmingly big-tech reqs (waymo/lyft/roblox/instacart) with a hard degree
#: bar, so a leveled TPM is a REACH, not a stretch -- demoted well BELOW his real
#: Scrum Master / Coach / Delivery lane so it stops cluttering the top. Still
#: VIABLE (the allowlist admitted it). A PLAIN "Technical Program Manager" (no
#: level word) stays in the moderate stretch tier.
_REACH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(staff|principal|distinguished|senior|sr\.?|lead)\b[\s\w,./-]{0,30}"
        r"\btechnical\s+program\s+manager\b",
        re.IGNORECASE,
    ),
)
_REACH_MULTIPLIER = 0.65


def fit_to_profile_multiplier(title: str) -> RankingFactor:
    """Rank Kevin's EXACT-match role families above the round-3-widened
    stretch families — both stay viable (the allowlist already decided
    that), this only decides who ranks higher for an equivalent-freshness
    pair. Neutral (1.0) for a title matching neither tier (shouldn't
    normally happen for an allowlisted posting, but never penalize an
    unrecognized shape)."""
    title = title or ""
    for pattern in _REACH_PATTERNS:
        if pattern.search(title):
            return RankingFactor(
                _REACH_MULTIPLIER,
                "reach: Staff/Principal-level Technical Program Manager -- a title/level Kevin "
                "has no history for; ranked well below his Scrum Master/Coach/delivery lane",
            )
    for pattern in _STRONG_FIT_PATTERNS:
        if pattern.search(title):
            return RankingFactor(
                _STRONG_FIT_MULTIPLIER,
                "matches Kevin's exact title/cert history (Scrum Master/Agile Coach/delivery-flavored)",
            )
    for pattern in _MODERATE_FIT_PATTERNS:
        if pattern.search(title):
            return RankingFactor(
                _MODERATE_FIT_MULTIPLIER,
                "adjacent/stretch fit (program/project management) -- viable but ranked below his exact-match roles",
            )
    return RankingFactor(1.0, "no specific fit-tier signal in the title")


# === degree-requirement penalty (round 4) ====================================
#: Kevin has no bachelor's degree (homeschool HS + certs). A HARD
#: requirement ("required", "must have", "minimum") is a real screening
#: risk; "preferred"/"or equivalent experience" is not -- he has 10+ years
#: of directly relevant experience.
_DEGREE_ESCAPE_RE = re.compile(
    r"(bachelor'?s?|master'?s?|b\.?s\.?|m\.?s\.?|mba)[^.]{0,100}"
    r"(or\s+equivalent|preferred|nice\s+to\s+have|a\s+plus|not\s+required)",
    re.IGNORECASE,
)
_DEGREE_HARD_REQUIRED_RE = re.compile(
    r"(bachelor'?s?|master'?s?|b\.?s\.?|m\.?s\.?|mba)[^.]{0,60}\brequired\b|"
    r"\brequires?\b[^.]{0,40}(bachelor'?s?|master'?s?)\s+degree|"
    r"\bmust\s+have\b[^.]{0,40}(bachelor'?s?|master'?s?)\s+degree|"
    r"\bminimum\b[^.]{0,40}(bachelor'?s?|master'?s?)\s+degree",
    re.IGNORECASE,
)
_DEGREE_HARD_REQUIRED_MULTIPLIER = 0.85


def degree_requirement_multiplier(description: str) -> RankingFactor:
    """Penalize a posting that HARD-requires a degree; neutral for
    "preferred"/"or equivalent experience"/no mention at all -- never
    over-penalize, most postings don't screen this hard in practice."""
    description = description or ""
    if not description:
        return RankingFactor(1.0, "no description to check for a degree requirement")
    if _DEGREE_ESCAPE_RE.search(description):
        return RankingFactor(
            1.0, "degree mentioned but not a hard requirement (preferred/equivalent-experience escape)"
        )
    if _DEGREE_HARD_REQUIRED_RE.search(description):
        return RankingFactor(
            _DEGREE_HARD_REQUIRED_MULTIPLIER, "posting hard-requires a degree Kevin does not have"
        )
    return RankingFactor(1.0, "no hard degree requirement detected")


# === US-remote HARD gate =====================================================
#: Explicit remote language (structural ``work_mode`` values are also
#: checked directly by the caller-facing helper below).
_REMOTE_LANGUAGE_RE = re.compile(
    r"\bremote\b|\bwork\s+from\s+home\b|\bwork\s+from\s+anywhere\b|"
    r"\bfully\s+remote\b|\bremote[- ]first\b|#li-remote",
    re.IGNORECASE,
)
#: Explicit onsite/hybrid language, or a clearance requirement (inherently
#: onsite -- mirrors the LLM rubric's existing GATE 3 treatment of TS/SCI).
_ONSITE_HYBRID_RE = re.compile(
    r"\bon[- ]site\b|\bin[- ]office\b|\bhybrid\b|\bTS/SCI\b|\bsecurity\s+clearance\b",
    re.IGNORECASE,
)
#: Curated NON-US country/city terms commonly seen in a scraped ``location``
#: field or description. Deliberately excludes ambiguous US/non-US homonyms
#: (e.g. the US state "Georgia" vs the country) to avoid false positives.
_NON_US_TERMS: frozenset[str] = frozenset(
    {
        "india", "bangalore", "bengaluru", "mumbai", "delhi", "new delhi", "hyderabad",
        "pune", "chennai", "gurgaon", "gurugram", "noida", "kolkata",
        "united kingdom", "uk", "london", "manchester", "dublin", "ireland",
        "canada", "toronto", "vancouver", "montreal", "ontario", "ottawa",
        "germany", "berlin", "munich", "frankfurt", "france", "paris",
        "spain", "madrid", "barcelona", "italy", "milan", "rome",
        "netherlands", "amsterdam", "poland", "warsaw", "portugal", "lisbon",
        "romania", "ukraine", "sweden", "stockholm", "switzerland", "zurich",
        "mexico", "mexico city", "brazil", "sao paulo", "são paulo",
        "argentina", "buenos aires", "colombia", "bogota", "bogotá", "chile", "santiago",
        "philippines", "manila", "singapore", "australia", "sydney", "melbourne",
        "new zealand", "auckland", "china", "beijing", "shanghai", "japan", "tokyo",
        "south korea", "seoul", "uae", "dubai", "abu dhabi", "south africa",
        "nigeria", "egypt", "israel", "tel aviv", "european union", "emea", "apac", "latam",
    }
)
_NON_US_TERMS_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in sorted(_NON_US_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
#: A non-US term in a clearly LOCATIVE position -- directly after "in", a comma,
#: a dash/pipe/@, "based in", "remote from", or "location:" -- so a title like
#: "... in Pune, India" or "Agile Coach - Toronto, Canada" gates, but a company
#: NAME that merely contains a city ("London Stock Exchange", "Berlin Packaging")
#: does NOT (the term is not in a locative position). Catches searxng postings
#: that carry the location in the TITLE while the location column is NULL.
_LOCATIVE_NON_US_RE = re.compile(
    r"(?:\bin\s+|,\s*|[-–—|@]\s*|\bbased\s+in\s+|\bremote\s+from\s+|\blocation:?\s*)"
    r"(?:the\s+)?(" + "|".join(re.escape(t) for t in sorted(_NON_US_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
#: A US signal: "United States"/"USA"/"U.S." spelled out, or "remote"
#: immediately paired with "US"/"United States" -- deliberately NOT a bare
#: "\bus\b" on its own (the common English pronoun "us" would false-positive
#: constantly in ordinary description prose, e.g. "join us", "about us").
_US_SIGNAL_RE = re.compile(
    r"\bunited states\b|\bu\.s\.a?\.?\b|\busa\b|"
    r"\bremote\s*[-,]?\s*(?:in\s+the\s+)?u\.?s\.?a?\.?\b|"
    r"\bu\.?s\.?a?\.?\s*[-,]?\s*remote\b|"
    r"\bremote\s*[-,]?\s*united\s+states\b|"
    r"\banywhere\s+in\s+the\s+u\.?s\.?a?\.?\b",
    re.IGNORECASE,
)
_REMOTE_WORK_MODES = {"remote", "fully remote", "remote-first", "remote first"}
_ONSITE_WORK_MODES = {"onsite", "on-site", "in-office", "hybrid"}


def classify_remote(
    work_mode: str | None, location: str | None = None, description: str = "", title: str = ""
) -> RemoteVerdict:
    """Kevin's HARD requirement: FULL US-REMOTE, no exceptions for an
    otherwise-appealing role. Two-stage: first confirm remote AT ALL
    (structural ``work_mode``, then remote/onsite language, then a named
    location with no remote qualifier = confirmed onsite); only THEN check
    US-ness for a remote-confirmed posting. Genuinely ambiguous cases (no
    signal either way) are left ``None`` -- not gated, only noted -- so a
    scraper gap never silently buries a genuinely good, genuinely US-remote
    role (``work_mode``/``location`` are frequently NULL even on real
    postings -- see this module's and its siblings' eval fixtures).

    ``title`` is scanned too: many searxng postings carry the location in the
    TITLE ("Senior TPM in Pune, India") while the location column is NULL, so a
    non-US location named in a LOCATIVE position in the title gates the posting
    even without any other signal (:data:`_LOCATIVE_NON_US_RE` -- conservative
    so a company name that merely contains a city does not false-gate).
    """
    wm = (work_mode or "").strip().lower()
    loc = (location or "").strip().lower()
    desc = (description or "").strip().lower()
    ttl = (title or "").strip().lower()
    haystack = " ".join(x for x in (wm, loc, desc, ttl) if x)

    # --- structural non-US gate (location column OR a locative mention in the
    # title), independent of remote-signal: a role explicitly located outside
    # the US with no US qualifier anywhere is not US-remote, full stop. Scoped
    # to structural fields (not the free-text description) so an incidental
    # "collaborate with our London office" in a US-remote JD never false-gates.
    struct_non_us = _NON_US_TERMS_RE.search(loc) or _LOCATIVE_NON_US_RE.search(ttl)
    if struct_non_us and not _US_SIGNAL_RE.search(haystack):
        return RemoteVerdict(
            False,
            f"non-US location ({struct_non_us.group(1) if struct_non_us.lastindex else struct_non_us.group(0)!r}) "
            "named in the title/location with no US qualifier",
        )

    # --- stage 1: remote AT ALL? ---
    if wm in _ONSITE_WORK_MODES:
        return RemoteVerdict(False, f"work_mode is {work_mode!r} (onsite/hybrid)")
    remote_signal = wm in _REMOTE_WORK_MODES or bool(_REMOTE_LANGUAGE_RE.search(haystack))
    onsite_signal = bool(_ONSITE_HYBRID_RE.search(haystack))
    if onsite_signal and not remote_signal:
        return RemoteVerdict(False, "explicit onsite/hybrid/clearance language, no remote qualifier")
    if not remote_signal and loc:
        # A specific location IS stated but nothing marks it remote anywhere
        # -- mirrors the LLM rubric's existing GATE-3 treatment of a named
        # city with no remote qualifier as confirmed non-remote.
        return RemoteVerdict(False, f"a specific location ({location!r}) is named with no remote qualifier")
    if not remote_signal:
        return RemoteVerdict(None, "no remote/onsite/location signal found")

    # --- stage 2: remote confirmed -- now US-specific ---
    non_us_match = _NON_US_TERMS_RE.search(haystack)
    us_signal = bool(_US_SIGNAL_RE.search(haystack))
    if non_us_match and not us_signal:
        return RemoteVerdict(
            False, f"remote confirmed but a non-US location signal ({non_us_match.group(0)!r}) with no US qualifier"
        )
    if us_signal:
        return RemoteVerdict(True, "explicit remote + US signal")
    # Remote confirmed, but no country stated either way -- ambiguous,
    # per the coordinator's explicit instruction do NOT hard-gate this case.
    return RemoteVerdict(None, "remote confirmed but no US/non-US signal found -- ambiguous")


#: Only the LOW tier (raw searxng metasearch) is demoted. High (direct ATS),
#: medium (jobspy/rss -- real scraped postings), and unknown all stay NEUTRAL
#: (1.0): the point is strictly to sink raw web-search hits below real postings,
#: not to penalize any genuine job source. Unknown -> neutral (never penalize a
#: source we cannot classify), mirroring the ambiguous-remote "don't gate" rule.
_SOURCE_TIER_MULTIPLIER: dict[str, float] = {"high": 1.0, "medium": 1.0, "low": 0.72}


def source_reliability_multiplier(source_key: str | None) -> RankingFactor:
    """Rank real postings above raw-metasearch hits.

    Kevin's requirement: "only verified sources ... the only entity is a job
    posting." A direct ATS API (greenhouse / lever / ashby / smartrecruiters /
    workday) is a ``high``-tier VERIFIED source; jobspy/rss are ``medium`` (real
    postings, scraped/feed); raw searxng metasearch is ``low`` -- the ONLY tier
    demoted (x0.72), so a real posting outranks a searxng web-hit of similar
    fit, WITHOUT excluding searxng (breadth still matters). Tier comes from
    :func:`source_reliability.reliability_tier`; unknown -> neutral.
    """
    from applicant.core.rules.source_reliability import reliability_tier

    tier = reliability_tier(source_key or "")
    mult = _SOURCE_TIER_MULTIPLIER.get(tier, 1.0)
    return RankingFactor(mult, f"source {source_key or '?'!r} tier={tier} (x{mult:.2f})")
