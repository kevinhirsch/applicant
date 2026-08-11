"""Deterministic derivation of a :class:`CandidateProfile` from the attribute
cloud (ADR-0011, FIT-MODEL FM-2). Pure + no IO so it is fully testable against a
real candidate's attributes; the service layer reads the cloud + persists.

This is deterministic-first (ADR-0011): the structural signals — which role
FAMILIES the candidate has actually HELD (``roles``), whether they hold a real
DEGREE (``education:*``), their certifications + skills — come straight from the
parsed profile. An LLM assist (title normalization / rationale prose) is a later
refinement; the deterministic pass already produces the strong/stretch/reach fit
bands that FS-2 (ADR-0012) will consume to retire the hardcoded ``role_domain_fit``
allowlist + ``fit_to_profile`` tiers. The point is GENERALITY: the bands are
computed from THIS candidate's history, so a different résumé yields different
bands — not a Kevin-hardcoded list.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from applicant.core.entities.candidate_profile import (
    CandidateProfile,
    Credential,
    FitBand,
    TitleHistory,
)
from applicant.core.ids import CampaignId

#: Canonical role-family map: a matched phrase -> (family key, display, level hint).
#: Ordered longest/most-specific first so "release train engineer" wins over a bare
#: "engineer" and "technical program manager" is classified before "program manager".
_ROLE_FAMILY_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\btechnical\s+program\s+manager\b|\btpm\b", re.I), "technical_program_manager", "Technical Program Manager"),
    (re.compile(r"\brelease\s+train\s+engineer\b|\brte\b", re.I), "release_train_engineer", "Release Train Engineer"),
    (re.compile(r"\bscrum\s*master\b", re.I), "scrum_master", "Scrum Master"),
    (re.compile(r"\b(agile|agility|scrum|kanban)\s+coach\b", re.I), "agile_coach", "Agile Coach"),
    (re.compile(r"\bteam\s+coach\b", re.I), "team_coach", "Team Coach"),
    (re.compile(r"\bagile\s+delivery\b", re.I), "agile_delivery", "Agile Delivery"),
    (re.compile(r"\bagile\s+practi(?:ce|ces|tioner|tioners)\b", re.I), "agile_practice", "Agile Practice"),
    (re.compile(r"\bagile\s+leader\b", re.I), "agile_leader", "Agile Leader"),
    (re.compile(r"\biteration\s+manager\b", re.I), "iteration_manager", "Iteration Manager"),
    (re.compile(r"\bagile\s+transformation\b", re.I), "agile_transformation", "Agile Transformation"),
    (re.compile(r"\bagile\s+program\s+manager\b", re.I), "agile_program_manager", "Agile Program Manager"),
    (re.compile(r"\bdelivery\s+(manager|lead)\b", re.I), "delivery_manager", "Delivery Manager"),
    (re.compile(r"\bprogram\s+managers?\b", re.I), "program_manager", "Program Manager"),
    (re.compile(r"\bproject\s+managers?\b", re.I), "project_manager", "Project Manager"),
    (re.compile(r"\bpmo\b", re.I), "pmo", "PMO"),
    (re.compile(r"\bchief\s+of\s+staff\b", re.I), "chief_of_staff", "Chief of Staff"),
)

#: Adjacent role families a delivery/agile candidate is a credible STRETCH for even
#: without title history (program/project management is squarely reachable). Held
#: families are removed from this set (they're strong, not stretch).
_ADJACENT_STRETCH_FAMILIES: frozenset[str] = frozenset(
    {"program_manager", "project_manager", "pmo", "chief_of_staff", "agile_program_manager"}
)

#: A real academic DEGREE (bachelor's+). Deliberately does NOT match a certification
#: that merely contains "Master" (e.g. "Microsoft Office Master Specialist") — the
#: degree word must be in a degree CONTEXT ("Bachelor of ...", "Master's degree in
#: ...") or a standalone abbreviation (B.S./M.S./MBA/PhD).
_DEGREE_RE = re.compile(
    r"\b(bachelor|master|associate|baccalaureate)(?:'?s)?\s+(?:of\b|degree\b|in\b)"
    r"|\bdegree\s+in\b"
    r"|\b(b\.?s\.?|b\.?a\.?|m\.?s\.?|m\.?a\.?|m\.?b\.?a\.?|ph\.?\s*d\.?|doctorate)\b",
    re.IGNORECASE,
)


def _families_from_text(text: str) -> list[tuple[str, str]]:
    """Return [(family_key, display)] for every role family named in ``text``."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern, family, display in _ROLE_FAMILY_PATTERNS:
        if family not in seen and pattern.search(text or ""):
            seen.add(family)
            out.append((family, display))
    # Subsumption: a compound title ("Technical/Agile Program Manager") also matches
    # the generic "Program Manager" substring -- but it IS the specific role, not both,
    # so drop the parent (else a TPM's reach band gets upgraded to PM's stretch).
    if seen & {"technical_program_manager", "agile_program_manager"}:
        out = [(f, d) for f, d in out if f != "program_manager"]
    return out


