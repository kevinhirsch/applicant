"""ScoringService (FR-AGENT-3).

Viability scoring from the JD: *can the user reasonably get this role?* — distinct from
resume-fit coverage (FR-RESUME-7, Phase 3). When the configured model is available the
score is a **semantic judgment** by the LLM (entry/L1 tier) of how well the posting
matches the candidate's stated criteria — role/seniority fit, skills overlap, work mode,
location, and comp. When no model is configured (or a call fails) it falls back to a
zero-token deterministic signal over criteria/JD overlap via local embeddings
(NFR-TOKEN-1), so scoring never hard-depends on the network.

When a LearningService is supplied, the score is biased toward the **converting-role
signature** (FR-LEARN-5): a role that looks like what has actually converted for this
campaign gets a small, transparent boost. Discovery and scoring thus both bend toward
the learned signature.

Before any of that runs, ``_score`` applies two DETERMINISTIC, no-LLM gates (the
catastrophic-miscalibration fix — prompt-only calibration of the LLM rubric alone was
tried twice and failed against the real discovery queue, where nearly every posting
scored 85-100 regardless of relevance): :func:`~applicant.core.rules.posting_quality
.check_posting_quality` floors non-postings (search-index pages, comparison/guide
articles, a methodology's own glossary page) to near zero, and
:func:`~applicant.core.rules.role_domain_fit.classify_role_domain` caps plainly
off-domain roles (IC/engineering-management software roles, product management,
data science, sales, legal, finance, marketing, video editing, research) low —
BEFORE the LLM ever runs, so neither can be talked back up by keyword density,
seniority, or pay. Both are pure/no-IO and only ever suppress a score, never lift one.

The viability **threshold defaults to 60** (on a 0..100 scale) and is configurable per
campaign; ``is_viable`` gates which postings reach the digest. A digest GET re-runs on
every view, so ``score_for_digest`` reuses a persisted score whenever the criteria are
unchanged (keyed by a criteria signature) rather than re-paying an LLM call per posting.
"""

from __future__ import annotations

import hashlib
import os

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.entities.viability_scoring import ViabilityScoring
from applicant.core.events import ViabilityScored, event_bus
from applicant.core.ids import JobPostingId
from applicant.core.rules.posting_quality import check_posting_quality
from applicant.core.rules.prompt_injection import neutralize_untrusted_text
from applicant.core.rules.role_domain_fit import classify_role_domain
from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import ChatMessage

log = get_logger(__name__)

#: Stdlib logger for the operational degrade-to-embeddings warning (#345). structlog
#: here renders through its own PrintLogger and does not propagate to the stdlib root,
#: so a score-less-reply warning must go through stdlib logging to be observable by
#: log handlers (and capturable in tests). Kept alongside the structured ``log``.
import logging as _logging  # noqa: E402

_std_log = _logging.getLogger(__name__)

#: Default viability threshold on a 0..100 scale (FR-AGENT-3); configurable.
DEFAULT_VIABILITY_THRESHOLD = 60
#: Neutral-positive default score when no search criteria are set (#344).
#: Configurable so operators can tune whether unscored postings are leaned
#: toward inclusion (higher) or exclusion (lower). 0.5 = neutral, 0.75 = lean
#: toward inclusion so nothing is silently dropped until criteria are stated.
DEFAULT_NEUTRAL_SCORE = 0.75
#: Max share of the score the converting-role signature can contribute (FR-LEARN-5).
_SIGNATURE_WEIGHT = 0.2

#: CATASTROPHIC-MISCALIBRATION FIX (live-queue incident: nearly every posting
#: scored 85-100 regardless of relevance, including a blog article and roles
#: like "Key Accounts Executive" / "Senior Product Security Engineer II").
#: Prompt-only calibration of the LLM rubric failed twice against the real
#: queue distribution, so these two DETERMINISTIC, no-LLM gates run FIRST in
#: ``_score`` and short-circuit straight to a fixed low score — cheap (no
#: model call) and, critically, a score the LLM can never talk back up.
#:
#: Comfortably under the "< 0.15" / "< 0.30" ceilings the fix requires, with
#: headroom for future rubric/threshold tuning without re-touching these.
_NON_POSTING_SCORE = 0.05
_OUT_OF_DOMAIN_SCORE = 0.15

#: P0 durability fix: how many CONSECUTIVE transient LLM failures a posting
#: tolerates before the resilience valve gives up and persists the degraded
#: embedding score anyway (see ``_persist_or_defer``). Without this cap, a
#: posting whose LLM call keeps failing would stay unscored forever and never
#: reach the digest. Tunable via ``SCORING_MAX_TRANSIENT_RETRIES`` (read fresh
#: per call, like ``agent_loop.py``'s ``SCORING_BATCH_PER_TICK`` — no restart
#: needed to change it).
DEFAULT_MAX_TRANSIENT_RETRIES = 3
#: Key the consecutive-transient-failure counter is stored under in the
#: existing nullable ``JobPosting.rationale`` JSON column — reused rather than
#: adding a schema migration. Cleared automatically the next time a real score
#: (LLM success, no-LLM-configured, or the retry-exhausted fallback) persists,
#: because ``_persist_score`` always writes a FRESH rationale dict.
_TRANSIENT_FAILURES_KEY = "transient_llm_failures"


