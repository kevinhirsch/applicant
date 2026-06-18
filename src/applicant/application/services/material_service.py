"""MaterialService (FR-RESUME-1/2/5/6/7/8/10, FR-ANSWER-1, NFR-TRUTH-1).

# STAGE B — owned by Phase 3.

The material-generation + interactive-feedback engine. It:

* **selects or generates** a resume variant for a posting using a fit score
  (FR-RESUME-7, threshold default >= 70) with parent lineage (FR-RESUME-6);
* generates **cover letters** (FR-RESUME-10) and **screening answers**
  (FR-ANSWER-1, factual vs essay) on demand;
* applies the **truthfulness guardrail** (reframe, never fabricate — FR-RESUME-2)
  and the **em-dash + banned-phrase post-filter** + voice-matching on every pass
  (FR-RESUME-5) via ``core.rules.truthfulness``;
* budgets generation to **1 LLM pass + 2 refinements** then routes to review;
* drives the **interactive revision-session loop** (add/subtract/free-text,
  FR-RESUME-8) and enforces the **review gate before submission**
  (``core.rules.review_gate``).

The LLM is optional: when absent (or stubbed) generation falls back to a
deterministic reframing of the supplied true source so the engine never blocks and
never fabricates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.resume_variant import ResumeFitScoring, ResumeVariant
from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.errors import InvalidInput, NotFound, TruthfulnessViolation
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    ResumeVariantId,
    RevisionSessionId,
    new_id,
)
from applicant.core.rules.materials import (
    AGGRESSIVENESS_DEFAULT,
    ScreeningKind,
    aggressiveness_directive,
    clamp_aggressiveness,
    classify_screening_question,
    should_generate_cover_letter,
)
from applicant.core.rules.review_gate import ensure_submittable
from applicant.core.rules.sensitive_fields import (
    DECLINE_TO_SELF_IDENTIFY,
    decide_sensitive_fill,
)
from applicant.core.rules.truthfulness import (
    VoiceProfile,
    candidate_claim_tokens,
    extract_voice_profile,
    find_banned_phrases,
    normalize_emdashes,
    strip_banned_phrases,
    unsupported_claims,
    unsupported_prose_claims,
    voice_alignment,
)

#: FR-RESUME-7 default selection threshold (coverage as a 0-100 percentage).
FIT_THRESHOLD = 70
#: FR-RESUME-* generation budget: 1 initial LLM pass + this many refinements.
REFINEMENT_BUDGET = 2
#: FR-RESUME-6 sprawl cap: max approved reusable parents kept per campaign before
#: clustering collapses near-duplicates.
VARIANT_CAP = 8
#: Two variants whose targeted-JD signatures embed above this similarity are
#: treated as the same cluster (FR-RESUME-6 cluster/cap, reuses the embedding port).
CLUSTER_SIMILARITY = 0.92
#: How much the converting-role signature alignment biases variant selection
#: (FR-LEARN-5). A small tiebreak so JD coverage still dominates the choice.
_CONVERTING_BIAS_WEIGHT = 0.25


@dataclass(frozen=True)
class FilterReport:
    """Result of the deterministic non-AI-looking post-filter (FR-RESUME-5)."""

    text: str
    em_dashes_stripped: bool
    banned_phrases: tuple[str, ...]
    voice_alignment: float = 1.0

    @property
    def clean(self) -> bool:
        return not self.banned_phrases


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of variant selection/generation for a posting (FR-RESUME-6/7)."""

    variant: ResumeVariant
    fit: ResumeFitScoring
    generated: bool  # True if a new variant was forked, False if a reuse