def _has_real_degree(education_values: list[str]) -> bool:
    """True iff any education entry is a real academic degree (bachelor's+)."""
    return any(_DEGREE_RE.search(v or "") for v in education_values)


def derive_candidate_profile(
    campaign_id: CampaignId, attributes: Mapping[str, str]
) -> CandidateProfile:
    """Derive a :class:`CandidateProfile` from a name->value attribute cloud.

    Reads ``roles`` (held families), ``education:*`` (degree gate + credentials),
    ``certifications``, and ``skill:*``. Degrades to an un-derived profile
    (``derived=False``) when there is no ``roles`` signal, so scoring falls back to
    the legacy allowlist rather than trusting an empty model.
    """
    attrs = {str(k): str(v) for k, v in attributes.items()}

    roles_text = attrs.get("roles", "") or attrs.get("roles:0", "")
    held = _families_from_text(roles_text)
    if not held:
        # No held-role signal -> don't fabricate a model; caller falls back.
        return CandidateProfile(campaign_id=campaign_id, derived=False)
    held_keys = {f for f, _ in held}

    education_values = [v for k, v in attrs.items() if k == "education" or k.startswith("education:")]
    has_degree = _has_real_degree(education_values)
    degree_detail = (
        "holds an academic degree" if has_degree
        else "no academic degree detected (certifications + secondary education only) "
             "— a hard ATS auto-filter risk on degree-required reqs"
    )

    # Credentials: the certifications attribute + any cert-shaped education entry.
    cred_values: list[str] = []
    if attrs.get("certifications"):
        cred_values.extend(p.strip() for p in re.split(r"[;,]", attrs["certifications"]) if p.strip())
    credentials = tuple(Credential(name=c) for c in dict.fromkeys(cred_values))  # de-dup, keep order

    skills = {v: 1.0 for k, v in attrs.items() if k.startswith("skill:") and v}

    title_history = tuple(
        TitleHistory(title=display, family=family, level="lead", primary=True)
        for family, display in held
    )

    # --- DERIVED fit bands -------------------------------------------------
    # STRONG: families the candidate has actually HELD.
    strong = tuple(FitBand(family=f, rationale=f"held role ({d})") for f, d in held)
    # STRETCH: credible adjacents (program/project mgmt) the candidate has NOT held.
    stretch = tuple(
        FitBand(family=f, rationale="adjacent to held delivery/agile roles; no title history")
        for f in sorted(_ADJACENT_STRETCH_FAMILIES - held_keys)
    )
    # REACH: a Technical Program Manager the candidate never held AND lacks the degree
    # these reqs commonly hard-gate on -> a reach, not a stretch (big-tech leveling).
    reach: tuple[FitBand, ...] = ()
    if "technical_program_manager" not in held_keys and not has_degree:
        reach = (
            FitBand(
                family="technical_program_manager",
                rationale="no TPM title history + no degree (common hard ATS gate) — a reach",
            ),
        )

    signature = f"roles={sorted(held_keys)};degree={has_degree};certs={len(credentials)};skills={len(skills)}"
    return CandidateProfile(
        campaign_id=campaign_id,
        title_history=title_history,
        current_level="lead",
        target_level="lead",
        credentials=credentials,
        has_degree=has_degree,
        degree_detail=degree_detail,
        skills=skills,
        strong_fit_families=strong,
        viable_stretch_families=stretch,
        reach_families=reach,
        derived=True,
        source_signature=signature,
    )


#: Band -> ranking multiplier, matching ranking_factors' strong / moderate / reach
#: fit tiers (1.10 / 0.85 / 0.65) so a DERIVED band scores IDENTICALLY to the legacy
#: fit_to_profile tier where both agree -- the FS-2 wiring is behavior-preserving.
_BAND_MULTIPLIER: dict[str, float] = {"strong": 1.10, "stretch": 0.85, "reach": 0.65}
_BAND_RANK: dict[str, int] = {"strong": 3, "stretch": 2, "reach": 1}


def families_from_title(title: str) -> list[str]:
    """Role family keys named in a posting ``title`` (same map as the derivation)."""
    return [f for f, _ in _families_from_text(title)]


def profile_fit(profile: CandidateProfile, title: str) -> tuple[str, float] | None:
    """Assess a posting ``title`` against the DERIVED profile (FS-2, ADR-0012).

    Returns ``(band, multiplier)`` from the best-matched family's band (strong >
    stretch > reach when a title names several), or ``None`` to signal the caller
    to FALL BACK to the legacy allowlist / fit tiers -- when the profile is
    un-derived, or no family the title names is banded (a derivation gap). This is
    what lets the derived model replace the hardcoded allowlist with zero
    regression: where the derivation is silent, legacy behavior is preserved.
    """
    if not getattr(profile, "derived", False):
        return None
    best: str | None = None
    for fam in families_from_title(title):
        band = profile.band_for(fam)
        if band and (best is None or _BAND_RANK[band] > _BAND_RANK[best]):
            best = band
    if best is None:
        return None
    return best, _BAND_MULTIPLIER[best]
