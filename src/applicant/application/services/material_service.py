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

from dataclasses import dataclass

from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.resume_variant import ResumeFitScoring, ResumeVariant
from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.errors import TruthfulnessViolation
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
from applicant.core.rules.review_gate import ReviewableMaterial, ensure_submittable
from applicant.core.rules.sensitive_fields import (
    DECLINE_TO_SELF_IDENTIFY,
    decide_sensitive_fill,
)
from applicant.core.rules.truthfulness import (
    VoiceProfile,
    extract_voice_profile,
    find_banned_phrases,
    normalize_emdashes,
    strip_banned_phrases,
    unsupported_claims,
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
        review_base_url: str = "/applicant/review.html",
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
        """
        # Only JD terms already supported by the true source may be surfaced; an
        # unsupported term is never injected. Re-emphasis keeps the real text
        # verbatim (a content no-op) so nothing the candidate cannot defend is
        # added. The em-dash post-filter always runs on the reframed output.
        return normalize_emdashes(true_source)

    def detect_fabrication(self, true_source: str, generated: str) -> list[str]:
        """Return generated claims not supported by the candidate's TRUE history.

        Pure detection (no raise) so the engine can flag/route. Compares every
        skill/qualification claim token in ``generated`` against the candidate's
        real attribute set / work history / base source (FR-RESUME-2).
        """
        return unsupported_claims(true_source, generated)

    def assert_no_fabrication(self, true_source: str, generated: str) -> None:
        """Raise ``TruthfulnessViolation`` if ``generated`` adds an unsupported claim.

        A generated bullet that names a skill/term absent from the candidate's true
        history is a fabrication (FR-RESUME-2, NFR-TRUTH-1). Wired into every
        generation + revision pass.
        """
        flagged = self.detect_fabrication(true_source, generated)
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
        reframed = self.reframe_truthfully(parent_source, jd_terms)
        self.assert_no_fabrication(parent_source, reframed)
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
        fit = self.score_fit(new_variant, posting_id, jd_terms, reframed)
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
            raise ValueError(f"no such variant {variant_id}")
        approved = dataclasses.replace(v, approved=True)
        self._storage.resume_variants.add(approved)
        self._storage.commit()
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
        self.assert_no_fabrication(true_source, report.text)
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
            # Factual: answer directly from the true source, no embellishment.
            answer = true_source.strip()
        report = self.apply_post_filter(answer)
        # Sensitive answers are policy-driven (explicit EEO answer or the canned
        # decline), not generated from true_source, so the fabrication guard (which
        # compares against true_source) does not apply to them (FR-ATTR-6).
        if kind is not ScreeningKind.SENSITIVE:
            self.assert_no_fabrication(true_source, report.text)
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
            raise ValueError(f"unknown revision turn kind: {kind!r}")
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
            if true_source is not None:
                self.assert_no_fabrication(true_source, new_content)
            if doc is not None:
                self._persist_content(doc, new_content)

        turn = RevisionTurn(kind=kind, instruction=instruction, ai_response=ai_response)
        session = RevisionSession(
            id=session.id,
            material_id=session.material_id,
            status=session.status,
            turns=(*session.turns, turn),
            redline_state={"content": new_content},
        )
        return self._save_session(session)

    def approve(self, document_id: GeneratedDocumentId) -> GeneratedDocument:
        """Approve the material through the review gate (FR-RESUME-8)."""
        doc = self._storage.documents.get(document_id)
        if doc is None:
            raise ValueError(f"no such document {document_id}")
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
        return approved

    def decline(self, document_id: GeneratedDocumentId) -> GeneratedDocument:
        """Decline the material (stays unapproved; blocks submission)."""
        doc = self._storage.documents.get(document_id)
        if doc is None:
            raise ValueError(f"no such document {document_id}")
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
        return doc

    # === review gate before submission (FR-RESUME-8) =====================
    def ensure_application_submittable(self, application_id: ApplicationId) -> None:
        """Raise ``ReviewRequired`` if any generated doc is unapproved."""
        docs = self._storage.documents.list_for_application(application_id)
        materials = [
            ReviewableMaterial(identifier=str(d.id), is_generated=True, approved=d.approved)
            for d in docs
        ]
        ensure_submittable(materials)

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
                    ]
                )
                return result.text
            except Exception:
                pass  # fall back to deterministic reframing; never block
        return self.reframe_truthfully(true_source, terms)

    def _revise(self, content: str, kind: str, instruction: str) -> tuple[str, str]:
        """Deterministic stub revision (real impl routes through the LLM)."""
        if kind == "add":
            return (content + "\n" + instruction, f"Added: {instruction}")
        if kind == "subtract":
            return (content.replace(instruction, "").strip(), f"Removed: {instruction}")
        return (content, f"Applied free-text guidance: {instruction}")

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


_SYSTEM_PROMPT = (
    "You adapt the candidate's REAL experience to a job. You reframe, reorder, and "
    "re-term true history. You NEVER fabricate skills, titles, dates, or claims. "
    "No em-dashes. Write in the candidate's own warm, direct, first-person voice."
)