class MaterialService:
    def __init__(
        self,
        storage,
        llm=None,
        resume_tailoring=None,
        *,
        embedding=None,
        docx_tailoring=None,
        conversion_service=None,
        notifications=None,
        pending_actions=None,
        learning=None,
        advanced_learning=None,
        review_base_url: str = "/review",
    ) -> None:
        self._storage = storage
        self._llm = llm
        self._resume_tailoring = resume_tailoring  # default/LaTeX engine
        self._docx_tailoring = docx_tailoring  # docx fallback engine
        self._embedding = embedding  # local embedding port (variant clustering)
        self._conversion = conversion_service  # per-campaign engine choice (Phase 0)
        # Optional LearningService so variant selection can prefer variants whose
        # traits match the converting-role signature (FR-LEARN-5).
        self._learning = learning
        # Optional AdvancedLearningService so a redline add/subtract/free-text turn
        # folds the user's revision feedback into learning (FR-LEARN-3 / FR-RESUME-8).
        self._advanced_learning = advanced_learning
        # Review-ready notification ladder + pending-actions home base (FR-NOTIF-4).
        self._notifications = notifications
        self._pending_actions = pending_actions
        self._review_base_url = review_base_url
        # UI-editable banned-phrase list (FR-RESUME-5); supplements the core seed.
        self._extra_banned: tuple[str, ...] = ()
        # Voice profile extracted from the user's corpus (FR-RESUME-5).
        self._voice: VoiceProfile = VoiceProfile()
        # Truthful-framing dial (FR-RESUME-9); present-but-grayed in the UI (FR-UI-2)
        # but wired so a backend-only flip makes it live.
        self._aggressiveness: int = AGGRESSIVENESS_DEFAULT

    # === engine selection (FR-RESUME-3a; respects Phase 0 ConversionService) ===
    def tailoring_for(self, campaign_id: CampaignId):
        """Return the tailoring adapter for the campaign's chosen engine.

        Phase 0's ConversionService persists the per-campaign engine (LaTeX vs
        docx) at the accept/reject gate; generation respects that choice. Falls
        back to the configured default adapter when no choice/adapter is wired.
        """
        if self._conversion is not None and self._docx_tailoring is not None:
            try:
                engine = self._conversion.get_engine(str(campaign_id))
            except Exception:
                engine = None
            if engine == "docx":
                return self._docx_tailoring
        return self._resume_tailoring

    # === banned-phrase list (UI-editable, FR-RESUME-5) ====================
    def set_banned_phrases(self, phrases: list[str]) -> None:
        """Replace the UI-editable banned-phrase list (FR-RESUME-5)."""
        self._extra_banned = tuple(p for p in phrases if p and p.strip())

    @property
    def banned_phrases(self) -> tuple[str, ...]:
        return self._extra_banned

    # === aggressiveness dial (FR-RESUME-9, dormant per FR-UI-2) ============
    def set_aggressiveness(self, value: int | None) -> int:
        """Set the truthful-framing dial (FR-RESUME-9), clamped into range.

        The control is grayed/dormant in the UI (FR-UI-2); this setter wires the
        backend so flipping it live later is a UI change only. The dial only biases
        framing (assertive vs measured), never the truthfulness guardrail.
        """
        self._aggressiveness = clamp_aggressiveness(value)
        return self._aggressiveness

    @property
    def aggressiveness(self) -> int:
        return self._aggressiveness

    # === voice matching (FR-RESUME-5) =====================================
    def load_voice_corpus(self, corpus: list[str]) -> VoiceProfile:
        """Extract + cache the voice profile from the user's resume corpus."""
        self._voice = extract_voice_profile(corpus)
        return self._voice

    @property
    def voice(self) -> VoiceProfile:
        return self._voice

    # === non-AI-looking post-filter (FR-RESUME-5) =========================
    def apply_post_filter(self, text: str) -> FilterReport:
        """Strip em-dashes + banned phrases deterministically; score voice alignment.

        Runs on EVERY generated/revised artifact before it reaches review and again
        before submission (voice-and-truthfulness §6). Em-dashes and banned phrases
        are STRIPPED deterministically (not left to the model); voice alignment is a
        nudge signal applied on every revision pass.
        """
        stripped = normalize_emdashes(text)
        debanned = strip_banned_phrases(stripped, self._extra_banned)
        return FilterReport(
            text=debanned,
            em_dashes_stripped=(stripped != text),
            banned_phrases=tuple(find_banned_phrases(stripped, self._extra_banned)),
            voice_alignment=voice_alignment(self._voice, debanned),
        )

    # === truthfulness guardrail (FR-RESUME-2, NFR-TRUTH-1) ================
    def true_attribute_text(self, campaign_id: CampaignId, base_source: str = "") -> str:
        """Flatten the candidate's TRUE attribute set + work history to one string.

        The fabrication check (FR-RESUME-2) compares generated claims against this
        ground truth: identity, work history, education, skills as stored in the
        attribute cloud, plus the base source. Nothing here is invented.
        """
        parts: list[str] = [base_source]
        try:
            attrs = self._storage.attributes.list_for_campaign(campaign_id)
        except Exception:
            attrs = []
        for a in attrs:
            val = getattr(a, "value", None)
            if val:
                parts.append(str(val))
        return "\n".join(p for p in parts if p)

    def reframe_truthfully(self, true_source: str, jd_terms: list[str]) -> str:
        """Reframe/re-emphasize TRUE source toward the JD without fabricating.

        Only terms already supported by ``true_source`` may be surfaced/re-termed;
        a JD term with no basis in the source is NEVER injected. This is the code
        embodiment of the interview-backtrack test: nothing is added that the
        candidate could not defend.

        The reframing is real (not a verbatim no-op): JD terms that ARE supported by
        the true source are re-emphasized in a leading "Relevant to this role:" line
        so the material is re-oriented toward the JD, while unsupported JD terms are
        dropped entirely (never injected). The em-dash post-filter always runs on the
        reframed output.
        """
        source = normalize_emdashes(true_source)
        if not jd_terms:
            return source
        supported_tokens = {t.lower() for t in candidate_claim_tokens(source)}
        # Surface ONLY JD terms the candidate can actually defend (whole-token or
        # whole-phrase support in the true source) — never inject an unsupported term.
        emphasized: list[str] = []
        for term in jd_terms:
            term_norm = term.strip()
            if not term_norm:
                continue
            term_tokens = {t.lower() for t in candidate_claim_tokens(term_norm)}
            if term_tokens and term_tokens <= supported_tokens:
                emphasized.append(term_norm)
        if not emphasized:
            return source
        # Re-emphasis line uses ONLY the supported JD terms themselves (each already
        # present in the true source), so it surfaces/re-orders truthfully without
        # introducing any new claim token the candidate could not defend (#17).
        lead = ", ".join(emphasized) + "."
        return normalize_emdashes(lead + "\n" + source)

    def detect_fabrication(
        self, true_source: str, generated: str, *, prose: bool = False
    ) -> list[str]:
        """Return generated claims not supported by the candidate's TRUE history.

        Pure detection (no raise) so the engine can flag/route. ``prose=False``
        (default) runs the strict per-token check used for résumé bullets / factual
        answers, where every skill/qualification token must trace to the source. For
        FREE PROSE (cover letters, essays) pass ``prose=True``: an open-ended
        narrative vocabulary will never all appear in the terse source, so only
        *entity-shaped* fabrications (named skills / orgs / acronyms / numbers) are
        flagged while ordinary prose passes (FR-RESUME-2, FR-RESUME-10).
        """
        if prose:
            return unsupported_prose_claims(true_source, generated)
        return unsupported_claims(true_source, generated)

    def assert_no_fabrication(
        self, true_source: str, generated: str, *, prose: bool = False
    ) -> None:
        """Raise ``TruthfulnessViolation`` if ``generated`` adds an unsupported claim.

        A generated bullet that names a skill/term absent from the candidate's true
        history is a fabrication (FR-RESUME-2, NFR-TRUTH-1). Wired into every
        generation + revision pass. ``prose=True`` selects the cover-letter/essay
        check (entity-shaped claims only); see :meth:`detect_fabrication`.
        """
        flagged = self.detect_fabrication(true_source, generated, prose=prose)
        if flagged:
            raise TruthfulnessViolation(
                f"Generated material claims {flagged!r} which is absent from the "
                "candidate's real history (FR-RESUME-2): adaptation reframes, it "
                "never fabricates a skill, title, date, or qualification."
            )

    # === fit scoring / selection (FR-RESUME-6/7) ==========================
    def score_fit(
        self, variant: ResumeVariant, posting_id: JobPostingId, jd_terms: list[str], source: str
    ) -> ResumeFitScoring:
        """Coverage check (not a fabrication target): fraction of JD terms present."""
        source_low = source.lower()
        if not jd_terms:
            coverage = 1.0
            missing: list[str] = []
        else:
            present = [t for t in jd_terms if t.lower() in source_low]
            missing = [t for t in jd_terms if t.lower() not in source_low]
            coverage = len(present) / len(jd_terms)
        return ResumeFitScoring(
            variant_id=variant.id,
            posting_id=posting_id,
            coverage=coverage,
            missing_terms=tuple(missing),
        )

    def lineage(self, variant: ResumeVariant) -> list[ResumeVariant]:
        """Walk parent_id back to the root (FR-RESUME-6), nearest-first."""
        chain: list[ResumeVariant] = []
        cur: ResumeVariant | None = variant
        seen: set[str] = set()
        while cur is not None and str(cur.id) not in seen:
            chain.append(cur)
            seen.add(str(cur.id))
            cur = self._storage.resume_variants.get(cur.parent_id) if cur.parent_id else None
        return chain

    def select_or_generate(
        self,
        campaign_id: CampaignId,
        posting_id: JobPostingId,
        jd_terms: list[str],
        base_source: str,
        *,
        threshold: int = FIT_THRESHOLD,
        variant_sources: dict[str, str] | None = None,
        application_id: ApplicationId | None = None,
    ) -> SelectionResult:
        """Reuse an approved variant scoring >= threshold, else fork from the best parent.

        FR-RESUME-7: score existing approved variants against the JD (cheap/local,
        reusing the embedding port + coverage); if the best clears ``threshold``
        reuse it; otherwise intelligently choose the best parent and generate a
        truthful adaptation toward the JD, route to review. Only ``approved``
        variants are reusable parents (FR-RESUME-6). A forked variant starts
        unapproved (must pass review before reuse/submission).

        ``variant_sources`` optionally maps a variant id -> its stored source so the
        coverage score reflects the variant's own text; absent it, the base source
        is used (the fallback the BDD/contract lane relies on).
        """
        variant_sources = variant_sources or {}
        candidates = [
            v for v in self._storage.resume_variants.list_for_campaign(campaign_id) if v.approved
        ]
        # Converting-role bias (FR-LEARN-5): prefer variants whose traits (their
        # targeted-JD signature) align with the signature of roles that actually
        # convert. The bias is a small tiebreak weight so coverage still dominates.
        sig_align = self._converting_alignment_for(campaign_id)
        best: SelectionResult | None = None
        best_rank = -1.0
        for v in candidates:
            src = variant_sources.get(str(v.id), base_source)
            fit = self.score_fit(v, posting_id, jd_terms, src)
            rank = fit.coverage + _CONVERTING_BIAS_WEIGHT * sig_align(v)
            if best is None or rank > best_rank:
                best = SelectionResult(variant=v, fit=fit, generated=False)
                best_rank = rank
        if best is not None and best.fit.coverage * 100 >= threshold:
            return best

        # No good reuse -> intelligently fork from the best parent (best coverage).
        parent = best.variant if best else None
        parent_source = variant_sources.get(str(parent.id), base_source) if parent else base_source
        # Generate the forked body through the same LLM-capable path the cover-letter /
        # essay generators use (deterministic truthful fallback when no LLM). #17: the
        # generated body — including any LLM-injected claim — is run through the
        # fabrication gate against the candidate's TRUE source (``base_source``, the
        # flattened real attribute set + history), NOT against the parent variant's own
        # text (which would be a vacuous source-to-self comparison).
        generated = self._generate_text(parent_source, jd_terms, kind="resume_variant")
        report = self.apply_post_filter(generated)
        self.assert_no_fabrication(base_source, report.text)
        new_variant = ResumeVariant(
            id=ResumeVariantId(new_id()),
            campaign_id=campaign_id,
            storage_path=f"variants/{new_id()}.tex",
            parent_id=parent.id if parent else None,
            targeted_jd_signature=",".join(sorted(jd_terms)),
            approved=False,
        )
        self._storage.resume_variants.add(new_variant)
        self._storage.commit()
        fit = self.score_fit(new_variant, posting_id, jd_terms, report.text)
        # #1 (FR-RESUME-1/8): a GENERATED variant is unreviewed output — materialize a
        # material_review pending action + the review-ready notification (mirroring
        # generate_cover_letter / generate_screening_answer) so there is something for
        # the user to approve and the pipeline parks at MATERIAL_REVIEW until they do.
        self._announce_variant_review_ready(new_variant, application_id)
        return SelectionResult(variant=new_variant, fit=fit, generated=True)

    def _converting_alignment_for(self, campaign_id: CampaignId):
        """Return ``variant -> alignment[0,1]`` vs the converting-role signature.

        Variants whose traits (their ``targeted_jd_signature``) look like the roles
        that actually convert score higher (FR-LEARN-5). When no learning/signature
        is available the bias is uniformly 0.0 so selection falls back to coverage.
        """
        if self._learning is None:
            return lambda _v: 0.0
        try:
            model = self._learning.load_model(campaign_id)
        except Exception:  # pragma: no cover - defensive
            return lambda _v: 0.0
        if not model.converting_role_signature.get("vector"):
            return lambda _v: 0.0

        def _align(variant: ResumeVariant) -> float:
            sig = (variant.targeted_jd_signature or "").replace(",", " ").strip()
            if not sig:
                return 0.0
            try:
                return self._learning.converting_alignment(model, sig)
            except Exception:  # pragma: no cover - defensive
                return 0.0

        return _align

    def approve_variant(self, variant_id: ResumeVariantId) -> ResumeVariant:
        """Mark a variant USER-APPROVED so it becomes a reusable parent (FR-RESUME-6).

        Approval is the only path to reusability; after approval the library is
        clustered/capped to prevent sprawl.
        """
        import dataclasses

        v = self._storage.resume_variants.get(variant_id)
        if v is None:
            raise NotFound(f"no such variant {variant_id}")
        approved = dataclasses.replace(v, approved=True)
        self._storage.resume_variants.add(approved)
        self._storage.commit()
        # #1: approving the variant is a review action — clear its material_review
        # pending action + expire its ping so the portal item does not linger.
        self._resolve_variant_review_action(approved)
        self.cluster_and_cap(v.campaign_id)
        return approved

    def cluster_and_cap(self, campaign_id: CampaignId, *, cap: int = VARIANT_CAP) -> list[ResumeVariant]:
        """Cluster near-duplicate approved variants + cap the library (FR-RESUME-6).

        Prevents library sprawl: approved variants whose targeted-JD signatures embed
        above ``CLUSTER_SIMILARITY`` are treated as one cluster (a child unapproved
        so only one parent per cluster survives). Returns the retained parents.
        Uses the local embedding port (NFR-LOCAL-1) when available; falls back to
        exact-signature dedup otherwise.
        """
        import dataclasses

        approved = [
            v for v in self._storage.resume_variants.list_for_campaign(campaign_id) if v.approved
        ]
        kept: list[ResumeVariant] = []
        for v in approved:
            sig = v.targeted_jd_signature or ""
            dup = False
            for k in kept:
                if self._signatures_cluster(sig, k.targeted_jd_signature or ""):
                    dup = True
                    break
            if dup:
                # Demote the near-duplicate so only the cluster representative stays.
                self._storage.resume_variants.add(dataclasses.replace(v, approved=False))
            else:
                kept.append(v)
        # Hard cap: keep the most-recent ``cap`` representatives, demote the rest.
        if len(kept) > cap:
            for v in kept[:-cap]:
                self._storage.resume_variants.add(dataclasses.replace(v, approved=False))
            kept = kept[-cap:]
        self._storage.commit()
        return kept

    def _signatures_cluster(self, a: str, b: str) -> bool:
        if a == b:
            return True
        if not a or not b:
            return False
        if self._embedding is not None:
            try:
                return self._embedding.similarity(a, b) >= CLUSTER_SIMILARITY
            except Exception:
                pass
        return False

    # === generation: resume / cover letter / screening answer =============
    def cover_letter_warranted(
        self, *, campaign_default: bool = False, role_requires: bool | None = None
    ) -> bool:
        """Decide whether the role warrants a cover letter (FR-RESUME-10).

        Cover letters are opt-in: the per-campaign default (off by default) sets the
        baseline; a role can force one on or off. Exposed so the orchestrator / UI
        can gate the (token-costing) generation on the same pure rule the service
        uses.
        """
        return should_generate_cover_letter(
            campaign_default=campaign_default, role_requires=role_requires
        )

    def generate_cover_letter(
        self,
        campaign_id: CampaignId,
        application_id: ApplicationId,
        true_source: str,
        jd_terms: list[str],
        *,
        campaign_default: bool = True,
        role_requires: bool | None = None,
    ) -> GeneratedDocument | None:
        """Generate a cover letter ON DEMAND (FR-RESUME-10), filtered + truthful.

        Returns ``None`` when the role does not warrant one (per the on-demand
        decision). Otherwise renders via the same LaTeX-primary/docx-fallback engine
        family (cover.cls), applies the em-dash + banned-phrase + voice filters and
        the truthfulness guardrail, stores it unapproved, and routes it to review
        (review-ready notification + pending action, FR-NOTIF-4).
        """
        if not self.cover_letter_warranted(
            campaign_default=campaign_default, role_requires=role_requires
        ):
            return None
        body = self._generate_text(true_source, jd_terms, kind="cover_letter")
        report = self.apply_post_filter(body)
        # A cover letter is free prose (FR-RESUME-10): use the entity-shaped check so
        # narrative wording passes while invented skills/orgs/credentials are caught.
        self.assert_no_fabrication(true_source, report.text, prose=True)
        doc = self._store_document(
            campaign_id, application_id, DocumentType.COVER_LETTER, report.text
        )
        self._announce_review_ready(doc, "Cover letter ready for review")
        return doc

    def generate_screening_answer(
        self,
        campaign_id: CampaignId,
        application_id: ApplicationId,
        question: str,
        true_source: str,
        *,
        essay: bool | None = None,
        explicit_answer: str | None = None,
    ) -> GeneratedDocument:
        """Generate a screening answer (FR-ANSWER-1): factual vs essay vs sensitive.

        When ``essay`` is None the question is CLASSIFIED (factual / essay /
        sensitive). Factual answers come deterministically from the true source / the
        attribute cloud (no fabrication); sensitive (EEO) ones follow the
        sensitive-field policy (``explicit_answer`` only, else decline — NEVER the
        flattened true source, which would leak the full attribute cloud / resume,
        FR-ATTR-6 / NFR-PRIV-1). Essay/long-form answers are LLM-generated from true
        history, voice + em-dash filtered, and routed through review. All go through
        the post-filter + truthfulness check and the review gate.
        """
        kind = (
            (ScreeningKind.ESSAY if essay else ScreeningKind.FACTUAL)
            if essay is not None
            else classify_screening_question(question)
        )
        if kind is ScreeningKind.ESSAY:
            answer = self._generate_text(true_source, [question], kind="essay_answer")
        elif kind is ScreeningKind.SENSITIVE:
            # EEO/demographic: no fabrication, no AI-guess, no PII leak. The answer
            # comes ONLY from an explicit stored EEO answer; absent that, decline.
            # NEVER fall back to true_source (FR-ATTR-6, NFR-PRIV-1).
            decision = decide_sensitive_fill(question, explicit_answer)
            answer = decision.value or DECLINE_TO_SELF_IDENTIFY
        else:
            # Factual: answer SCOPED to the question (FR-ANSWER-1, NFR-PRIV-1). In the
            # live loop ``true_source`` is the WHOLE flattened attribute cloud + history,
            # so echoing it verbatim would dump the resume/PII into the form field (#5).
            # Extract only the attribute/value relevant to the question; never the whole
            # cloud. Return a safe minimal answer when nothing matches.
            answer = self._scope_factual_answer(campaign_id, question, true_source)
        report = self.apply_post_filter(answer)
        # Sensitive answers are policy-driven (explicit EEO answer or the canned
        # decline), not generated from true_source, so the fabrication guard (which
        # compares against true_source) does not apply to them (FR-ATTR-6).
        if kind is not ScreeningKind.SENSITIVE:
            # Essay answers are free prose (entity-shaped check); factual answers are
            # terse and stay on the strict per-token check.
            self.assert_no_fabrication(
                true_source, report.text, prose=(kind is ScreeningKind.ESSAY)
            )
        doc = self._store_document(
            campaign_id, application_id, DocumentType.SCREENING_ANSWER, report.text
        )
        self._announce_review_ready(doc, "Screening answer ready for review")
        return doc

    def generate_for_deferred_question(
        self,
        campaign_id: CampaignId,
        application_id: ApplicationId,
        deferred: dict,
        true_source: str,
    ) -> GeneratedDocument:
        """Clean handoff entry point for Phase 2's deferred essay screening questions.

        Phase 2 pre-fill records essay screening questions it must NOT auto-answer
        (``deferred_essay_questions`` with ``label``/``selector``/``url``) and defers
        them here (FR-ANSWER-1, FR-PREFILL-3). The question is classified and routed
        through the same generate + filter + review path.
        """
        question = deferred.get("label") or deferred.get("question") or ""
        explicit_answer = deferred.get("explicit_answer")
        return self.generate_screening_answer(
            campaign_id,
            application_id,
            question,
            true_source,
            essay=None,
            explicit_answer=explicit_answer,
        )

    # === interactive revision loop (FR-RESUME-8) ==========================
    def open_revision(self, document_id: GeneratedDocumentId) -> RevisionSession:
        """Open (or resume) the DURABLE revision session for a document.

        Sessions persist to ``revision_sessions`` so the interactive loop is
        resumable across restarts (FR-RESUME-8): a reopened review picks up exactly
        where it left off.
        """
        existing = self._storage.revisions.get_for_material(document_id)
        if existing is not None:
            return existing
        session = RevisionSession(
            id=RevisionSessionId(new_id()),
            material_id=document_id,
            status=RevisionStatus.OPEN,
        )
        self._storage.revisions.add(session)
        self._storage.commit()
        return session

    def _save_session(self, session: RevisionSession) -> RevisionSession:
        self._storage.revisions.add(session)
        self._storage.commit()
        return session

    def apply_turn(
        self,
        document_id: GeneratedDocumentId,
        kind: str,
        instruction: str,
        *,
        true_source: str | None = None,
    ) -> RevisionSession:
        """Apply one add/subtract/free-text turn within the refinement budget.

        After ``REFINEMENT_BUDGET`` turns the loop stays open but further turns are
        no-ops that re-route to review (the budget caps autonomous churn; the human
        still drives approve/decline). Every revision pass re-applies the em-dash +
        banned-phrase + voice post-filter (FR-RESUME-5) and, when ``true_source`` is
        supplied, the fabrication guardrail (FR-RESUME-2) so a revision can never
        introduce an unsupported claim.
        """
        if kind not in ("add", "subtract", "free_text"):
            raise InvalidInput(f"unknown revision turn kind: {kind!r}")
        session = self.open_revision(document_id)
        if session.status is not RevisionStatus.OPEN:
            return session
        doc = self._storage.documents.get(document_id)
        content = doc.content if doc and doc.content else ""

        if len(session.turns) >= REFINEMENT_BUDGET:
            ai_response = "Refinement budget reached; please approve or decline."
            new_content = content
        else:
            new_content, ai_response = self._revise(content, kind, instruction)
            # Every revision pass re-applies the post-filter (FR-RESUME-5).
            new_content = self.apply_post_filter(new_content).text
            # Fabrication guardrail on revision too (FR-RESUME-2) when truth is known.
            # Cover letters / screening answers are free prose, so use the prose check
            # (entity-shaped claims) rather than the strict per-token résumé check.
            if true_source is not None:
                prose = bool(doc) and doc.type in (
                    DocumentType.COVER_LETTER,
                    DocumentType.SCREENING_ANSWER,
                )
                self.assert_no_fabrication(true_source, new_content, prose=prose)
            if doc is not None:
                self._persist_content(doc, new_content)
            # FR-LEARN-3 / FR-RESUME-8: fold this revision turn into learning so the
            # user's add/subtract/free-text edits bias future material generation. Best
            # effort under the per-campaign lock; learning must never break the turn.
            self._fold_revision_feedback(doc, kind, instruction)

        turn = RevisionTurn(kind=kind, instruction=instruction, ai_response=ai_response)
        session = RevisionSession(
            id=session.id,
            material_id=session.material_id,
            status=session.status,
            turns=(*session.turns, turn),
            redline_state={"content": new_content},
        )
        return self._save_session(session)

    def _fold_revision_feedback(self, doc, kind: str, instruction: str) -> None:
        """Fold one redline turn into the learning model (FR-LEARN-3, best-effort)."""
        if self._advanced_learning is None or doc is None:
            return
        campaign_id = getattr(doc, "campaign_id", None)
        if campaign_id is None or not (instruction or "").strip():
            return
        if kind in ("add", "subtract"):
            edits = [{"op": kind, "text": instruction}]
            free_text = ""
        else:
            edits = []
            free_text = instruction
        try:
            self._advanced_learning.fold_revision_feedback_atomic(
                campaign_id, edits=edits, free_text=free_text
            )
        except Exception:  # pragma: no cover - learning must never break the turn
            pass

    def approve(self, document_id: GeneratedDocumentId) -> GeneratedDocument:
        """Approve the material through the review gate (FR-RESUME-8)."""
        doc = self._storage.documents.get(document_id)
        if doc is None:
            raise NotFound(f"no such document {document_id}")
        # Final post-filter before approval (defence in depth).
        content = self.apply_post_filter(doc.content or "").text
        approved = GeneratedDocument(
            id=doc.id,
            campaign_id=doc.campaign_id,
            application_id=doc.application_id,
            type=doc.type,
            content=content,
            storage_path=doc.storage_path,
            approved=True,
        )
        self._storage.documents.add(approved)
        self._storage.commit()
        session = self._storage.revisions.get_for_material(document_id)
        if session is not None:
            self._save_session(
                RevisionSession(
                    id=session.id,
                    material_id=session.material_id,
                    status=RevisionStatus.APPROVED,
                    turns=session.turns,
                    redline_state=session.redline_state,
                )
            )
        # FR-NOTIF-3/4 (#5): the review action resolves the material_review pending
        # action + expires its escalation ladder so the ping/portal item does not
        # linger after the user acted.
        self._resolve_review_action(doc)
        return approved

    def decline(self, document_id: GeneratedDocumentId) -> GeneratedDocument:
        """Decline the material (stays unapproved; blocks submission)."""
        doc = self._storage.documents.get(document_id)
        if doc is None:
            raise NotFound(f"no such document {document_id}")
        session = self._storage.revisions.get_for_material(document_id)
        if session is not None:
            self._save_session(
                RevisionSession(
                    id=session.id,
                    material_id=session.material_id,
                    status=RevisionStatus.DECLINED,
                    turns=session.turns,
                    redline_state=session.redline_state,
                )
            )
        # A decline is also a review ACTION: clear its pending action + ping (#5).
        self._resolve_review_action(doc)
        return doc

    def _resolve_review_action(self, doc: GeneratedDocument) -> None:
        """Resolve the material_review pending action + expire its ladder (#5).

        Both ``approve`` and ``decline`` are review actions. Without this, the
        ``material_review:{doc.id}`` pending action stayed open forever and the
        escalation ladder kept re-pinging. Best-effort: a notifier/storage hiccup
        must never break the recorded approve/decline.
        """
        dedup_key = f"material_review:{doc.id}"
        if self._pending_actions is not None:
            try:
                self._pending_actions.resolve_by_dedup(doc.campaign_id, dedup_key)
            except Exception:  # pragma: no cover - defensive
                pass
        if self._notifications is not None:
            try:
                self._notifications.acted(dedup_key)
            except Exception:  # pragma: no cover - defensive
                pass

    # === review gate before submission (FR-RESUME-8) =====================
    def ensure_application_submittable(self, application_id: ApplicationId) -> None:
        """Raise ``ReviewRequired`` if any generated material is unapproved.

        #4: the gate now also covers the app's linked GENERATED resume variant (not
        just generated documents), so an unapproved variant can't be submitted unreviewed.
        """
        from applicant.application.services.submission_service import (
            _reviewable_materials_for,
        )

        ensure_submittable(_reviewable_materials_for(self._storage, application_id))

    # === redline rendering passthrough ===================================
    def render_redline(self, variant_id: ResumeVariantId, base_source: str, new_source: str):
        """Render the add/subtract redline via the tailoring adapter (FR-RESUME-8)."""
        if self._resume_tailoring is None:
            raise RuntimeError("no resume-tailoring adapter configured")
        return self._resume_tailoring.render_redline(variant_id, base_source, new_source)

    # --- review-ready notification linkage (FR-NOTIF-4) -------------------
    def _announce_review_ready(self, doc: GeneratedDocument, title: str) -> None:
        """Emit a review-ready notification + pending action linked to the review surface.

        Reuses the Phase 1 escalation ladder (NotificationService) and the
        pending-actions home base (FR-NOTIF-4, FR-UI-3): the user is pinged with a
        deep link to the redline review surface, and the same item is materialized in
        the portal so review survives restarts. Both are best-effort: generation never
        blocks if a channel is unavailable.
        """
        deep_link = f"{self._review_base_url}?document_id={doc.id}"
        if self._pending_actions is not None:
            try:
                self._pending_actions.materialize(
                    doc.campaign_id,
                    "material_review",
                    title,
                    application_id=doc.application_id or None,
                    payload={
                        "document_id": str(doc.id),
                        "document_type": doc.type.value,
                        "review_url": deep_link,
                    },
                    dedup_key=f"material_review:{doc.id}",
                )
            except Exception:
                pass
        if self._notifications is not None:
            try:
                self._notifications.notify_decision(
                    f"material_review:{doc.id}",
                    title=title,
                    body="Tap to open the redline review.",
                    deep_link=deep_link,
                )
            except Exception:
                pass

    # --- factual screening-answer scoping (FR-ANSWER-1, NFR-PRIV-1, #5) ----
    def _scope_factual_answer(
        self, campaign_id: CampaignId, question: str, true_source: str
    ) -> str:
        """Scope a factual answer to the QUESTION; never echo the whole true_source (#5).

        Strategy, in order:
          1. If a stored, non-sensitive attribute matches the question, answer with
             ITS value only (the precise fact the question asks for).
          2. Otherwise pick the single most question-relevant line of ``true_source``
             (the line sharing the most question tokens) — not the whole blob.
          3. If ``true_source`` is already a single short line (the BDD/contract lane's
             one-fact source), return it as-is.
          4. If nothing matches, return a safe minimal answer (empty) so the caller can
             defer/leave it for the user rather than leaking unrelated PII.
        """
        source = (true_source or "").strip()
        if not source:
            return ""
        # 1. Stored-attribute match (the precise fact, no surrounding PII).
        attr_value = self._attribute_value_for_question(campaign_id, question)
        if attr_value:
            return attr_value
        lines = [ln.strip() for ln in source.splitlines() if ln.strip()]
        # 3. Single-line source (already question-scoped): return it directly.
        if len(lines) <= 1:
            return source
        # 2. Most question-relevant line by token overlap.
        q_tokens = _word_tokens(question)
        best_line = ""
        best_overlap = 0
        for ln in lines:
            overlap = len(q_tokens & _word_tokens(ln))
            if overlap > best_overlap:
                best_overlap = overlap
                best_line = ln
        if best_overlap > 0:
            return best_line
        # 4. Nothing matched — do NOT dump the whole cloud; defer with a safe minimal.
        return ""

    def _attribute_value_for_question(
        self, campaign_id: CampaignId, question: str
    ) -> str | None:
        """Return a stored NON-sensitive attribute value whose name/alias the question names."""
        from applicant.core.rules.sensitive_fields import is_sensitive_field

        try:
            attrs = self._storage.attributes.list_for_campaign(campaign_id)
        except Exception:  # pragma: no cover - defensive
            return None
        q_tokens = _word_tokens(question)
        if not q_tokens:
            return None
        for a in attrs:
            if is_sensitive_field(a.name):
                continue
            names = {a.name, *getattr(a, "aliases", ())}
            for nm in names:
                nm_tokens = _word_tokens(nm)
                if nm_tokens and nm_tokens <= q_tokens and a.value:
                    return str(a.value)
        return None

    def _announce_variant_review_ready(
        self, variant: ResumeVariant, application_id: ApplicationId | None
    ) -> None:
        """Materialize a material_review pending action + ping for a GENERATED variant (#1).

        Mirrors ``_announce_review_ready`` (which serves GeneratedDocuments) so a
        generated resume variant is reviewable/approvable: the portal item + the ping
        deep-link to the variant review surface. Best-effort — generation never blocks
        if a channel is unavailable.
        """
        title = "Resume variant ready for review"
        deep_link = f"{self._review_base_url}?variant_id={variant.id}"
        dedup_key = f"material_review:{variant.id}"
        if self._pending_actions is not None:
            try:
                self._pending_actions.materialize(
                    variant.campaign_id,
                    "material_review",
                    title,
                    application_id=application_id,
                    payload={
                        "variant_id": str(variant.id),
                        "document_type": "resume_variant",
                        "review_url": deep_link,
                    },
                    dedup_key=dedup_key,
                )
            except Exception:  # pragma: no cover - defensive
                pass
        if self._notifications is not None:
            try:
                self._notifications.notify_decision(
                    dedup_key,
                    title=title,
                    body="Tap to open the redline review.",
                    deep_link=deep_link,
                )
            except Exception:  # pragma: no cover - defensive
                pass

    def _resolve_variant_review_action(self, variant: ResumeVariant) -> None:
        """Resolve a variant's material_review pending action + expire its ping (#1/#5)."""
        dedup_key = f"material_review:{variant.id}"
        if self._pending_actions is not None:
            try:
                self._pending_actions.resolve_by_dedup(variant.campaign_id, dedup_key)
            except Exception:  # pragma: no cover - defensive
                pass
        if self._notifications is not None:
            try:
                self._notifications.acted(dedup_key)
            except Exception:  # pragma: no cover - defensive
                pass

    # --- internals --------------------------------------------------------
    def _generate_text(self, true_source: str, terms: list[str], *, kind: str) -> str:
        """1 LLM pass with deterministic truthful fallback when no LLM is wired."""
        if self._llm is not None and getattr(self._llm, "is_configured", lambda: False)():
            try:
                from applicant.ports.driven.llm import ChatMessage

                # Voice-matching + the truthful-framing dial constrain generation on
                # every pass (FR-RESUME-5/9). The dial only biases framing.
                system = _SYSTEM_PROMPT + "\n" + self._voice.as_directive()
                system += "\n" + aggressiveness_directive(self._aggressiveness)
                if self._extra_banned:
                    system += "\nAvoid these phrases: " + "; ".join(self._extra_banned)
                result = self._llm.complete(
                    [
                        ChatMessage(role="system", content=system),
                        ChatMessage(
                            role="user",
                            content=f"[{kind}] Source:\n{true_source}\nEmphasize: {', '.join(terms)}",
                        ),
                    ],
                    # Heavy writing escalates straight to L2 (FR-LLM-3/4); it still
                    # climbs further on low confidence / context overflow.
                    start_tier=_HEAVY_WRITING_START_TIER,
                )
                return _strip_llm_preamble(result.text)
            except Exception:
                pass  # fall back to deterministic reframing; never block
        return self.reframe_truthfully(true_source, terms)

    def _revise(self, content: str, kind: str, instruction: str) -> tuple[str, str]:
        """Apply one revision turn to ``content`` per ``instruction``.

        Routes through the LLM when one is configured — escalated to L2 because
        editing application material (résumé / cover letter / answer) is heavy,
        quality-sensitive writing (FR-LLM-3/4, FR-RESUME-8). Falls back to a
        deterministic edit so the loop still works with no model wired. Returns
        ``(revised_content, short_ack)``; the caller re-applies the post-filter and
        the fabrication guard.
        """
        revised = self._llm_revise(content, kind, instruction)
        if revised is not None:
            ack = {
                "add": "Added what you asked for.",
                "subtract": "Removed that for you.",
            }.get(kind, "Applied your change.")
            return revised, ack
        # Deterministic fallback (no LLM): keep the loop usable.
        if kind == "add":
            return (content + "\n" + instruction, f"Added: {instruction}")
        if kind == "subtract":
            return (content.replace(instruction, "").strip(), f"Removed: {instruction}")
        return (content, f"Applied free-text guidance: {instruction}")

    def _llm_revise(self, content: str, kind: str, instruction: str) -> str | None:
        """LLM-backed in-place revision; returns the revised text or None.

        None (no model, empty output, or any error) lets ``_revise`` fall back to
        the deterministic edit — a revision turn must never crash the loop.
        """
        if self._llm is None or not getattr(self._llm, "is_configured", lambda: False)():
            return None
        try:
            from applicant.ports.driven.llm import ChatMessage

            how = {
                "add": "Weave the following addition into the document naturally",
                "subtract": "Remove (or rephrase to drop) the following from the document",
                "free_text": "Apply the following edit to the document",
            }.get(kind, "Apply the following edit to the document")
            system = (
                "You revise the candidate's EXISTING application document in place. "
                "Reframe, reorder, and tighten, but stay strictly truthful: never add "
                "a skill, title, date, employer, or qualification not already present. "
                "No em-dashes. Keep the candidate's voice. Return ONLY the revised "
                "document text, with no preamble, commentary, or code fences."
            ) + "\n" + self._voice.as_directive()
            user = f"{how}:\n{instruction}\n\nCURRENT DOCUMENT:\n{content}"
            result = self._llm.complete(
                [
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user),
                ],
                start_tier=_HEAVY_WRITING_START_TIER,
            )
            text = _strip_llm_preamble((result.text or "").strip())
            return text or None
        except Exception:
            return None

    def _store_document(
        self, campaign_id: CampaignId, application_id: ApplicationId, dtype: DocumentType, content: str
    ) -> GeneratedDocument:
        doc = GeneratedDocument(
            id=GeneratedDocumentId(new_id()),
            campaign_id=campaign_id,
            application_id=application_id,
            type=dtype,
            content=content,
            approved=False,
        )
        self._storage.documents.add(doc)
        self._storage.commit()
        return doc

    def _persist_content(self, doc: GeneratedDocument, content: str) -> None:
        updated = GeneratedDocument(
            id=doc.id,
            campaign_id=doc.campaign_id,
            application_id=doc.application_id,
            type=doc.type,
            content=content,
            storage_path=doc.storage_path,
            approved=doc.approved,
        )
        self._storage.documents.add(updated)
        self._storage.commit()


