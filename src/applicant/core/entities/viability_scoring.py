"""ViabilityScoring entity — can the user reasonably get this role? (FR-AGENT-3)."""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.ids import JobPostingId


@dataclass(frozen=True)
class ViabilityScoring:
    """Scores whether the user could reasonably get the role, from the JD.

    Distinct from ``ResumeFitScoring`` (coverage of a variant vs a JD).
    """

    posting_id: JobPostingId
    score: float  # 0.0..1.0
    rationale: str = ""
    #: True when ``score`` came from the local-embedding FALLBACK because a
    #: configured LLM tier call failed (timeout/transport/parse) — NOT because no
    #: LLM is configured at all (P0 durability fix, scoring_service.py). Callers
    #: (``ScoringService._persist_or_defer``) use this to avoid persisting a
    #: transient failure as an authoritative sub-threshold score, which used to
    #: permanently bury an otherwise-good posting with no retry. Defaults False so
    #: every existing construction site (LLM success, no-LLM-configured, the
    #: no-criteria neutral score) is byte-identical to before.
    degraded: bool = False
