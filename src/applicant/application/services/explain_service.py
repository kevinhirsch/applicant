"""ExplainService — the EXPLAIN backend: WHY a posting scored what it scored.

Builds a per-posting, weighted greens/reds :class:`ScoreBreakdown`
(``core/entities/score_breakdown.py``) that reconciles with the posting's
persisted ``ViabilityScoring.score``, and durably caches it on the existing
``JobPosting.rationale`` JSON column under the ``"breakdown"`` key (same
precedent as ``scoring_service.py``'s ``SNAPSHOT_KEY`` /
``transient_llm_failures`` — no schema change).

**Deterministic-FIRST** (NFR-TOKEN-1 parity with ``ScoringService``): every
factor comes from a PURE, no-IO core rule —

* ``core.rules.posting_quality.check_posting_quality`` (owned by a concurrent
  agent; imported READ-ONLY, never edited) gates whether this is even a real,
  specific opening;
* ``core.rules.jd_match.compute_jd_match`` measures keyword overlap between
  the candidate's stated criteria and the posting text;
* ``core.rules.freshness.posting_freshness`` flags a stale listing;
* ``core.rules.eligibility.assess_work_auth_eligibility`` flags a stated
  sponsorship/citizenship conflict;
* ``core.rules.ats_match_rate`` scores a prior live pre-fill walk's field
  match rate, when one has been recorded on the posting.

An OPTIONAL LLM tier only adds a short plain-language NUANCE line — at ZERO
score weight — so ``build_breakdown`` always produces a complete, sensible
breakdown with no LLM configured at all (token/offline parity).

**Trigger**: :meth:`start` subscribes to the ``ViabilityScored`` domain event
(mirrors ``AuditLogService.start`` — an isolated per-event session when
``session_factory`` is configured, so the write survives a scheduler-thread
rollback) and re-runs the breakdown on every (re-)score, self-healing the
cached rationale.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.score_breakdown import BreakdownFactor, ScoreBreakdown
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.entities.viability_scoring import ViabilityScoring
from applicant.core.ids import JobPostingId
from applicant.core.rules import ats_match_rate, jd_match, posting_quality
from applicant.core.rules import eligibility as eligibility_rule
from applicant.core.rules import freshness as freshness_rule
from applicant.core.rules.prompt_injection import neutralize_untrusted_text
from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import ChatMessage

log = get_logger(__name__)

#: Key the breakdown is cached under, within the existing ``rationale`` JSON
#: column (precedent: ``scoring_service.SNAPSHOT_KEY``-style reuse — no schema
#: migration).
BREAKDOWN_KEY = "breakdown"

_GREEN_AT = 0.66
_RED_AT = 0.34


def _polarity_for(raw_value: float) -> str:
    """Green/red/neutral classification for a raw [0,1] factor value."""
    if raw_value >= _GREEN_AT:
        return "green"
    if raw_value <= _RED_AT:
        return "red"
    return "neutral"


@dataclasses.dataclass
class _RawFactor:
    """Intermediate, pre-normalization signal — never leaves this module."""

    label: str
    raw_value: float  # 0..1, 1 = best/green
    base_weight: float
    detail: str
    polarity: str | None = None  # override; else derived from raw_value
    source: str = "deterministic"


class ExplainService:
    """Builds + persists the weighted greens/reds EXPLAIN breakdown for a posting."""

    #: Relative importance of each deterministic factor BEFORE normalization —
    #: only factors that actually produce a signal for a given posting are
    #: normalized in (see :meth:`_deterministic_factors`). Chosen so the
    #: posting-quality gate (a non-posting craters everything, mirroring its
    #: role as GATE 1 in ``ScoringService._llm_base``'s rubric) dominates,
    #: keyword overlap is the next-heaviest signal, and freshness/eligibility/
    #: ats-match are secondary, informational nudges.
    WEIGHT_POSTING_QUALITY = 0.35
    WEIGHT_JD_MATCH = 0.30
    WEIGHT_FRESHNESS = 0.10
    WEIGHT_ELIGIBILITY = 0.15
    WEIGHT_ATS_MATCH = 0.10

    def __init__(
        self,
        storage,
        llm=None,
        embedding=None,
        *,
        session_factory=None,
        bus=None,
    ) -> None:
        self._storage = storage
        self._llm = llm
        self._embedding = embedding
        self._session_factory = session_factory
        from applicant.core.events import event_bus as _default_bus

        self._bus = bus or _default_bus

    # -- trigger (event-bus subscription) ------------------------------------

    def start(self) -> None:
        """Subscribe to ``ViabilityScored`` so the breakdown self-heals on every score.

        Mirrors ``AuditLogService.start``: when ``session_factory`` is
        configured (real DB / scheduler thread) every event opens its own
        session so the explain write is never rolled back with the caller's
        in-flight transaction; otherwise the shared (in-memory) storage is
        used directly.
        """
        from applicant.core.events import ViabilityScored

        self._bus.on(ViabilityScored, self._on_viability_scored)
        log.info("explain_service_subscribed")

    def _on_viability_scored(self, event: Any) -> None:
        if self._session_factory is not None:
            self._handle_isolated(event)
        else:
            self._handle_with(self._storage, event)

    def _handle_isolated(self, event: Any) -> None:
        from applicant.adapters.storage.repositories import SqlAlchemyStorage

        sess = None
        try:
            sess = self._session_factory()
            store = SqlAlchemyStorage(sess)
            self._handle_with(store, event)
        except Exception as exc:  # pragma: no cover - never break scoring
            log.warning("explain_trigger_failed", error=str(exc))
        finally:
            if sess is not None:
                try:
                    sess.close()
                except Exception:  # pragma: no cover - defensive
                    pass

    def _handle_with(self, storage, event: Any) -> None:
        posting = storage.postings.get(event.posting_id)
        if posting is None:
            return
        criteria = self._load_criteria(storage, posting.campaign_id)
        viability = ViabilityScoring(posting_id=posting.id, score=event.score)
        breakdown = self.build_breakdown(posting, criteria, viability)
        self.persist_breakdown(posting, breakdown, storage=storage)

    def _load_criteria(self, storage, campaign_id) -> SearchCriteria | None:
        try:
            from applicant.application.services.criteria_service import CriteriaService

            return CriteriaService(storage, self._llm).get_criteria(campaign_id)
        except Exception:  # pragma: no cover - never break the trigger
            return None

    # -- pure breakdown construction ------------------------------------------

    def build_breakdown(
        self,
        posting: JobPosting,
        criteria: SearchCriteria | None = None,
        viability: ViabilityScoring | None = None,
    ) -> ScoreBreakdown:
        """Compute the weighted greens/reds breakdown for ``posting``.

        ``viability`` is the score this breakdown must reconcile with; when
        omitted, falls back to the posting's own persisted
        ``viability_score`` and, failing that, the deterministic factors' own
        weighted average (e.g. a posting scored for the very first time,
        before any ``ViabilityScoring`` exists at all).
        """
        raw_factors = self._deterministic_factors(posting, criteria)
        total_weight = sum(f.base_weight for f in raw_factors) or 1.0
        raw_score = sum(f.raw_value * f.base_weight for f in raw_factors) / total_weight
        target_score = self._target_score(posting, viability, raw_score)

        factors: list[BreakdownFactor] = []
        for f in raw_factors:
            norm_weight = f.base_weight / total_weight
            contribution = round(norm_weight * f.raw_value * 100.0, 2)
            polarity = f.polarity or _polarity_for(f.raw_value)
            factors.append(
                BreakdownFactor(
                    label=f.label,
                    polarity=polarity,  # type: ignore[arg-type]
                    weight=round(norm_weight, 4),
                    contribution=contribution,
                    source=f.source,  # type: ignore[arg-type]
                    detail=f.detail,
                )
            )

        subtotal = round(sum(fac.contribution for fac in factors), 2)
        residual = round(target_score * 100.0 - subtotal, 2)
        factors.append(self._reconciliation_factor(residual))

        nuance = self._llm_nuance(posting, criteria, target_score)
        if nuance:
            factors.append(
                BreakdownFactor(
                    label="Model's plain-language take",
                    polarity="neutral",
                    weight=0.0,
                    contribution=0.0,
                    source="llm",
                    detail=nuance,
                )
            )

        summary = self._summary(target_score, factors)
        return ScoreBreakdown(
            posting_id=posting.id,
            score=max(0.0, min(1.0, target_score)),
            factors=tuple(factors),
            summary=summary,
        )

    def _deterministic_factors(
        self, posting: JobPosting, criteria: SearchCriteria | None
    ) -> list[_RawFactor]:
        factors: list[_RawFactor] = []

        # --- GATE: real, specific posting? (posting_quality — owned, import-only) --
        verdict = posting_quality.check_posting_quality(
            posting.title or "", posting.source_url or "", posting.description or ""
        )
        factors.append(
            _RawFactor(
                label="Real, specific job posting",
                raw_value=1.0 if verdict.is_posting else 0.0,
                base_weight=self.WEIGHT_POSTING_QUALITY,
                detail=verdict.reason,
            )
        )

        # --- keyword overlap between stated criteria and the posting (jd_match) ---
        effective_criteria = criteria or SearchCriteria(campaign_id=posting.campaign_id)
        criteria_text = " ".join(
            (
                *effective_criteria.titles,
                *effective_criteria.keywords,
                effective_criteria.human_readable,
            )
        ).strip()
        jd_text = f"{posting.title} {posting.description}".strip()
        if criteria_text:
            match = jd_match.compute_jd_match(criteria_text, jd_text)
            matched, missing = match["matched"], match["missing"]
            detail = f"Covers {', '.join(matched[:5])}" if matched else "No shared curated keywords found"
            detail += f"; missing {', '.join(missing[:5])}." if missing else "."
            factors.append(
                _RawFactor(
                    label="Skill & keyword overlap with your stated criteria",
                    raw_value=match["score"] / 100.0,
                    base_weight=self.WEIGHT_JD_MATCH,
                    detail=detail,
                )
            )
        else:
            factors.append(
                _RawFactor(
                    label="Skill & keyword overlap with your stated criteria",
                    raw_value=0.5,
                    base_weight=self.WEIGHT_JD_MATCH,
                    detail="No search criteria set yet — treated as neutral.",
                    polarity="neutral",
                )
            )

        # --- freshness (only when a timestamp is actually known) ------------------
        fresh = freshness_rule.posting_freshness(posting.date_posted, posting.first_seen)
        if fresh is not None:
            stale = fresh["posted_stale"]
            detail = f"{fresh['posted_label']} {fresh['posted_relative']}"
            if stale:
                detail += f" — flagged stale (>{freshness_rule.STALE_AFTER_DAYS} days)."
            else:
                detail += "."
            factors.append(
                _RawFactor(
                    label="Posting freshness",
                    raw_value=0.0 if stale else 1.0,
                    base_weight=self.WEIGHT_FRESHNESS,
                    detail=detail,
                )
            )

        # --- work-authorization eligibility ---------------------------------------
        # ``work_auth`` isn't threaded into this pure signature yet (no owned-file
        # wiring this round); read it from ``criteria.learned_adjustments`` when a
        # future learning pass ever records one there, else default to "no known
        # conflict" — honest, not a fabricated eligibility verdict.
        learned = dict(getattr(effective_criteria, "learned_adjustments", {}) or {})
        work_auth = learned.get("work_auth") or {}
        posting_text = f"{posting.title} {posting.description}"
        elig = eligibility_rule.assess_work_auth_eligibility(posting_text, work_auth)
        factors.append(
            _RawFactor(
                label="Work-authorization eligibility",
                raw_value=1.0 if elig.eligible else 0.0,
                base_weight=self.WEIGHT_ELIGIBILITY,
                detail=elig.reason
                or "No conflicting sponsorship/citizenship requirement detected.",
            )
        )

        # --- ATS pre-fill match rate (only when a live walk recorded one) ---------
        ats_factor = self._ats_match_factor(posting)
        if ats_factor is not None:
            factors.append(ats_factor)

        return factors

    def _ats_match_factor(self, posting: JobPosting) -> _RawFactor | None:
        """Field-match-rate factor (``core.rules.ats_match_rate``) — only when a
        prior live pre-fill walk recorded ``filled``/``detected`` counts on this
        posting's ``rationale["prefill_match"]``. Nothing currently writes that
        key, so this factor is normally OMITTED (not a red — simply not yet
        known) rather than fabricating a fill rate the engine never measured;
        it stays ready for when a pre-fill walk starts recording it there.
        """
        rationale = getattr(posting, "rationale", None)
        if not isinstance(rationale, dict):
            return None
        stats = rationale.get("prefill_match")
        if not isinstance(stats, dict):
            return None
        try:
            filled = int(stats.get("filled", 0))
            detected = int(stats.get("detected", 0))
        except (TypeError, ValueError):
            return None
        rate = ats_match_rate.field_match_rate(filled, detected)
        wrong_ats = ats_match_rate.is_probable_wrong_ats(filled, detected)
        detail = f"{filled}/{detected} detected fields filled on the last pre-fill walk."
        if wrong_ats:
            detail += " Below the acceptable match-rate floor — probable wrong-ATS / near-empty fill."
        return _RawFactor(
            label="Form pre-fill match rate",
            raw_value=rate,
            base_weight=self.WEIGHT_ATS_MATCH,
            detail=detail,
        )

    @staticmethod
    def _target_score(
        posting: JobPosting, viability: ViabilityScoring | None, raw_score: float
    ) -> float:
        if viability is not None and viability.score is not None:
            return max(0.0, min(1.0, viability.score))
        persisted = getattr(posting, "viability_score", None)
        if persisted is not None:
            return max(0.0, min(1.0, persisted))
        return max(0.0, min(1.0, raw_score))

    @staticmethod
    def _reconciliation_factor(residual: float) -> BreakdownFactor:
        if residual > 1.0:
            polarity = "green"
        elif residual < -1.0:
            polarity = "red"
        else:
            polarity = "neutral"
        weight = round(min(1.0, abs(residual) / 100.0), 4)
        detail = (
            "The remaining gap to your persisted score — the model's semantic "
            "judgment, learning bias (taste/converting-role signature), and any "
            "other signal the checks above don't individually cover."
        )
        return BreakdownFactor(
            label="Overall model judgment & learning bias",
            polarity=polarity,  # type: ignore[arg-type]
            weight=weight,
            contribution=residual,
            source="deterministic",
            detail=detail,
        )

    def _llm_nuance(
        self, posting: JobPosting, criteria: SearchCriteria | None, target_score: float
    ) -> str:
        """Optional plain-language nuance line from the injected LLM tier.

        ZERO score weight — never changes what the breakdown adds up to, only
        enriches the human-readable narrative. Guarded: any failure (no LLM
        wired, not configured, a bad reply) degrades to ``""`` so the
        deterministic breakdown above is always complete on its own
        (token/offline parity).
        """
        llm = self._llm
        if llm is None or not getattr(llm, "is_configured", lambda: False)():
            return ""
        try:
            criteria_block = (
                getattr(criteria, "human_readable", "") or "(no stated criteria)"
            )
            system = ChatMessage(
                role="system",
                content=(
                    "In ONE short, plain-language sentence, explain the single "
                    "biggest reason this posting scored the way it did for this "
                    "candidate. No score numbers, no JSON — plain prose only."
                ),
            )
            user = ChatMessage(
                role="user",
                content=(
                    f"Candidate criteria: {neutralize_untrusted_text(criteria_block)}\n"
                    f"Posting title: {neutralize_untrusted_text(posting.title or '')}\n"
                    f"Posting description: {neutralize_untrusted_text(posting.description or '')}\n"
                    f"Score: {round(target_score * 100)}/100"
                ),
            )
            result = llm.complete([system, user], start_tier=1, max_tokens=80)
            text = (getattr(result, "text", "") or "").strip()
            return text[:400]
        except Exception as exc:  # noqa: BLE001 - nuance is advisory-only, never fatal
            log.warning("explain_llm_nuance_failed", error=str(exc))
            return ""

    @staticmethod
    def _summary(target_score: float, factors: list[BreakdownFactor]) -> str:
        greens = [f.label for f in factors if f.polarity == "green"]
        reds = [f.label for f in factors if f.polarity == "red"]
        pct = round(target_score * 100)
        parts = [f"Scored {pct}/100."]
        if greens:
            parts.append("In favor: " + ", ".join(greens[:3]) + ".")
        if reds:
            parts.append("Against: " + ", ".join(reds[:3]) + ".")
        if not greens and not reds:
            parts.append("No strongly positive or negative signal — a middling match.")
        return " ".join(parts)

    # -- serializers -----------------------------------------------------------

    def to_payload(self, breakdown: ScoreBreakdown) -> dict:
        """Full JSON-able payload for ``GET /api/explain/{posting_id}``."""
        return {
            "posting_id": str(breakdown.posting_id),
            "score": breakdown.score,
            "score_pct": round(breakdown.score * 100),
            "summary": breakdown.summary,
            "factors": [self._factor_to_dict(f) for f in breakdown.factors],
        }

    def compact(self, breakdown: ScoreBreakdown, *, top_n: int = 3) -> dict:
        """Top-N highest-magnitude chips for a compact UI surface (a later wave)."""
        candidates = [f for f in breakdown.factors if f.contribution != 0 or f.polarity != "neutral"]
        ranked = sorted(candidates, key=lambda f: abs(f.contribution), reverse=True)
        chips = [
            {"label": f.label, "polarity": f.polarity, "contribution": f.contribution}
            for f in ranked[:top_n]
        ]
        return {
            "score_pct": round(breakdown.score * 100),
            "summary": breakdown.summary,
            "chips": chips,
        }

    @staticmethod
    def _factor_to_dict(f: BreakdownFactor) -> dict:
        return {
            "label": f.label,
            "polarity": f.polarity,
            "weight": f.weight,
            "contribution": f.contribution,
            "source": f.source,
            "detail": f.detail,
        }

    # -- persistence (rationale['breakdown'] MERGE, no schema change) ----------

    def persist_breakdown(
        self, posting: JobPosting, breakdown: ScoreBreakdown, *, storage=None
    ) -> JobPosting:
        """Read-modify-write MERGE ``breakdown`` into ``posting.rationale['breakdown']``.

        Reuses the existing JSON ``rationale`` column (precedent:
        ``scoring_service.py``'s snapshot / ``transient_llm_failures`` keys) —
        no schema change. Merges rather than replaces the dict so any OTHER
        key already on ``rationale`` (the score text, the review snapshot, …)
        survives untouched. Best-effort: a storage hiccup must never break the
        caller (the event trigger / the endpoint's lazy-cache path).
        """
        store = storage if storage is not None else self._storage
        prior = getattr(posting, "rationale", None)
        prior = dict(prior) if isinstance(prior, dict) else {}
        prior[BREAKDOWN_KEY] = self._breakdown_to_dict(breakdown)
        try:
            updated = dataclasses.replace(posting, rationale=prior)
            store.postings.add(updated)
            store.commit()
            return updated
        except Exception as exc:  # pragma: no cover - persistence must never break the caller
            log.warning("explain_persist_failed", error=str(exc))
            return posting

    def explain_posting(
        self, posting_id: JobPostingId, criteria: SearchCriteria | None = None
    ) -> ScoreBreakdown | None:
        """Load ``posting_id``, reusing a cached breakdown when still fresh, else
        build + persist a fresh one (the endpoint's lazy-compute-and-cache path).

        ``criteria`` is self-loaded from the posting's campaign when omitted
        (mirrors ``DigestService``'s front-door self-load — see
        ``test_digest_criteria_wiring.py``). Returns ``None`` only when the
        posting itself does not exist.
        """
        posting = self._storage.postings.get(posting_id)
        if posting is None:
            return None
        if criteria is None:
            criteria = self._load_criteria(self._storage, posting.campaign_id)
        cached = self._cached_breakdown(posting)
        if cached is not None:
            return cached
        breakdown = self.build_breakdown(posting, criteria)
        self.persist_breakdown(posting, breakdown)
        return breakdown

    def _cached_breakdown(self, posting: JobPosting) -> ScoreBreakdown | None:
        rationale = getattr(posting, "rationale", None)
        if not isinstance(rationale, dict):
            return None
        raw = rationale.get(BREAKDOWN_KEY)
        if not isinstance(raw, dict):
            return None
        cached_score = raw.get("score")
        current_score = getattr(posting, "viability_score", None)
        # Only reuse while the cached breakdown's score still matches the
        # posting's CURRENT persisted score — a re-score invalidates it (the
        # trigger self-heals it anyway; this guards the lazy-read path too).
        if current_score is not None and cached_score is not None:
            try:
                if abs(float(cached_score) - float(current_score)) > 1e-6:
                    return None
            except (TypeError, ValueError):
                return None
        try:
            return self._breakdown_from_dict(posting.id, raw)
        except Exception:  # pragma: no cover - a malformed cache just recomputes
            return None

    @staticmethod
    def _breakdown_to_dict(breakdown: ScoreBreakdown) -> dict:
        return {
            "score": breakdown.score,
            "summary": breakdown.summary,
            "factors": [
                {
                    "label": f.label,
                    "polarity": f.polarity,
                    "weight": f.weight,
                    "contribution": f.contribution,
                    "source": f.source,
                    "detail": f.detail,
                }
                for f in breakdown.factors
            ],
        }

    @staticmethod
    def _breakdown_from_dict(posting_id: JobPostingId, raw: dict) -> ScoreBreakdown:
        factors = tuple(
            BreakdownFactor(
                label=str(f.get("label", "")),
                polarity=f.get("polarity", "neutral"),
                weight=float(f.get("weight", 0.0)),
                contribution=float(f.get("contribution", 0.0)),
                source=f.get("source", "deterministic"),
                detail=str(f.get("detail", "")),
            )
            for f in (raw.get("factors") or [])
            if isinstance(f, dict)
        )
        return ScoreBreakdown(
            posting_id=posting_id,
            score=float(raw.get("score", 0.0)),
            factors=factors,
            summary=str(raw.get("summary", "")),
        )