def _word_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric word tokens of length >= 2 (for question scoping, #5)."""
    import re

    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 2}


_SYSTEM_PROMPT = (
    "You adapt the candidate's REAL experience to a job. You reframe, reorder, and "
    "re-term true history. You NEVER fabricate skills, titles, dates, or claims. "
    "No em-dashes. Write in the candidate's own warm, direct, first-person voice."
)

#: A leading meta-preamble an LLM sometimes prepends before the real document
#: ("Here's a cover letter draft in your voice, emphasizing X…:", "Sure, here is the
#: revised version:"). Matched ONLY at the very start and only stripped when ample
#: real content remains, so it can never eat a legitimate opening sentence.
_PREAMBLE_RE = re.compile(
    r"^\s*(?:sure[,!.]?\s+|certainly[,!.]?\s+|of course[,!.]?\s+|okay[,!.]?\s+)?"
    r"(?:here(?:'s| is)|below is|this is|i(?:'ve| have)\s+\w+)\b[^\n]*?"
    r"(?:draft|version|cover letter|letter|answer|r[ée]sum[ée]|revis\w+|"
    r"in your voice|as requested|for you|below)[^\n]*?[:.],?\s+",
    re.IGNORECASE,
)


def _strip_llm_preamble(text: str) -> str:
    """Drop a leading 'Here's a draft…:' meta-sentence the model may prepend.

    Conservative: only when the match is at the very start AND >= 60 chars of real
    content remain after it, so a genuine opening line is never removed.
    """
    if not text:
        return text
    m = _PREAMBLE_RE.match(text)
    if m and (len(text) - m.end()) >= 60:
        return text[m.end():].lstrip(" ,.\n")
    return text


#: Writing application material (résumé variants, cover letters, essay answers) is a
#: heavy, quality-sensitive task, so it starts at the escalation tier (L2) instead of
#: the cheap L1 default — an immediate escalation before even trying L1 (FR-LLM-3/4).
#: The adapter clamps this to the ladder, so a single-tier setup still works.
_HEAVY_WRITING_START_TIER = 2