class ScoringService:
    def __init__(
        self,
        storage,
        llm,
        embedding,
        *,
        threshold: int = DEFAULT_VIABILITY_THRESHOLD,
        neutral_score: float = DEFAULT_NEUTRAL_SCORE,
        max_transient_retries: int | None = None,
        learning=None,
        advanced_learning=None,
        tool_registry=None,
        agent_memory=None,
    ) -> None:
        self._storage = storage
        self._llm = llm
        self._embedding = embedding
        self._threshold = threshold
        self._neutral_score = neutral_score
        # P0 durability fix: bounded retry budget before a degraded (embedding
        # fallback) score is accepted as final. ``None`` (the default — every
        # existing construction site) reads ``SCORING_MAX_TRANSIENT_RETRIES`` fresh
        # here so an operator can tune it via env with no code change; an explicit
        # int (tests) overrides it directly.
        if max_transient_retries is None:
            try:
                max_transient_retries = int(
                    os.getenv("SCORING_MAX_TRANSIENT_RETRIES", "")
                    or DEFAULT_MAX_TRANSIENT_RETRIES
                )
            except (TypeError, ValueError):
                max_transient_retries = DEFAULT_MAX_TRANSIENT_RETRIES
        self._max_transient_retries = max_transient_retries
        self._learning = learning
        # Optional AdvancedLearningService so scoring can bias toward the DISCRETE
        # converting signature that the live conversion loop actually writes (+ an
        # advisory recall nudge), not just the Phase-1 centroid (FR-LEARN-5). ``None``
        # (default) => discrete/recall bias is skipped, byte-identical to before.
        self._advanced_learning = advanced_learning
        self._tools = tool_registry  # optional ToolRegistry for FR-UI-4 dispatch gate
        # Optional agent-memory trio (``.memory`` / ``.skills`` / ``.recall``,
        # FR-MIND-1). When wired, the LLM scorer gets the curated memory/preferences as
        # ADVISORY context so scoring reflects what the agent has learned about the
        # user's taste — complementing, never replacing, the criteria/conversion
        # learning. When ``None`` (the default), scoring is byte-identical to before.
        self._agent_memory = agent_memory

    @property
    def threshold(self) -> int:
        return self._threshold

    def score_viability(
        self, posting_id: JobPostingId, criteria: SearchCriteria | None = None
    ) -> ViabilityScoring:
        """Score a stored posting against the campaign criteria (local-first)."""
        posting = self._storage.postings.get(posting_id)
        if posting is None:
            return ViabilityScoring(posting_id=posting_id, score=0.0, rationale="posting not found")
        learning_model = self._load_learning_model(posting.campaign_id)
        advanced_model = self._load_advanced_model(posting.campaign_id)
        scoring = self._score(
            posting, criteria, learning_model=learning_model, advanced_model=advanced_model
        )
        persisted = self._persist_or_defer(
            posting,
            scoring,
            criteria_sig=self._criteria_sig(criteria),
            learning_sig=self._learning_sig(learning_model),
        )
        if persisted:
            # Only fire the "scored" domain event (and its audit-log entry) when the
            # score actually landed durably — a deferred degraded fallback (see
            # ``_persist_or_defer``) leaves the posting genuinely unscored, so an
            # event claiming it was scored would be misleading and would double up
            # once the real score persists on a later retry.
            event_bus.emit(
                ViabilityScored(
                    posting_id=posting_id,
                    score=scoring.score,
                    campaign_id=posting.campaign_id,
                )
            )
        return scoring

    def _persist_score(
        self,
        posting: JobPosting,
        scoring: ViabilityScoring,
        *,
        criteria_sig: str = "",
        learning_sig: str = "",
    ) -> None:
        """Durably store the viability score + rationale on the posting (FR-DIG-4).

        So the digest rationale survives restart instead of being recomputed every
        run. ``criteria_sig`` records WHICH criteria produced the score so the digest
        can reuse it only while the criteria are unchanged (it re-scores on a change).
        ``learning_sig`` (#239) records the learning-MODEL state the score was computed
        against so a new conversion / taste shift also invalidates the cached score —
        without it the digest kept returning the stale pre-conversion score until the
        user happened to edit their criteria. Best-effort: a storage hiccup must not
        break scoring/digest delivery.
        """
        import dataclasses

        try:
            updated = dataclasses.replace(
                posting,
                viability_score=scoring.score,
                rationale={
                    "text": scoring.rationale,
                    "viable": self.is_viable(scoring),
                    "criteria_sig": criteria_sig,
                    "learning_sig": learning_sig,
                },
            )
            self._storage.postings.add(updated)
            self._storage.commit()
        except Exception:  # pragma: no cover - never let persistence break scoring
            pass

    def _llm_configured(self) -> bool:
        """True iff an LLM tier is wired and reports itself configured."""
        llm = self._llm
        return llm is not None and getattr(llm, "is_configured", lambda: False)()

    def _persist_or_defer(
        self,
        posting: JobPosting,
        scoring: ViabilityScoring,
        *,
        criteria_sig: str = "",
        learning_sig: str = "",
    ) -> bool:
        """Persist ``scoring`` unless it's a degraded fallback that should be retried.

        THE P0 FIX: a transient LLM failure (timeout/transport/parse) used to
        degrade ``_base_score`` to the local embedding signal, and that degraded
        value was persisted unconditionally — embedding similarity almost never
        clears the viability threshold, so a posting hit by a one-off LLM hiccup
        was permanently buried below the threshold with no retry (``_unscored_postings``
        only ever revisits postings whose ``viability_score`` is still ``NULL``).

        When ``scoring.degraded`` is True AND an LLM tier IS configured (so a retry
        can plausibly succeed), this SKIPS persistence — ``viability_score`` stays
        whatever it already was (``None`` for a first-time posting), so the next
        tick's ``list_unscored_for_campaign`` retries it via the LLM — UNLESS the
        posting has now failed ``self._max_transient_retries`` times in a row, in
        which case the degraded value is accepted so the posting still makes
        progress instead of retrying forever. The two legitimate cases — an LLM
        success, or no LLM configured at all (``scoring.degraded`` is False in both,
        see ``_base_score``) — always persist immediately, byte-identical to before.

        Returns True iff the score was actually persisted (so the caller can decide
        whether firing a "scored" domain event is honest).
        """
        if scoring.degraded and self._llm_configured():
            failures = self._bump_transient_failures(posting)
            if failures < self._max_transient_retries:
                return False  # leave unscored for retry; do not persist the poisoned value
            # Retry budget exhausted: fall through and accept the degraded value so
            # the posting isn't stuck unscored forever.
        self._persist_score(posting, scoring, criteria_sig=criteria_sig, learning_sig=learning_sig)
        return True

    def _transient_failure_count(self, posting: JobPosting) -> int:
        """Consecutive-transient-LLM-failure count durably recorded on ``posting``."""
        rationale = getattr(posting, "rationale", None)
        if not isinstance(rationale, dict):
            return 0
        try:
            return int(rationale.get(_TRANSIENT_FAILURES_KEY, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _bump_transient_failures(self, posting: JobPosting) -> int:
        """Increment + durably persist the consecutive-transient-failure counter.

        Stored on the existing nullable ``JobPosting.rationale`` JSON column
        (no schema migration) so the count survives across scheduler ticks even
        while ``viability_score`` stays NULL. ``viability_score`` is deliberately
        left untouched here — only the bookkeeping key changes — so the posting
        stays in ``list_unscored_for_campaign`` until the retry budget is spent.
        Best-effort like ``_persist_score``: a storage hiccup must never break
        scoring; on failure this returns the WOULD-BE count so the caller's
        this-attempt decision is still correct even if it couldn't be durably
        recorded.
        """
        import dataclasses

        prior = getattr(posting, "rationale", None)
        prior = prior if isinstance(prior, dict) else {}
        count = self._transient_failure_count(posting) + 1
        try:
            updated = dataclasses.replace(
                posting, rationale={**prior, _TRANSIENT_FAILURES_KEY: count}
            )
            self._storage.postings.add(updated)
            self._storage.commit()
        except Exception:  # pragma: no cover - never let bookkeeping break scoring
            pass
        return count

    def _load_learning_model(self, campaign_id):
        """Load the per-campaign ``LearningModel`` ONCE for a scoring pass (perf).

        ``_score``/``_taste_bias``/``_signature_alignment``/``_learning_sig`` each
        independently called ``self._learning.load_model(campaign_id)`` before this
        change — up to 3 identical storage round-trips (a ``campaigns.get`` plus a
        ``discovery_sources.list_for_campaign`` scan, per ``LearningService.load_model``)
        for a SINGLE posting scored. ``load_model`` is a side-effect-free read and
        nothing in the scoring call tree writes learning state in between, so loading
        once per top-level call (``score_viability``/``score_for_digest``/
        ``score_posting``) and threading the result through is byte-identical to
        reloading at each call site — just without the redundant round-trips. Returns
        ``None`` when no learning service is wired or the load fails (mirrors the
        try/except every call site used to do individually).
        """
        if self._learning is None:
            return None
        try:
            return self._learning.load_model(campaign_id)
        except Exception:  # pragma: no cover - never let learning break scoring
            return None

    def _load_advanced_model(self, campaign_id):
        """Load the per-campaign advanced-learning model ONCE for a scoring pass.

        Companion to :meth:`_load_learning_model` — same perf rationale, separate
        provider (``AdvancedLearningService.load_model`` may not always delegate to
        the same ``LearningService`` instance as ``self._learning``, so this is kept
        as its own call rather than reused from ``_load_learning_model``).
        """
        if self._advanced_learning is None:
            return None
        try:
            return self._advanced_learning.load_model(campaign_id)
        except Exception:  # pragma: no cover - never let learning break scoring
            return None

    def _learning_sig(self, model) -> str:
        """Stable signature of the LEARNING state a score depends on (#239).

        Empty (``""``) when no learning service is wired or the model is at cold start
        (no conversions, no taste) — so a campaign with no learning reuses exactly as
        before. Folds the converting-role signature (centroid sample count + discrete
        feature keys/weights) AND the approve/decline ``feature_stats`` so that EITHER a
        new conversion OR a new taste signal yields a fresh signature, invalidating the
        stale cached score on the next digest. Guarded: a learning hiccup degrades to
        ``""`` (reuse on criteria alone) rather than breaking the digest.

        ``model`` is the pre-loaded ``LearningModel`` for this posting's campaign (see
        :meth:`_load_learning_model`) — ``None`` covers both "no learning wired" and "the
        load failed", exactly like the try/except this replaced.
        """
        if model is None:
            return ""
        sig = getattr(model, "converting_role_signature", {}) or {}
        samples = int(getattr(model, "converting_samples", 0) or 0)
        feature_stats = getattr(model, "feature_stats", {}) or {}
        # Sort for a deterministic, order-independent digest of the learning state.
        sig_part = ";".join(
            f"{k}={sig[k]}" for k in sorted(sig) if k != "vector"
        )
        # The centroid vector is a long float list; fold its sample count + a coarse
        # presence marker instead of every float (a new conversion bumps ``samples``).
        vector_present = "v" if sig.get("vector") else ""
        stats_part = ";".join(
            f"{feat}={sorted((feature_stats.get(feat) or {}).items())}"
            for feat in sorted(feature_stats)
        )
        material = f"{samples}|{vector_present}|{sig_part}|{stats_part}"
        if material == "0|||":
            return ""  # cold start: no learning state to key on
        return hashlib.blake2b(material.encode("utf-8"), digest_size=8).hexdigest()

    def _criteria_sig(self, criteria: SearchCriteria | None) -> str:
        """Stable signature of the criteria a score was computed against.

        Empty (``""``) when no meaningful criteria are set — so the neutral
        "no-criteria" score reuses consistently. Any change to titles/keywords/
        work-modes/locations/salary-floor/free-text yields a new signature, which
        invalidates the reuse in ``score_for_digest`` and forces a fresh score.
        """
        if criteria is None:
            return ""
        parts = [
            *getattr(criteria, "titles", ()),
            *getattr(criteria, "keywords", ()),
            *getattr(criteria, "work_modes", ()),
            *getattr(criteria, "locations", ()),
            str(getattr(criteria, "salary_floor", "") or ""),
            getattr(criteria, "human_readable", "") or "",
        ]
        text = "|".join(p for p in (str(x).strip() for x in parts) if p).lower()
        if not text:
            return ""
        return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()

    def score_for_digest(
        self, posting: JobPosting, criteria: SearchCriteria | None = None
    ) -> ViabilityScoring:
        """Score a posting for the digest view, reusing a persisted score when the
        criteria are unchanged (FR-DIG-3/4).

        The front-door ``GET /api/digest/{id}`` re-builds the digest on every view, so
        without reuse an LLM-backed score would re-pay one model call per posting each
        time. Reuse the durably-persisted score+rationale while its ``criteria_sig``
        matches the current criteria; otherwise compute fresh and persist it.
        """
        sig = self._criteria_sig(criteria)
        # Load the learning model ONCE — needed for ``learning_sig`` regardless of a
        # cache hit or miss. The ADVANCED model is only loaded below, lazily, on a
        # miss (it was never fetched on a hit path before this change either, since
        # a hit returns before ``_score`` ever runs) — no new work on the hit path.
        learning_model = self._load_learning_model(posting.campaign_id)
        learning_sig = self._learning_sig(learning_model)
        persisted = getattr(posting, "viability_score", None)
        rationale = getattr(posting, "rationale", None) or {}
        if (
            persisted is not None
            and isinstance(rationale, dict)
            and rationale.get("criteria_sig") == sig
            # #239: reuse only when the LEARNING state also matches — a new conversion
            # or taste shift changes ``learning_sig`` and forces a fresh, biased score.
            and rationale.get("learning_sig", "") == learning_sig
        ):
            return ViabilityScoring(
                posting_id=posting.id,
                score=persisted,
                rationale=str(rationale.get("text") or ""),
            )
        advanced_model = self._load_advanced_model(posting.campaign_id)
        scoring = self._score(
            posting, criteria, learning_model=learning_model, advanced_model=advanced_model
        )
        # P0 durability fix: a degraded (LLM-configured-but-failed) fallback must
        # not be persisted as authoritative — see ``_persist_or_defer``. ``scoring``
        # is still RETURNED so the digest can show the transient in-memory value
        # immediately; only the durable write is skipped/deferred.
        self._persist_or_defer(posting, scoring, criteria_sig=sig, learning_sig=learning_sig)
        return scoring

    def score_posting(
        self, posting: JobPosting, criteria: SearchCriteria | None = None
    ) -> ViabilityScoring:
        """Score an in-hand posting (no storage round-trip)."""
        learning_model = self._load_learning_model(posting.campaign_id)
        advanced_model = self._load_advanced_model(posting.campaign_id)
        return self._score(
            posting, criteria, learning_model=learning_model, advanced_model=advanced_model
        )

    def is_viable(self, scoring: ViabilityScoring) -> bool:
        """True if the scaled (0..100) score meets the configurable threshold.

        ROBUST: coalesce a missing score to 0.0 and re-clamp into [0, 1] before the
        comparison so a None/out-of-range score (e.g. from a nullable persisted value)
        can never raise ``TypeError`` on ``>=`` or let an >1.0 score pass the gate.
        """
        score = getattr(scoring, "score", None) or 0.0
        score = max(0.0, min(1.0, score))
        return score * 100.0 >= self._threshold

    def _score(
        self,
        posting: JobPosting,
        criteria: SearchCriteria | None,
        *,
        learning_model=None,
        advanced_model=None,
    ) -> ViabilityScoring:
        # Honor the Scoring tool toggle at dispatch (FR-UI-4).
        if self._tools is not None:
            self._tools.ensure_enabled("scoring")

        # DETERMINISTIC PRE-LLM GATES (catastrophic-miscalibration fix): run
        # BEFORE the criteria default / embedding / LLM ever execute, so a
        # non-posting or an off-domain role never reaches (and can never be
        # rescued by) the LLM's own judgment. Both are pure, no-IO checks on
        # the posting alone — independent of criteria/learning — so they run
        # unconditionally, even when no criteria are set yet.
        quality = check_posting_quality(
            posting.title, posting.source_url, posting.description or ""
        )
        if not quality.is_posting:
            return ViabilityScoring(
                posting_id=posting.id,
                score=_NON_POSTING_SCORE,
                rationale=(
                    "Not a specific job posting, so it scores near zero "
                    f"regardless of keyword overlap: {quality.reason}"
                ),
            )
        domain = classify_role_domain(posting.title, posting.description or "")
        if domain.in_domain is False:
            return ViabilityScoring(
                posting_id=posting.id,
                score=_OUT_OF_DOMAIN_SCORE,
                rationale=(
                    "Off-domain role — capped regardless of seniority, pay, "
                    f"or remote match: {domain.reason}"
                ),
            )

        if criteria is None:
            criteria = SearchCriteria(campaign_id=posting.campaign_id)
        criteria_text = " ".join(
            (*criteria.titles, *criteria.keywords, criteria.human_readable)
        ).strip()
        jd_text = f"{posting.title} {posting.description}".strip()
        degraded = False
        if not criteria_text:
            # No stated criteria yet: neutral-positive so nothing is silently dropped.
            base = 0.75
            rationale = "No search criteria set yet — scored neutral so nothing is dropped."
        else:
            base, rationale, degraded = self._base_score(posting, criteria, criteria_text, jd_text)
        # #237: fold the accumulated per-feature approve/decline TASTE into the base
        # score so the feedback loop actually closes — a posting carrying a value the
        # user has consistently declined is nudged down, an approved one nudged up.
        # ``1.0`` (no taste / no match) leaves the score byte-identical to before.
        taste = self._taste_bias(learning_model, f"{jd_text} {criteria_text}")
        if taste != 1.0:
            biased_base = max(0.0, min(1.0, base * taste))
            direction = "up" if taste > 1.0 else "down"
            rationale += (
                f"; nudged {direction} by your past approve/decline taste "
                f"(x{taste:.2f}, FR-LEARN-1)"
            )
            base = biased_base
        score = base
        alignment = self._signature_alignment(
            learning_model, advanced_model, posting.campaign_id, jd_text
        )
        if alignment > 0.0:
            # Blend toward the converting-role signature (FR-LEARN-5), transparently.
            score = (1.0 - _SIGNATURE_WEIGHT) * base + _SIGNATURE_WEIGHT * alignment
            rationale += (
                f"; biased toward converting-role signature "
                f"(alignment {alignment * 100:.0f}/100, FR-LEARN-5)"
            )
        return ViabilityScoring(
            posting_id=posting.id, score=score, rationale=rationale, degraded=degraded
        )

    def _base_score(
        self,
        posting: JobPosting,
        criteria: SearchCriteria,
        criteria_text: str,
        jd_text: str,
    ) -> tuple[float, str, bool]:
        """Base viability in [0, 1] + a plain-language rationale + a DEGRADED flag.

        Prefer the configured model's semantic judgment (entry/L1 tier); fall back to
        the local zero-token lexical-overlap signal when no model is configured or a
        call fails — the digest must never hard-depend on the network.

        The third element, ``degraded``, is True ONLY when an LLM tier IS configured
        but the call failed and this fell back to the embedding signal — the case
        the P0 durability fix (``ScoringService._persist_or_defer``) guards against:
        a transient failure must not be persisted as if it were an authoritative LLM
        judgment, or it permanently buries a posting below the viability threshold
        with no retry. ``degraded`` is False both when the LLM succeeds AND when no
        LLM is configured at all — in the latter case the embedding signal IS the
        authoritative score by design (NFR-TOKEN-1), exactly as before.
        """
        llm = self._llm
        if llm is not None and getattr(llm, "is_configured", lambda: False)():
            try:
                score, rationale = self._llm_base(posting, criteria)
                return score, rationale, False
            except Exception as exc:  # noqa: BLE001 - any model/parse failure degrades
                # #345: do NOT swallow the failure silently. A model reply that parses
                # but carries no ``score`` key (or any other model/parse error) must be
                # surfaced — naming the missing score — BEFORE we degrade to the local
                # embedding signal, so an operator can see a model is misbehaving rather
                # than only noticing a quietly-worse score.
                _std_log.warning(
                    "viability model returned no usable score (%s); degrading to the "
                    "local embedding signal for posting %s",
                    exc,
                    getattr(posting, "id", "?"),
                )
                base = self._embedding.similarity(criteria_text, jd_text)
                return (
                    base,
                    (
                        f"Match {base * 100:.0f}/100 from overlap between the role and "
                        f"your criteria (threshold {self._threshold})."
                    ),
                    True,
                )
        base = self._embedding.similarity(criteria_text, jd_text)
        return (
            base,
            (
                f"Match {base * 100:.0f}/100 from overlap between the role and your "
                f"criteria (threshold {self._threshold})."
            ),
            False,
        )

    def _llm_base(
        self, posting: JobPosting, criteria: SearchCriteria
    ) -> tuple[float, str]:
        """Ask the model to score the posting against the criteria (0-100 + reason)."""
        crit_lines = []
        if criteria.titles:
            crit_lines.append("Target titles: " + ", ".join(criteria.titles))
        if getattr(criteria, "work_modes", ()):  # noqa: SIM222
            crit_lines.append("Acceptable work modes: " + ", ".join(criteria.work_modes))
        if getattr(criteria, "locations", ()):
            crit_lines.append("Locations: " + ", ".join(criteria.locations))
        if getattr(criteria, "salary_floor", None):
            crit_lines.append(f"Minimum acceptable salary: {criteria.salary_floor}")
        if criteria.keywords:
            crit_lines.append("Skills / keywords: " + ", ".join(criteria.keywords))
        if criteria.human_readable:
            crit_lines.append("In their own words: " + criteria.human_readable)
        criteria_block = "\n".join(crit_lines) or "(no explicit criteria)"
        # Neutralize untrusted scraped text before it enters the LLM prompt so an
        # attacker-controlled job description cannot steer the score (FR-SEC-6).
        safe_description = neutralize_untrusted_text(posting.description or "")
        jd_block = "\n".join(
            line
            for line in [
                f"Title: {neutralize_untrusted_text(posting.title or '')}",
                # The source URL carries structural signal GATE 1/3 below rely on
                # (a search/index path, a methodology-reference domain, a city
                # baked into a job-board URL slug) that the title/description
                # alone often omit — neutralized like every other scraped field.
                f"Source URL: {neutralize_untrusted_text(posting.source_url or '')}" if posting.source_url else "",
                f"Company: {neutralize_untrusted_text(posting.company or '')}" if posting.company else "",
                f"Work mode: {neutralize_untrusted_text(posting.work_mode or '')}" if posting.work_mode else "",
                f"Location: {neutralize_untrusted_text(posting.location or '')}" if posting.location else "",
                f"Salary: {neutralize_untrusted_text(posting.salary or '')}" if posting.salary else "",
                f"Description: {safe_description}" if posting.description else "",
            ]
            if line
        )
        system_text = (
            "You score how well a job posting matches a job-seeker's stated search "
            "criteria — whether this is a role they would plausibly want AND could "
            "realistically get. Work through these checks IN ORDER; each is a GATE — "
            "if a gate fails, the posting scores LOW (single digits to about 20) "
            "regardless of how well its keywords overlap the criteria.\n\n"
            "GATE 1 — Is this an actual, single, specific job opening at one "
            "employer? Score 0-10 if it is instead: a search-results/index page "
            "listing MANY openings (title patterns like 'X Jobs | Site', 'Jobs, "
            "Employment | Site', a leading result count e.g. '132 ... jobs' or "
            "'1,000+ ... jobs' or 'Top N ... Jobs', an hourly-rate query title e.g. "
            "'$51-$83/hr ... Jobs'); a comparison or explainer ARTICLE (title "
            "contains ' vs ', 'Explained', 'Career Path'/'Guide', 'Key "
            "Differences', a forum thread, a blog/Medium post); a methodology's "
            "OWN reference/glossary/certification page (e.g. Scaled Agile's own "
            "site defining what an RTE or Scrum Master IS, rather than a company "
            "hiring one); or site-navigation/related-jobs boilerplate captured as "
            "the description (e.g. 'N open jobs · ... jobs · ... jobs'). A "
            "useful tell: when 'Company' is a search engine or aggregator name "
            "('google cse', 'brave', 'duckduckgo', 'bing') rather than a real "
            "employer, look HARDER for the structural patterns above — but that "
            "alone is NEVER a reason to fail this gate. Discovery routinely finds "
            "real postings via a search engine, so 'Company' shows the search "
            "engine, not the employer, on many genuine postings too. If the URL "
            "points at a SPECIFIC job (a numbered/UUID job id, a '/jobs/view/...' "
            "or 'JobDetail'/'/job/...' path on an employer's own careers site or "
            "ATS — Greenhouse, Lever, Workday, a company's own careers domain), "
            "treat it as a real posting even when 'Company' is a search-engine "
            "name and the description is thin. This gate is about STRUCTURE, "
            "not content quality — a real "
            "posting with a thin or blocked description (e.g. 'we cannot provide "
            "a description') still PASSES this gate; judge it on title/company/URL "
            "context instead of failing it for a missing description. If you "
            "determine this IS a search-results/index/article/glossary/"
            "boilerplate page, THE SCORE MUST BE single digits-to-10 — a "
            "keyword-dense aggregator title (e.g. 'Release Train Engineer Jobs | "
            "Dice.com') is NOT a partial match; it is not a job at all.\n\n"
            "GATE 2 — Role/domain fit. Score low for an off-domain role even if it "
            "is senior, remote, and well-paid: general software-ENGINEERING "
            "management ('Manager/Director, Software Engineering'), IC "
            "engineering, solutions/enterprise architecture, sales, account "
            "management, or data science are OFF-DOMAIN. A 'Program Manager' / "
            "'Technical Program Manager' / 'Delivery Manager' title is NOT enough "
            "by itself — score it HIGH only when the role's actual core is "
            "agile-delivery facilitation/coaching (running Scrum/Kanban "
            "ceremonies, PI Planning, Release Train coordination, "
            "Scrum-of-Scrums, agile transformation, servant leadership for "
            "delivery teams). A TPM/PgM role that is really about platform "
            "strategy, general cross-functional roadmap execution, or "
            "engineering-org operations WITHOUT agile facilitation as the core is "
            "OFF-DOMAIN even if 'Agile' or 'Scrum' is mentioned in passing. If the "
            "JD's actual day-to-day is writing code, building software/AI "
            "systems, dashboards, or integrations — a 'hands-on technical "
            "builder' — it is OFF-DOMAIN regardless of the title, even when "
            "'program manager' is the job title. THE SCORE MUST MATCH THIS "
            "VERDICT: an off-domain role stays in the single digits-to-20 range "
            "even if it is a strong title/seniority/remote/pay match on paper — "
            "never let those other overlaps pull an off-domain role's score back "
            "up.\n\n"
            "GATE 3 — Work mode / location. Work through this in order: "
            "(1) If the posting explicitly says remote / remote-first / work "
            "from home / work from anywhere in the US, remote is CONFIRMED — no "
            "penalty. (2) Otherwise, if a specific city/region is named ANYWHERE "
            "(title, URL, description — e.g. 'in Charlotte, North Carolina', a "
            "'/job/austin/' URL slug, 'Reston', a city-specific job board name "
            "like 'Built In San Francisco'), or a non-US country/city is named, "
            "or a security-clearance requirement (TS/SCI, Secret) is present, "
            "remote is CONFIRMED-NO — score LOW (single digits-to-20), THE SAME "
            "AS AN OFF-DOMAIN role: do not let a perfect title/domain match on "
            "paper pull a confirmed-non-remote posting's score back up into the "
            "60s-90s — if your own rationale names a specific city, a clearance, "
            "or a non-US location as the reason, the number you output MUST be "
            "low, not merely 'lower than it would otherwise be'. A named city "
            "with no remote qualifier attached is NOT the same as 'unstated' — "
            "it is a confirmed non-remote signal even though no field literally "
            "says 'onsite'. (3) ONLY when NEITHER of the above applies — truly no "
            "city, no country, no clearance, no remote/onsite language ANYWHERE "
            "in the title, URL, company, or description — is work mode "
            "genuinely unstated: DEDUCT NOTHING for it, score as if it matches "
            "the criteria, and judge the posting on role/domain fit alone. "
            "Worked example: a 'Senior Scrum Master / Release Train Engineer' "
            "posting with no city, no clearance, and no remote/onsite wording "
            "anywhere scores in the 80s-90s on role/domain fit alone — EXACTLY "
            "as if it had explicitly said 'Remote'. Never justify a score below "
            "75 by citing 'work mode unstated' or 'salary unstated' when "
            "nothing else is wrong with the posting — case (3) above means "
            "treat it as satisfied, not as a small deduction. The same "
            "three-way logic applies to salary: only penalize a STATED figure "
            "below the floor, never an unstated one.\n\n"
            "If a posting clears all three gates, score its role/seniority/skills "
            "overlap against the criteria normally (higher = better match). "
            "Score a junior/entry role low for a senior candidate. Before you "
            "answer, check your own rationale: if it names a gate failure (not "
            "a specific single posting / off-domain / confirmed non-remote), "
            "your 'score' number MUST be single digits-to-20 — a rationale that "
            "identifies a failed gate and a score above 20 CONTRADICTS ITSELF; "
            "fix the number, not the words.\n\n"
            "ONLY IF you just confirmed above that NO gate failed (the score "
            "is NOT single digits-to-20) — apply one more, LAST ranking nudge "
            "among already-viable postings, AFTER everything above, and never "
            "before it: TASTE PREFERENCE. This is a nudge, NOT a gate, and it "
            "NEVER applies to and NEVER rescues a posting that failed Gate 1, "
            "2, or 3 above — a confirmed non-remote/onsite, off-domain, or "
            "non-posting verdict keeps its single-digits-to-20 score no "
            "matter how SAFe/RTE-flavored the role is; do not revisit that "
            "number here. For a posting that IS already viable: the "
            "candidate is SAFe-certified and fully qualified for and open to "
            "SAFe roles, but prefers Large-Scale Scrum (LeSS) or framework-"
            "agnostic Scrum/Kanban delivery work. TOP band, 85-100 on domain "
            "fit: a LeSS-aligned role (mentions 'LeSS' or 'Large-Scale "
            "Scrum') or a framework-agnostic/plain-Scrum role (Scrum "
            "Master, Agile Coach, or Agile Delivery facilitating Scrum/"
            "Kanban with no SAFe framing). SAFe SUB-TOP band, typically "
            "75-88 and never below 70 for this reason alone: any already-"
            "viable role that foregrounds 'SAFe'/'Scaled Agile Framework', "
            "a SAFe-branded title/keyword ('SAFe RTE', 'SAFe Scrum "
            "Master', 'Team Coach'), OR a Release Train Engineer/RTE title "
            "— RTE is itself a SAFe-defined role even when the word 'SAFe' "
            "is never used, so score it a notch below a comparable LeSS/"
            "agnostic role; it is still clearly viable, never a "
            "disqualification. A posting at a known LeSS shop (e.g. Wells "
            "Fargo) gets a small extra lift toward the top of its band.\n\n"
            "Respond ONLY with JSON: an integer "
            "'score' 0-100 (100 = ideal) and a one-sentence 'rationale' in plain "
            "language a non-technical user can read, naming which gate (if any) "
            "drove the score."
        )
        # FR-MIND-1/5: advisory curated memory about the user's taste/preferences, read
        # fresh per call (FR-MIND-10). It NUDGES scoring toward what the agent has
        # learned the user likes/avoids; it never overrides the criteria/conversion
        # learning and confers no authority (FR-MIND-11).
        learned = self._learned_context(posting.campaign_id)
        if learned:
            system_text += "\n\n" + learned
        system = ChatMessage(role="system", content=system_text)
        user = ChatMessage(
            role="user",
            content=(
                f"CANDIDATE CRITERIA:\n{criteria_block}\n\n"
                f"JOB POSTING:\n{jd_block}\n\n"
                "Score this posting 0-100."
            ),
        )
        schema = {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                "rationale": {"type": "string"},
            },
            "required": ["score", "rationale"],
        }
        result = self._llm.complete(
            [system, user], start_tier=1, json_schema=schema, max_tokens=250
        )
        data = result.structured or {}
        if not data and getattr(result, "text", ""):
            data = self._parse_json_loose(result.text)
        raw = data.get("score")
        if raw is None:
            raise ValueError("model returned no score")
        score = max(0.0, min(1.0, float(raw) / 100.0))
        rationale = str(data.get("rationale") or "").strip() or (
            f"Scored {round(score * 100)}/100 against your criteria."
        )
        return score, rationale

    @staticmethod
    def _parse_json_loose(text: str) -> dict:
        """Best-effort extract a JSON object from a model reply (defensive).

        Logs a warning when the extracted dict lacks a ``score`` key (#345) so
        operators can detect models that silently omit the expected field rather
        than having the error swallowed in the caller's fallback chain.
        """
        import json
        import re

        obj: dict = {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                obj = parsed
        except Exception:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        obj = parsed
                except Exception:
                    pass
        if obj and "score" not in obj:
            log.warning("parse_json_loose_missing_score", snippet=text[:200])
        return obj

    def _learned_context(self, campaign_id) -> str:
        """A BOUNDED, advisory curated-memory block about the user's taste (FR-MIND-1/5).

        Read fresh from the agent-memory trio on every call (never cached on the
        instance — FR-MIND-10). Surfaces a few curated memory lines (the user's
        preferences/style) so the scorer reflects what the agent has learned the user
        likes or avoids in a role. ADVISORY ONLY (FR-MIND-11): any line that *claims* a
        safety-gated authority is dropped via the core ``claims_authority`` rule; the
        block can only nudge the score, never override the criteria or grant authority.

        Degrades silently to ``""`` when no ``agent_memory`` is wired (byte-identical to
        the prior behavior) or nothing is on file.
        """
        am = self._agent_memory
        if am is None:
            return ""
        from applicant.core.rules.agent_memory import claims_authority

        try:
            snap = am.memory.snapshot(campaign_id=str(campaign_id))
        except Exception:
            return ""
        if snap is None:
            return ""
        mem_lines: list[str] = []
        for e in (tuple(snap.user) + tuple(snap.environment))[:8]:
            txt = getattr(e, "text", "")
            if not txt or claims_authority(txt):
                continue  # advisory-only: never surface an authority claim
            mem_lines.append(f"- {txt}")
        if not mem_lines:
            return ""
        block = (
            "What you have learned about this user's taste and preferences "
            "(advisory — let it nudge, not override, the criteria above):\n"
            + "\n".join(mem_lines)
        )
        # Hard-bound so learned context never bloats the scoring prompt (FR-MIND-13).
        return block[:1200]

    def _taste_bias(self, learning_model, text: str) -> float:
        """Accumulated approve/decline taste multiplier for a posting (#237, FR-LEARN-1).

        Reads the per-campaign ``feature_stats`` taste signal through the wired
        ``LearningService`` and returns a bounded multiplier in ``[0.8, 1.2]``. Returns
        ``1.0`` (no bias) when no learning service is wired or nothing matches, so a
        cold campaign — and the no-learning baseline scorer — score byte-identically to
        before. Guarded: a learning/storage hiccup must never 500 the digest.

        ``learning_model`` is the pre-loaded model from :meth:`_load_learning_model`
        (``None`` covers both "no learning wired" and "the load failed", same net
        effect as the try/except this replaced).
        """
        if self._learning is None or learning_model is None:
            return 1.0
        try:
            return self._learning.taste_bias(learning_model, text)
        except Exception:  # pragma: no cover - taste bias must never break scoring
            return 1.0

    def _signature_alignment(
        self, learning_model, advanced_model, campaign_id, jd_text: str
    ) -> float:
        """Advisory converting-signature alignment in [0,1] for a JD (FR-LEARN-5).

        Combines, via ``max`` (NOT a sum — so the same conversion evidence is never
        double-counted), three complementary, read-only views of what converts:

          * the Phase-1 embedding CENTROID (``LearningService.converting_alignment``),
          * the DISCRETE role-feature signature the live conversion loop actually
            writes (``AdvancedLearningService.text_alignment``), and
          * a small ADVISORY recall nudge ("roles like the ones that converted",
            ``AdvancedLearningService.recall_alignment``, FR-MIND-3).

        These are different facets each folded ONCE per conversion (centroid vs
        discrete features vs durable run history); reading all three biases ranking
        without re-folding any signal. 0.0 at cold start (no conversions, no recall)
        so a brand-new campaign scores byte-identically to before.

        ``learning_model``/``advanced_model`` are pre-loaded once per scoring pass
        (see :meth:`_load_learning_model`/:meth:`_load_advanced_model`) rather than
        reloaded here — ``recall_alignment`` takes no model and is still attempted
        whenever ``self._advanced_learning`` is wired, independent of whether the
        model load succeeded, exactly as before.
        """
        signals: list[float] = []
        if self._learning is not None and learning_model is not None:
            try:
                # Keep the alignment call inside the guard: a flaky embedding must not
                # 500 GET /api/digest/{id} or scoring — fall back to no bias instead.
                signals.append(self._learning.converting_alignment(learning_model, jd_text))
            except Exception:
                pass
        if self._advanced_learning is not None:
            if advanced_model is not None:
                try:
                    signals.append(
                        self._advanced_learning.text_alignment(advanced_model, jd_text)
                    )
                except Exception:
                    pass
            try:
                signals.append(
                    self._advanced_learning.recall_alignment(campaign_id, jd_text)
                )
            except Exception:
                pass
        return max(signals) if signals else 0.0
