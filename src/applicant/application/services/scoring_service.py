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

The viability **threshold defaults to 70** (on a 0..100 scale) and is configurable per
campaign; ``is_viable`` gates which postings reach the digest. A digest GET re-runs on
every view, so ``score_for_digest`` reuses a persisted score whenever the criteria are
unchanged (keyed by a criteria signature) rather than re-paying an LLM call per posting.
"""

from __future__ import annotations

import hashlib

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.entities.viability_scoring import ViabilityScoring
from applicant.core.events import ViabilityScored, event_bus
from applicant.core.ids import JobPostingId
from applicant.core.rules.prompt_injection import neutralize_untrusted_text
from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import ChatMessage

log = get_logger(__name__)

#: Default viability threshold on a 0..100 scale (FR-AGENT-3); configurable.
DEFAULT_VIABILITY_THRESHOLD = 70
#: Neutral-positive default score when no search criteria are set (#344).
#: Configurable so operators can tune whether unscored postings are leaned
#: toward inclusion (higher) or exclusion (lower). 0.5 = neutral, 0.75 = lean
#: toward inclusion so nothing is silently dropped until criteria are stated.
DEFAULT_NEUTRAL_SCORE = 0.75
#: Max share of the score the converting-role signature can contribute (FR-LEARN-5).
_SIGNATURE_WEIGHT = 0.2


class ScoringService:
    def __init__(
        self,
        storage,
        llm,
        embedding,
        *,
        threshold: int = DEFAULT_VIABILITY_THRESHOLD,
        neutral_score: float = DEFAULT_NEUTRAL_SCORE,
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
        scoring = self._score(posting, criteria)
        self._persist_score(
            posting,
            scoring,
            criteria_sig=self._criteria_sig(criteria),
            learning_sig=self._learning_sig(posting.campaign_id),
        )
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

    def _learning_sig(self, campaign_id) -> str:
        """Stable signature of the LEARNING state a score depends on (#239).

        Empty (``""``) when no learning service is wired or the model is at cold start
        (no conversions, no taste) — so a campaign with no learning reuses exactly as
        before. Folds the converting-role signature (centroid sample count + discrete
        feature keys/weights) AND the approve/decline ``feature_stats`` so that EITHER a
        new conversion OR a new taste signal yields a fresh signature, invalidating the
        stale cached score on the next digest. Guarded: a learning hiccup degrades to
        ``""`` (reuse on criteria alone) rather than breaking the digest.
        """
        if self._learning is None:
            return ""
        try:
            model = self._learning.load_model(campaign_id)
        except Exception:  # pragma: no cover - never let learning break scoring
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
        learning_sig = self._learning_sig(posting.campaign_id)
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
        scoring = self._score(posting, criteria)
        self._persist_score(posting, scoring, criteria_sig=sig, learning_sig=learning_sig)
        return scoring

    def score_posting(
        self, posting: JobPosting, criteria: SearchCriteria | None = None
    ) -> ViabilityScoring:
        """Score an in-hand posting (no storage round-trip)."""
        return self._score(posting, criteria)

    def is_viable(self, scoring: ViabilityScoring) -> bool:
        """True if the scaled (0..100) score meets the configurable threshold.

        ROBUST: coalesce a missing score to 0.0 and re-clamp into [0, 1] before the
        comparison so a None/out-of-range score (e.g. from a nullable persisted value)
        can never raise ``TypeError`` on ``>=`` or let an >1.0 score pass the gate.
        """
        score = getattr(scoring, "score", None) or 0.0
        score = max(0.0, min(1.0, score))
        return score * 100.0 >= self._threshold

    def _score(self, posting: JobPosting, criteria: SearchCriteria | None) -> ViabilityScoring:
        # Honor the Scoring tool toggle at dispatch (FR-UI-4).
        if self._tools is not None:
            self._tools.ensure_enabled("scoring")
        if criteria is None:
            criteria = SearchCriteria(campaign_id=posting.campaign_id)
        criteria_text = " ".join(
            (*criteria.titles, *criteria.keywords, criteria.human_readable)
        ).strip()
        jd_text = f"{posting.title} {posting.description}".strip()
        if not criteria_text:
            # No stated criteria yet: neutral-positive so nothing is silently dropped.
            base = 0.75
            rationale = "No search criteria set yet — scored neutral so nothing is dropped."
        else:
            base, rationale = self._base_score(posting, criteria, criteria_text, jd_text)
        # #237: fold the accumulated per-feature approve/decline TASTE into the base
        # score so the feedback loop actually closes — a posting carrying a value the
        # user has consistently declined is nudged down, an approved one nudged up.
        # ``1.0`` (no taste / no match) leaves the score byte-identical to before.
        taste = self._taste_bias(posting.campaign_id, f"{jd_text} {criteria_text}")
        if taste != 1.0:
            biased_base = max(0.0, min(1.0, base * taste))
            direction = "up" if taste > 1.0 else "down"
            rationale += (
                f"; nudged {direction} by your past approve/decline taste "
                f"(x{taste:.2f}, FR-LEARN-1)"
            )
            base = biased_base
        score = base
        alignment = self._signature_alignment(posting.campaign_id, jd_text)
        if alignment > 0.0:
            # Blend toward the converting-role signature (FR-LEARN-5), transparently.
            score = (1.0 - _SIGNATURE_WEIGHT) * base + _SIGNATURE_WEIGHT * alignment
            rationale += (
                f"; biased toward converting-role signature "
                f"(alignment {alignment * 100:.0f}/100, FR-LEARN-5)"
            )
        return ViabilityScoring(posting_id=posting.id, score=score, rationale=rationale)

    def _base_score(
        self,
        posting: JobPosting,
        criteria: SearchCriteria,
        criteria_text: str,
        jd_text: str,
    ) -> tuple[float, str]:
        """Base viability in [0, 1] + a plain-language rationale.

        Prefer the configured model's semantic judgment (entry/L1 tier); fall back to
        the local zero-token lexical-overlap signal when no model is configured or a
        call fails — the digest must never hard-depend on the network.
        """
        llm = self._llm
        if llm is not None and getattr(llm, "is_configured", lambda: False)():
            try:
                return self._llm_base(posting, criteria)
            except Exception:
                pass  # degrade to the local signal below
        base = self._embedding.similarity(criteria_text, jd_text)
        return base, (
            f"Match {base * 100:.0f}/100 from overlap between the role and your "
            f"criteria (threshold {self._threshold})."
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
                f"Title: {posting.title}",
                f"Company: {posting.company}" if posting.company else "",
                f"Work mode: {posting.work_mode}" if posting.work_mode else "",
                f"Location: {posting.location}" if posting.location else "",
                f"Salary: {posting.salary}" if posting.salary else "",
                f"Description: {safe_description}" if posting.description else "",
            ]
            if line
        )
        system_text = (
            "You score how well a job posting matches a job-seeker's stated search "
            "criteria — whether this is a role they would plausibly want AND could "
            "realistically get. Weigh role/title and seniority fit, required-skills "
            "overlap, work mode, location, and compensation against the criteria. "
            "Score a junior/entry role low for a senior candidate; an off-domain "
            "role (e.g. front-end when they want back-end) low; an onsite/relocation "
            "role low when they want remote; a pay-floor miss low. Respond ONLY with "
            "JSON: an integer 'score' 0-100 (100 = ideal) and a one-sentence "
            "'rationale' in plain language a non-technical user can read."
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

    def _taste_bias(self, campaign_id, text: str) -> float:
        """Accumulated approve/decline taste multiplier for a posting (#237, FR-LEARN-1).

        Reads the per-campaign ``feature_stats`` taste signal through the wired
        ``LearningService`` and returns a bounded multiplier in ``[0.8, 1.2]``. Returns
        ``1.0`` (no bias) when no learning service is wired or nothing matches, so a
        cold campaign — and the no-learning baseline scorer — score byte-identically to
        before. Guarded: a learning/storage hiccup must never 500 the digest.
        """
        if self._learning is None:
            return 1.0
        try:
            model = self._learning.load_model(campaign_id)
            return self._learning.taste_bias(model, text)
        except Exception:  # pragma: no cover - taste bias must never break scoring
            return 1.0

    def _signature_alignment(self, campaign_id, jd_text: str) -> float:
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
        """
        signals: list[float] = []
        if self._learning is not None:
            try:
                model = self._learning.load_model(campaign_id)
                # Keep the alignment call inside the guard: a flaky embedding must not
                # 500 GET /api/digest/{id} or scoring — fall back to no bias instead.
                signals.append(self._learning.converting_alignment(model, jd_text))
            except Exception:
                pass
        if self._advanced_learning is not None:
            try:
                model = self._advanced_learning.load_model(campaign_id)
                signals.append(self._advanced_learning.text_alignment(model, jd_text))
            except Exception:
                pass
            try:
                signals.append(
                    self._advanced_learning.recall_alignment(campaign_id, jd_text)
                )
            except Exception:
                pass
        return max(signals) if signals else 0.0
