"""CandidateProfile — the derived competitiveness model (ADR-0011, FIT-MODEL).

This is the substrate that lets scoring make the *reach-vs-strong-fit* call the
way a human (or Claude) does when re-reading the résumé — "would this candidate
get a CALL for this role?" — rather than the keyword/allowlist membership test in
``core.rules.role_domain_fit`` (which is Kevin-hardcoded and needs manual patches
every time a real title slips through: Agile Practitioner, leveled TPM, ...).

It is DERIVED (see ``application.services.candidate_profile_service``), not
hand-authored: structural fields come from the parsed résumé + attribute cloud;
an LLM assist normalizes titles / infers level / articulates the fit rationale.
The model is stored + inspectable + re-derivable per campaign, so it is auditable
and revertible. It degrades gracefully to an empty profile when the résumé is
sparse (callers fall back to today's allowlist behavior — ADR-0012 migration).

FS-* (ADR-0012) scoring consumes ``strong_fit_families`` / ``reach_families`` +
the competitiveness signals (degree gate, title-history, level, industry) here,
replacing the hardcoded ``role_domain_fit`` allowlist + ``fit_to_profile`` tiers.
OUTCOME-LEARN (ADR-0013) sharpens the derived bands from real application outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.core.ids import CampaignId

#: Coarse seniority level, associate -> executive. Used for level-match scoring
#: (a role two bands above the candidate's realistic target is a reach).
Level = str  # one of _LEVELS, kept as str for storage simplicity
_LEVELS: tuple[str, ...] = (
    "associate",
    "mid",
    "senior",
    "lead",
    "principal",
    "director",
    "executive",
)


@dataclass(frozen=True)
class TitleHistory:
    """A role/title the candidate has ACTUALLY held (vs. is adjacent to)."""

    title: str  #: normalized title, e.g. "Scrum Master", "Release Train Engineer"
    family: str  #: role family key, e.g. "scrum_master", "agile_coach", "rte"
    level: Level  #: seniority level while held
    years: float = 0.0  #: total tenure in this title/family
    primary: bool = True  #: primary role vs. a stretch/coverage stint
    recent: bool = True  #: held within the recent window (recency of the skill)


@dataclass(frozen=True)
class Credential:
    """A typed certification/credential (CSP-SM, A-CSM, SAFe SSM, KMP, ...)."""

    name: str
    kind: str = "certification"  #: certification | license | clearance


@dataclass(frozen=True)
class IndustryExposure:
    """An industry the candidate has worked in, with depth + recency."""

    name: str  #: e.g. "finance", "insurance", "healthcare", "aerospace"
    regulated: bool = False
    depth_years: float = 0.0
    recent: bool = True


@dataclass(frozen=True)
class FitBand:
    """A derived role family the candidate is a strong fit / viable stretch /
    reach for, with a human-readable rationale (feeds the EXPLAIN breakdown)."""

    family: str  #: role family key, e.g. "scrum_master", "technical_program_manager"
    rationale: str = ""  #: why this band ("title + certs + regulated-industry match")


@dataclass(frozen=True)
class CandidateProfile:
    """A structured model of the candidate's real competitiveness (ADR-0011).

    All fields default empty so an un-derived / sparse profile is valid and callers
    can degrade to the legacy allowlist. ``derived`` is False until a real
    derivation has run (so scoring knows whether to trust the bands or fall back).
    """

    campaign_id: CampaignId

    #: 1. Role/title history — what the candidate has actually HELD.
    title_history: tuple[TitleHistory, ...] = ()
    #: 2. Seniority — current level + realistic target band.
    current_level: Level = ""
    target_level: Level = ""
    #: 3. Credentials + the degree gate. ``has_degree`` is an explicit, first-class
    #: field because "no bachelor's" is a hard, common ATS auto-filter (ADR-0012).
    credentials: tuple[Credential, ...] = ()
    has_degree: bool = False
    degree_detail: str = ""  #: e.g. "homeschool HS + certs; no bachelor's"
    #: 4. Industries with depth + recency.
    industries: tuple[IndustryExposure, ...] = ()
    #: 5. Functional domains / skills, name -> evidence strength in [0,1]
    #: (demonstrated-and-quantified vs. merely mentioned).
    skills: dict[str, float] = field(default_factory=dict)
    #: 6. Quantified achievements (the wins that make the candidate competitive).
    achievements: tuple[str, ...] = ()
    #: 7. True technical depth families (distinguishes real depth from adjacent,
    #: e.g. DevOps/endpoint automation != software-services engineering).
    technical_depth: tuple[str, ...] = ()
    #: 8. DERIVED fit bands — computed from the above (NOT hand-authored).
    strong_fit_families: tuple[FitBand, ...] = ()
    viable_stretch_families: tuple[FitBand, ...] = ()
    reach_families: tuple[FitBand, ...] = ()

    #: True once a real derivation has populated the model (else callers fall back
    #: to the legacy ``role_domain_fit`` allowlist — graceful degradation).
    derived: bool = False
    #: Provenance/version so a re-derivation on résumé change is auditable.
    source_signature: str = ""

    # --- read helpers scoring will use (FS-*, ADR-0012) ----------------------

    def held_families(self) -> frozenset[str]:
        """Role families the candidate has ACTUALLY held (title-history match)."""
        return frozenset(t.family for t in self.title_history)

    def band_for(self, family: str) -> str | None:
        """Return 'strong' | 'stretch' | 'reach' for ``family``, or None if the
        profile is un-derived or doesn't classify it (caller falls back)."""
        if not self.derived:
            return None
        key = (family or "").strip().lower()
        if any(b.family == key for b in self.strong_fit_families):
            return "strong"
        if any(b.family == key for b in self.viable_stretch_families):
            return "stretch"
        if any(b.family == key for b in self.reach_families):
            return "reach"
        return None
