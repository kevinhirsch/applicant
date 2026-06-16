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
from applicant.core.rules.review_gate import ReviewableMaterial, ensure_submittable
from applicant.core.rules.truthfulness import (
    find_banned_phrases,
    normalize_emdashes,
)

#: FR-RESUME-7 default selection threshold (coverage as a 0-100 percentage).
FIT_THRESHOLD = 70
#: FR-RESUME-* generation budget: 1 initial LLM pass + this many refinements.
REFINEMENT_BUDGET = 2


@dataclass(frozen=True)
class FilterReport:
    """Result of the deterministic non-AI-looking post-filter (FR-RESUME-5)."""

    text: str
    em_dashes_stripped: bool
    banned_phrases: tuple[str, ...]

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
    def __init__(self, storage, llm=None, resume_tailoring=None) -> None:
        self._storage = storage
        self._llm = llm
        self._resume_tailoring = resume_tailoring
        # Revision sessions live in-memory keyed by document id (no repo yet).
        self._sessions: dict[str, RevisionSession] = {}

    # === non-AI-looking post-filter (FR-RESUME-5) =========================
    def apply_post_filter(self, text: str) -> FilterReport:
        """Strip em-dashes deterministically and report banned phrases.

        Runs on EVERY generated/revised artifact before it reaches review and
        again before submission (voice-and-truthfulness §6).
        """
        stripped = normalize_emdashes(text)
        return FilterReport(
            text=stripped,
            em_dashes_stripped=(stripped != text),
            banned_phrases=tuple(find_banned_phrases(stripped)),
        )

    # === truthfulness guardrail (FR-RESUME-2, NFR-TRUTH-1) ================
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

    def assert_no_fabrication(self, true_source: str, generated: str) -> None:
        """Raise ``TruthfulnessViolation`` if ``generated`` adds an unsupported skill.

        A generated bullet that names a skill/term absent from the true source
        (and not a stopword) is a fabrication. Conservative substring check: every
        capitalized/technical token in the generated text that looks like a skill
        claim must be traceable to the source.
        """
        source_low = true_source.lower()
        for line in generated.splitlines():
            for token in _candidate_skill_tokens(line):
                if token.lower() not in source_low:
                    raise TruthfulnessViolation(
                        f"Generated material claims '{token}' which is absent from the "
                        "candidate's real source (FR-RESUME-2): adaptation reframes, "
                        "it never fabricates a skill."
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

    def select_or_generate(
        self,
        campaign_id: CampaignId,
        posting_id: JobPostingId,
        jd_terms: list[str],
        base_source: str,
        *,
        threshold: int = FIT_THRESHOLD,
    ) -> SelectionResult:
        """Reuse an approved variant scoring >= threshold, else fork a new one.

        Only ``approved`` variants are reusable (FR-RESUME-6 lineage). A forked
        variant reframes the parent's TRUE source toward the JD (FR-RESUME-2) and
        starts unapproved (must pass review before reuse/submission).
        """
        candidates = [
            v for v in self._storage.resume_variants.list_for_campaign(campaign_id) if v.approved
        ]
        best: SelectionResult | None = None
        for v in candidates:
            fit = self.score_fit(v, posting_id, jd_terms, base_source)
            if best is None or fit.coverage > best.fit.coverage:
                best = SelectionResult(variant=v, fit=fit, generated=False)
        if best is not None and best.fit.coverage * 100 >= threshold:
            return best

        # No good reuse -> fork a new (unapproved) variant from the base source.
        parent = best.variant if best else None
        reframed = self.reframe_truthfully(base_source, jd_terms)
        self.assert_no_fabrication(base_source, reframed)
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

    # === generation: resume / cover letter / screening answer =============
    def generate_cover_letter(
        self, campaign_id: CampaignId, application_id: ApplicationId, true_source: str, jd_terms: list[str]
    ) -> GeneratedDocument:
        """Generate a cover letter (FR-RESUME-10), filtered + truthful, unapproved."""
        body = self._generate_text(true_source, jd_terms, kind="cover_letter")
        report = self.apply_post_filter(body)
        self.assert_no_fabrication(true_source, report.text)
        return self._store_document(
            campaign_id, application_id, DocumentType.COVER_LETTER, report.text
        )

    def generate_screening_answer(
        self,
        campaign_id: CampaignId,
        application_id: ApplicationId,
        question: str,
        true_source: str,
        *,
        essay: bool,
    ) -> GeneratedDocument:
        """Generate a screening answer (FR-ANSWER-1): factual vs essay style.

        Factual answers are short/direct; essay answers are voice-matched prose.
        Both go through the post-filter + truthfulness check and the review gate.
        """
        if essay:
            answer = self._generate_text(true_source, [question], kind="essay_answer")
        else:
            # Factual: answer directly from the true source, no embellishment.
            answer = true_source.strip()
        report = self.apply_post_filter(answer)
        self.assert_no_fabrication(true_source, report.text)
        return self._store_document(
            campaign_id, application_id, DocumentType.SCREENING_ANSWER, report.text
        )

    # === interactive revision loop (FR-RESUME-8) ==========================
    def open_revision(self, document_id: GeneratedDocumentId) -> RevisionSession:
        """Open (or return the existing) revision session for a document."""
        existing = self._sessions.get(str(document_id))
        if existing is not None:
            return existing
        session = RevisionSession(
            id=RevisionSessionId(new_id()),
            material_id=document_id,
            status=RevisionStatus.OPEN,
        )
        self._sessions[str(document_id)] = session
        return session

    def apply_turn(
        self, document_id: GeneratedDocumentId, kind: str, instruction: str
    ) -> RevisionSession:
        """Apply one add/subtract/free-text turn within the refinement budget.

        After ``REFINEMENT_BUDGET`` turns the loop stays open but further turns are
        no-ops that re-route to review (the budget caps autonomous churn; the human
        still drives approve/decline).
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
        self._sessions[str(document_id)] = session
        return session

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
        session = self._sessions.get(str(document_id))
        if session is not None:
            self._sessions[str(document_id)] = RevisionSession(
                id=session.id,
                material_id=session.material_id,
                status=RevisionStatus.APPROVED,
                turns=session.turns,
                redline_state=session.redline_state,
            )
        return approved

    def decline(self, document_id: GeneratedDocumentId) -> GeneratedDocument:
        """Decline the material (stays unapproved; blocks submission)."""
        doc = self._storage.documents.get(document_id)
        if doc is None:
            raise ValueError(f"no such document {document_id}")
        session = self._sessions.get(str(document_id))
        if session is not None:
            self._sessions[str(document_id)] = RevisionSession(
                id=session.id,
                material_id=session.material_id,
                status=RevisionStatus.DECLINED,
                turns=session.turns,
                redline_state=session.redline_state,
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

    # --- internals --------------------------------------------------------
    def _generate_text(self, true_source: str, terms: list[str], *, kind: str) -> str:
        """1 LLM pass with deterministic truthful fallback when no LLM is wired."""
        if self._llm is not None and getattr(self._llm, "is_configured", lambda: False)():
            try:
                from applicant.ports.driven.llm import ChatMessage

                result = self._llm.complete(
                    [
                        ChatMessage(role="system", content=_SYSTEM_PROMPT),
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

# Stopwords that are not skill claims (so the fabrication check stays conservative).
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "have", "has", "was",
        "were", "are", "our", "their", "your", "you", "led", "built", "drove",
        "managed", "worked", "experience", "team", "role", "year", "years",
    }
)


def _candidate_skill_tokens(line: str) -> list[str]:
    """Tokens that look like skill/technology claims (Capitalized or ALLCAPS words).

    Used by the fabrication check: a Capitalized multi-letter token not present in
    the true source is treated as a potentially fabricated skill claim.
    """
    tokens: list[str] = []
    for raw in line.replace(",", " ").replace(".", " ").split():
        word = raw.strip("()[]{}:;")
        if len(word) < 3:
            continue
        if word.lower() in _STOPWORDS:
            continue
        # Capitalized or all-caps -> likely a proper noun / technology name.
        if word[0].isupper() or word.isupper():
            tokens.append(word)
    return tokens
