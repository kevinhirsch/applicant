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

import logging
import re
from dataclasses import dataclass, replace

from applicant.core.entities.generated_document import (
    DocumentType,
    GeneratedDocument,
    LearnedProvenance,
)
from applicant.core.entities.resume_variant import ResumeFitScoring, ResumeVariant
from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.entities.screening_answer_library import ScreeningAnswerLibraryEntry
from applicant.core.errors import (
    InvalidInput,
    NotFound,
    ReviewRequired,
    TruthfulnessViolation,
)
from applicant.core.events import MaterialApproved, event_bus
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    ResumeVariantId,
    RevisionSessionId,
    ScreeningAnswerLibraryEntryId,
    new_id,
)
from applicant.core.rules.materials import (
    AGGRESSIVENESS_DEFAULT,
    ScreeningKind,
    aggressiveness_directive,
    clamp_aggressiveness,
    classify_screening_question,
    normalize_screening_question,
    should_generate_cover_letter,
)
from applicant.core.rules.prompt_injection import neutralize_untrusted_text
from applicant.core.rules.review_gate import ensure_submittable
from applicant.core.rules.sensitive_fields import (
    DECLINE_TO_SELF_IDENTIFY,
    decide_sensitive_fill,
)
from applicant.core.rules.truthfulness import (
    DEFAULT_TRUTH_POLICY,
    TruthPolicy,
    VoiceProfile,
    candidate_claim_tokens,
    coerce_truth_policy,
    extract_voice_profile,
    find_banned_phrases,
    normalize_emdashes,
    policy_blocks,
    strip_banned_phrases,
    trace_line_provenance,
    unsupported_claims,
    unsupported_prose_claims,
    voice_alignment,
)
from applicant.ports.driven.llm import LLMLadderExhausted

log = logging.getLogger(__name__)

#: FR-RESUME-7 default selection threshold (coverage as a 0-100 percentage).
FIT_THRESHOLD = 70
#: FR-RESUME-* generation budget: 1 initial LLM pass + this many refinements.
REFINEMENT_BUDGET = 2
#: Aggressiveness dial persistence key in AppConfigStore (FR-RESUME-9).
_AGGRESSIVENESS_CONFIG_KEY = "resume.aggressiveness"

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
        config_store=None,
        notifications=None,
        pending_actions=None,
        learning=None,
        advanced_learning=None,
        agent_memory=None,
        research_service=None,
        research_enabled: bool = True,
        review_base_url: str = "/review",
        truth_policy: TruthPolicy | str | None = None,
    ) -> None:
        self._storage = storage
        self._config_store = config_store
        self._llm = llm
        # P1-13 truth policy (owner directive). BALANCED (default): the model may
        # freely rewrite/restructure; invented *facts* are SURFACED (returned to the
        # caller for the review UI) rather than hard-blocked — safe because a human
        # approves every send. STRICT keeps the historical hard-fail. A bad value
        # coerces to the safe default.
        self._truth_policy: TruthPolicy = (
            DEFAULT_TRUTH_POLICY if truth_policy is None else coerce_truth_policy(truth_policy)
        )
        # Silent-degradation diagnostics (#246): the generation pipeline has many
        # defensive ``except`` blocks that let it degrade rather than crash. Counting
        # them — and surfacing a diagnostic once they cross a threshold within one
        # service lifetime — turns invisible degradation into an observable signal
        # instead of silently producing empty/approximate output.
        self._silent_failure_count: int = 0
        self._last_diagnostic_at: int = 0
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
        # Optional agent-memory trio (``.memory`` / ``.skills`` / ``.recall``,
        # FR-MIND-1/2/3). When wired, generation appends a BOUNDED, advisory-only
        # "what the assistant has learned" block to the system prompt (read fresh per
        # call — FR-MIND-10). When ``None`` (the default), behavior is byte-identical
        # to before: no block, no extra calls.
        self._agent_memory = agent_memory
        # Pre-application company research (#299): the SAME capped/deduped/cached
        # ResearchService the agent loop escalates to. When wired + enabled, on-demand
        # cover-letter generation folds a short company-research block into the
        # generation context (and the truthfulness ground truth, so referencing a
        # researched fact is not flagged as a fabrication). Best-effort + budget-aware:
        # a cache hit is free, an exhausted budget / unavailable channel is a silent
        # no-op, so behaviour is byte-identical to before when research is off.
        self._research = research_service
        self._research_enabled = bool(research_enabled)
        # Review-ready notification ladder + pending-actions home base (FR-NOTIF-4).
        self._notifications = notifications
        self._pending_actions = pending_actions
        self._review_base_url = review_base_url
        # UI-editable banned-phrase list (FR-RESUME-5); supplements the core seed.
        self._extra_banned: tuple[str, ...] = ()
        # Voice profile extracted from the user's corpus (FR-RESUME-5).
        self._voice: VoiceProfile = VoiceProfile()
        # The campaign whose résumé corpus ``_voice`` was extracted from (lazy, per
        # service instance — instances are rebuilt per tick/request).
        self._voice_campaign: CampaignId | None = None
        # Truthful-framing dial (FR-RESUME-9); present-but-grayed in the UI (FR-UI-2)
        # but wired so a backend-only flip makes it live.
        self._aggressiveness: int = self._load_aggressiveness()
        # Transient: the advisory learned-item provenance from the most recent
        # ``_generate_text`` pass (FR-MIND-5/-11, FR-OBS-2). The storing generator
        # reads it right after generation and attaches it to the material; empty
        # when no agent-memory substrate was drawn on.
        self._last_provenance: tuple[LearnedProvenance, ...] = ()
        # Transient: True when the most recent ``_generate_text`` pass fell back to
        # the DETERMINISTIC reframe because the LLM tier ladder was exhausted (e.g. a
        # misconfigured upper tier returning 401). Surfaced so a canned draft is
        # visible as degraded rather than masquerading as a real generation.
        self._last_degraded: bool = False

    @property
    def last_generation_degraded(self) -> bool:
        """Whether the most recent generation fell back to the deterministic draft.

        Set when the LLM ladder was exhausted (not when no model is wired at all);
        lets the caller / review UI flag the draft as a degraded fallback.
        """
        return self._last_degraded

    #: Sentinel ``LearnedProvenance.kind`` marking a cover-letter/screening-answer
    #: draft as a degraded deterministic fallback (dark-engine audit #40). Reuses
    #: the EXISTING ``provenance`` JSON column (no schema migration) purely as a
    #: durable carrier — it is NOT a learned item, so the review UI must render it
    #: as a plain-language fallback warning and exclude it from the "What I drew
    #: on" transparency list.
    DEGRADED_PROVENANCE_KIND = "degraded"

    #: Same idea, but for résumé variants: they persist via ``fit_scores`` (a free
    #: JSON dict, no migration needed either) rather than ``provenance``.
    DEGRADED_FIT_SCORE_KEY = "degraded"

    _DEGRADED_LABEL = (
        "The writing model was unavailable, so this draft used a basic template "
        "instead of being tailored by AI. Review it closely before approving."
    )

    def _degraded_marker(self) -> LearnedProvenance:
        """Build the provenance sentinel recording a degraded generation pass."""
        return LearnedProvenance(
            kind=self.DEGRADED_PROVENANCE_KIND, label=self._DEGRADED_LABEL, ref=""
        )

    def _with_degraded_marker(
        self, provenance: tuple[LearnedProvenance, ...]
    ) -> tuple[LearnedProvenance, ...]:
        """Append the degraded sentinel to ``provenance`` iff the last pass degraded.

        Called right after ``_generate_text`` (mirrors how ``_last_provenance`` is
        read), so the flag is captured before the NEXT ``_generate_text`` call
        resets it.
        """
        if self._last_degraded:
            return (*provenance, self._degraded_marker())
        return provenance

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
                self._note_silent_degradation("material_service.py")
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
    def _effective_config_store(self):
        """The config store to persist the dial through.

        Prefers the injected ``AppConfigStore``; when none is wired (e.g. a bare
        service over shared storage) it lazily stashes one on the ``storage`` object so
        every service built over the SAME storage shares the value across requests
        (#187 per-job-search persistence) without a config store being threaded in.
        """
        if self._config_store is not None:
            return self._config_store
        store = getattr(self._storage, "_material_config_store", None)
        if store is None:
            from applicant.adapters.storage.app_config_store import (
                InMemoryAppConfigStore,
            )

            store = InMemoryAppConfigStore()
            try:
                self._storage._material_config_store = store
            except Exception:
                return None
        return store

    @staticmethod
    def _campaign_aggressiveness_key(campaign_id: CampaignId) -> str:
        """Per-campaign persistence key for the dial (#187)."""
        return f"{_AGGRESSIVENESS_CONFIG_KEY}.{campaign_id}"

    def set_aggressiveness(
        self, value: int | None, campaign_id: CampaignId | None = None
    ) -> int:
        """Set the truthful-framing dial (FR-RESUME-9), clamped into range.

        Persisted via the AppConfigStore so the value survives across requests. When a
        ``campaign_id`` is supplied the choice is ALSO banked per job search (#187) so a
        fresh service can recall it for that campaign; the global key always tracks the
        latest choice as a fallback. The dial only biases framing (assertive vs
        measured), never the truthfulness guardrail.
        """
        self._aggressiveness = clamp_aggressiveness(value)
        self._persist_aggressiveness(campaign_id)
        return self._aggressiveness

    def load_aggressiveness(self, campaign_id: CampaignId) -> int:
        """Recall the chosen dial value for a job search across requests (#187).

        Reads the per-campaign value first, falling back to the latest global choice,
        then the default — so a fresh service built for the same campaign recovers the
        operator's chosen framing rather than resetting to the default each request.
        """
        store = self._effective_config_store()
        if store is not None:
            for key in (
                self._campaign_aggressiveness_key(campaign_id),
                _AGGRESSIVENESS_CONFIG_KEY,
            ):
                try:
                    rec = store.get(key)
                except Exception:
                    rec = None
                if rec is not None and "value" in rec:
                    return clamp_aggressiveness(rec["value"])
        return AGGRESSIVENESS_DEFAULT

    def _load_aggressiveness(self) -> int:
        """Read the persisted (global) aggressiveness value, or return the default."""
        store = self._effective_config_store()
        if store is not None:
            try:
                rec = store.get(_AGGRESSIVENESS_CONFIG_KEY)
                if rec is not None and "value" in rec:
                    return clamp_aggressiveness(rec["value"])
            except Exception:
                pass
        return AGGRESSIVENESS_DEFAULT

    def _persist_aggressiveness(self, campaign_id: CampaignId | None = None) -> None:
        """Write the current aggressiveness to the config store (global + per-campaign).

        The in-memory ``self._aggressiveness`` already reflects the user's choice for
        this request/instance, so a store failure here is a *persistence* failure, not
        a user-facing one — the call site's return value is unaffected either way
        (audit #46: this used to be a bare ``except Exception: pass`` with zero trace,
        so a failing store silently meant "resets to the default on the next restart"
        with no way for an operator to notice before the user does).
        """
        store = self._effective_config_store()
        if store is None:
            return
        payload = {"value": self._aggressiveness}
        try:
            store.set(_AGGRESSIVENESS_CONFIG_KEY, payload)
            if campaign_id is not None:
                store.set(self._campaign_aggressiveness_key(campaign_id), dict(payload))
        except Exception:
            log.warning(
                "Failed to persist aggressiveness setting (value=%s, campaign_id=%s); "
                "it will not survive a restart",
                self._aggressiveness,
                campaign_id,
                exc_info=True,
            )

    @property
    def aggressiveness(self) -> int:
        return self._aggressiveness

    # === silent-degradation diagnostics (#246) ============================
    #: How many silent degradations may accumulate before a diagnostic is surfaced.
    SILENT_FAILURE_DIAGNOSTIC_THRESHOLD = 3

    @property
    def silent_failure_count(self) -> int:
        """How many times this service has silently degraded (#246)."""
        return self._silent_failure_count

    def _note_silent_degradation(self, where: str) -> None:
        """Record one silent degradation and surface a diagnostic past the threshold.

        Every defensive ``except`` in the generation pipeline routes through here so a
        run of swallowed failures becomes a visible, counted signal rather than vanishing
        into empty output (#246). Crossing the threshold emits a degradation diagnostic
        exactly once per threshold-multiple so a flaky run is loud without spamming.
        """
        self._silent_failure_count += 1
        log.warning("material generation silently degraded at %s", where)
        if (
            self._silent_failure_count >= self.SILENT_FAILURE_DIAGNOSTIC_THRESHOLD
            and self._silent_failure_count != self._last_diagnostic_at
        ):
            self._last_diagnostic_at = self._silent_failure_count
            self.emit_degradation_diagnostic(self._silent_failure_count)

    def emit_degradation_diagnostic(self, count: int) -> None:
        """Surface a diagnostic event when silent degradation crosses the threshold (#246).

        Emits a loud, structured observability event (an ``error``-level log carrying the
        degradation count) so repeated silent degradation becomes visible rather than
        vanishing into empty/approximate output. Never raises — a diagnostic must never
        itself break generation.
        """
        log.error(
            "material generation degradation diagnostic: silently degraded %d times — "
            "output may be incomplete or approximate; check the model connection and "
            "base profile",
            count,
        )

    # === voice matching (FR-RESUME-5) =====================================
    def load_voice_corpus(self, corpus: list[str]) -> VoiceProfile:
        """Extract + cache the voice profile from the user's resume corpus."""
        self._voice = extract_voice_profile(corpus)
        return self._voice

    def _ensure_voice_for(self, campaign_id: CampaignId) -> None:
        """Lazily extract the voice profile from the campaign's OWN résumé corpus so
        every generation + revision is constrained to sound like the candidate, not
        generic AI prose (FR-RESUME-5).

        Without this the corpus was never loaded in the live flow, so ``as_directive``
        fell back to a generic voice. Extracted once per campaign per instance (they
        are rebuilt per tick/request); a missing/thin corpus keeps the neutral
        directive. Best-effort — never blocks generation.
        """
        if self._voice_campaign == campaign_id:
            return
        try:
            corpus = [
                line.strip()
                for line in (self._base_resume_text(campaign_id) or "").splitlines()
                if line.strip()
            ]
        except Exception:  # pragma: no cover - defensive; never block generation
            corpus = []
        if corpus:
            self.load_voice_corpus(corpus)
        self._voice_campaign = campaign_id

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
            self._note_silent_degradation("material_service.py")
            attrs = []
        for a in attrs:
            val = getattr(a, "value", None)
            if val:
                parts.append(str(val))
        # Include the uploaded base-résumé text as ground truth. The attribute cloud
        # only captures structured/parsed fields (and work-history flattening can drop
        # the achievement prose with its metrics), so without this a real achievement
        # the candidate genuinely has ("cut p99 latency 38%") would read as a
        # fabrication in a generated cover letter / answer (FR-RESUME-2).
        resume_text = self._base_resume_text(campaign_id)
        if resume_text:
            parts.append(resume_text)
        return "\n".join(p for p in parts if p)

    def _base_resume_text(self, campaign_id: CampaignId) -> str:
        """The raw text of the uploaded base résumé, if persisted (best-effort)."""
        repo = getattr(self._storage, "onboarding_profiles", None)
        if repo is None:
            return ""
        try:
            profile = repo.get_for_campaign(campaign_id)
            intake = getattr(profile, "intake", None) or {}
            base = intake.get("base_resume", {}) if isinstance(intake, dict) else {}
            return str(base.get("raw_text", "") or "")
        except Exception:  # pragma: no cover - defensive; never break generation
            return ""

    def _with_application_context(self, true_source: str, application_id) -> str:
        """Append the application's target company + role title to the fabrication
        check source. These name the addressee/position the material is FOR; they are
        never claims about the candidate's history, so allowing them keeps a letter
        that names the employer from self-reporting as a fabrication. Best-effort."""
        ctx = self._posting_context(application_id)
        return f"{true_source}\n{ctx}" if ctx else true_source

    def _posting_context(self, application_id) -> str:
        """Target company + role title text for the application (``""`` if unavailable)."""
        try:
            app = self._storage.applications.get(application_id)
        except Exception:
            self._note_silent_degradation("material_service.py")
            app = None
        if app is None:
            return ""
        bits = [getattr(app, "role_name", "") or "", getattr(app, "job_title", "") or ""]
        pid = getattr(app, "posting_id", None)
        if pid is not None:
            try:
                posting = self._storage.postings.get(pid)
            except Exception:
                self._note_silent_degradation("material_service.py")
                posting = None
            if posting is not None:
                bits += [
                    getattr(posting, "company", "") or "",
                    getattr(posting, "title", "") or "",
                    getattr(posting, "location", "") or "",
                ]
        return " ".join(b for b in bits if b)

    def _company_role_for(self, application_id) -> tuple[str, str]:
        """Resolve the application's target ``(company, role)`` for research.

        Reuses the same application/posting lookup ``_posting_context`` does, but
        returns the company + role as distinct fields so they can be forwarded to the
        owner-scoped, URL-safe deep-research channel. Best-effort: ``("", "")`` when
        unavailable so research is simply skipped (no crash).
        """
        try:
            app = self._storage.applications.get(application_id)
        except Exception:  # pragma: no cover - defensive
            app = None
        if app is None:
            return "", ""
        role = (getattr(app, "role_name", "") or getattr(app, "job_title", "") or "").strip()
        company = ""
        pid = getattr(app, "posting_id", None)
        if pid is not None:
            try:
                posting = self._storage.postings.get(pid)
            except Exception:  # pragma: no cover - defensive
                posting = None
            if posting is not None:
                company = (getattr(posting, "company", "") or "").strip()
                if not role:
                    role = (getattr(posting, "title", "") or "").strip()
        return company, role

    def _company_research_context(
        self, campaign_id: CampaignId, application_id
    ) -> str:
        """A short company-research block to fold into cover-letter generation (#299).

        Escalates to the SAME capped/deduped/cached ``ResearchService`` the agent loop
        uses, scoped to the campaign so the per-campaign budget + dedupe cache are
        shared. Returns ``""`` (a silent no-op, byte-identical to research-off) when:
        research is not wired or disabled, the channel is unavailable, the budget is
        spent, there is no company to research, or the run fails. The ResearchService
        itself enforces the cap + dedupe + cache and uses the owner-scoped, URL-safe
        deep-research channel — this method never weakens that.
        """
        if self._research is None or not self._research_enabled:
            return ""
        company, role = self._company_role_for(application_id)
        if not company:
            return ""
        query = (
            f"What should a job applicant know about {company} to tailor their "
            "application?"
        )
        try:
            report = self._research.research(
                campaign_id, query, company=company, role=role or None
            )
        except Exception:  # pragma: no cover - service degrades, never raises
            return ""
        if report is None or not (report.summary or report.key_findings):
            return ""
        lines = [f"[Company research — {company}]"]
        if report.summary:
            lines.append(report.summary.strip())
        for finding in (report.key_findings or [])[:6]:
            lines.append(f"- {finding}")
        return "\n".join(p for p in lines if p).strip()

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
        self,
        true_source: str,
        generated: str,
        *,
        prose: bool = False,
        policy: TruthPolicy | None = None,
    ) -> list[str]:
        """Check ``generated`` for claims absent from the candidate's true history.

        Returns the flagged (unsupported) fact tokens — always, so the caller can
        SURFACE them as suggestions to confirm — and, under the STRICT truth policy,
        raises ``TruthfulnessViolation`` on any flag (the historical hard-fail,
        FR-RESUME-2 / NFR-TRUTH-1). Under BALANCED (the default, P1-13) it never
        raises: the model may freely rewrite, and invented facts are returned for the
        review UI rather than blocked — safe because a human approves every send.
        ``prose=True`` selects the cover-letter/essay check (entity-shaped claims
        only); see :meth:`detect_fabrication`.
        """
        flagged = self.detect_fabrication(true_source, generated, prose=prose)
        effective = policy or self._truth_policy
        if policy_blocks(flagged, effective):
            raise TruthfulnessViolation(
                f"Generated material claims {flagged!r} which is absent from the "
                "candidate's real history: adaptation reframes, it "
                "never fabricates a skill, title, date, or qualification."
            )
        if flagged:
            log.info(
                "truth_policy=%s surfaced %d unsupported fact(s) for review: %r",
                effective.value,
                len(flagged),
                flagged,
            )
        return flagged

    def flagged_facts_for_document(self, document_id: GeneratedDocumentId) -> dict:
        """Facts in an already-persisted document not traceable to the profile.

        P1-13 truth policy (BALANCED): the fabrication guard SURFACES rather than
        blocks flagged facts, so a stored draft may legitimately contain fact-class
        tokens (skills, orgs, credentials, dates, numbers) that are not yet in the
        candidate's attribute cloud / base résumé. This read-only method recomputes
        those flagged tokens so the review UI can surface them for the user to
        confirm ("yes, that's true, add it to my profile") or remove from the draft.

        Pure detection: no raise, no write, no LLM call, no company research
        (side-effect-free). The ground truth is the same flattened true-attribute
        text the persistence guard checks against, plus the application's own
        addressee/role context (so the target company/role is never itself flagged).
        The free-prose (entity-shaped) check is used for cover letters / screening
        answers, matching how they were generated; résumé-class docs use the strict
        per-token check. Returns the campaign id (so the caller can add a confirmed
        fact to that campaign's profile), the document type, and the flagged tokens.
        """
        doc = self._storage.documents.get(document_id)
        if doc is None:
            raise NotFound(f"no such document {document_id}")
        prose = doc.type in (DocumentType.COVER_LETTER, DocumentType.SCREENING_ANSWER)
        source = self.true_attribute_text(doc.campaign_id)
        if doc.application_id:
            source = self._with_application_context(source, doc.application_id)
        flagged = self.detect_fabrication(source, doc.content or "", prose=prose)
        return {
            "document_id": str(doc.id),
            "campaign_id": str(doc.campaign_id),
            "type": doc.type.value,
            "flagged": flagged,
        }

    def _provenance_sources(
        self, campaign_id: CampaignId, application_id
    ) -> list[tuple[str, str]]:
        """The candidate's ground truth as LABELLED components (H4).

        The same material :meth:`true_attribute_text` flattens for the
        fabrication guard, kept apart and named so the review surface can say
        WHICH source supports each generated fact: every profile attribute by
        name, the uploaded base résumé, and (when the document targets an
        application) the posting's own company/role context. Labels are plain
        language — they are shown verbatim at review time.
        """
        components: list[tuple[str, str]] = []
        try:
            attrs = self._storage.attributes.list_for_campaign(campaign_id)
        except Exception:
            self._note_silent_degradation("material_service.py")
            attrs = []
        for a in attrs:
            name = str(getattr(a, "name", "") or "").strip()
            val = getattr(a, "value", None)
            if name and val:
                components.append((f"your profile ({name})", str(val)))
        resume_text = self._base_resume_text(campaign_id)
        if resume_text:
            components.append(("your base résumé", resume_text))
        if application_id is not None:
            ctx = self._posting_context(application_id)
            if ctx:
                components.append(("the job posting you're applying to", ctx))
        return components

    def line_provenance_for_document(self, document_id: GeneratedDocumentId) -> dict:
        """Per-line provenance of a stored draft: what traces where (H4).

        Visible provenance for the review screen: every non-empty line of the
        document with its fact-class tokens, each traced to the named
        ground-truth component(s) that support it (a profile attribute by name,
        the base résumé, the target posting) — or to nothing, in which case it
        is returned as unsourced so the UI flags it rather than hiding it.
        Reuses the exact fabrication-guard tokenizers/matchers
        (:func:`trace_line_provenance`), so this view can never disagree with
        :meth:`flagged_facts_for_document`.

        Pure detection: no raise besides 404, no write, no LLM call. Honesty
        (H-series): a document with no reviewable text returns
        ``checked: False`` with a reason — the absence of a check is said out
        loud, never rendered as a clean check.
        """
        doc = self._storage.documents.get(document_id)
        if doc is None:
            raise NotFound(f"no such document {document_id}")
        base = {
            "document_id": str(doc.id),
            "campaign_id": str(doc.campaign_id),
            "type": doc.type.value,
        }
        content = doc.content or ""
        if not content.strip():
            return {
                **base,
                "checked": False,
                "reason": "This document has no text content to trace.",
                "lines": [],
                "unsourced": [],
            }
        prose = doc.type in (DocumentType.COVER_LETTER, DocumentType.SCREENING_ANSWER)
        sources = self._provenance_sources(doc.campaign_id, doc.application_id)
        traced = trace_line_provenance(sources, content, prose=prose)
        unsourced: list[str] = []
        lines: list[dict] = []
        for lp in traced:
            facts = []
            for f in lp.facts:
                facts.append({"token": f.token, "sources": list(f.sources)})
                if f.unsourced and f.token not in unsourced:
                    unsourced.append(f.token)
            lines.append({"line": lp.line, "facts": facts})
        return {**base, "checked": True, "lines": lines, "unsourced": unsourced}

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

    @staticmethod
    def _fit_scores_entry(fit: ResumeFitScoring) -> dict:
        """Serialize a coverage check into the variant's ``fit_scores`` JSON dict (P1-8).

        The deterministic keyword-coverage metric (JD terms vs the variant's own
        text) is banked on the variant alongside the model-driven viability score
        the digest shows, so the review surface / variant library can render a real
        "covers N% of the posting's language; missing: ..." line instead of "not
        scored". Rides the EXISTING free-form ``fit_scores`` dict (no migration);
        merged over any keys already present (e.g. the degraded-draft flag).
        """
        return {
            "coverage": fit.coverage,
            "missing_terms": list(fit.missing_terms),
            "posting_id": str(fit.posting_id),
        }

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

    # === document-library integration (#293) ==============================
    def promote_to_base_resume(self, variant: ResumeVariant) -> ResumeVariant:
        """Adopt a library variant as the new base the engine tailors from (#293).

        Marks the chosen variant as an approved root (clears its ``parent_id`` so it
        becomes the lineage root) and persists it, so future ``select_or_generate``
        runs fork from this variant rather than the original base. Returns the promoted
        variant. Idempotent: promoting the same variant again is a no-op.
        """
        from dataclasses import replace

        promoted = replace(variant, parent_id=None, approved=True)
        self._storage.resume_variants.add(promoted)
        self._storage.commit()
        return promoted

    def fill_cover_letter_template(
        self, template: str, context: dict[str, str]
    ) -> str:
        """Fill a cover-letter template's ``{{field}}`` merge fields from context (#293).

        A small, deterministic merge-field filler for the template library: every
        ``{{name}}`` placeholder is replaced with ``context["name"]`` (whitespace inside
        the braces tolerated). Unknown placeholders are left blank rather than leaking the
        raw ``{{...}}`` token into the letter, so a partial context never produces broken
        output. Pure string substitution — never an LLM call, never a fabrication path.
        """
        import re

        def _sub(match: re.Match) -> str:
            key = match.group(1).strip()
            return str(context.get(key, ""))

        return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", _sub, template)

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
            # P1-8: bank the deterministic keyword-coverage check on the REUSED
            # variant too (not just freshly generated ones), so the library /
            # review surface shows the coverage this selection was based on.
            reused = replace(
                best.variant,
                fit_scores={**best.variant.fit_scores, **self._fit_scores_entry(best.fit)},
            )
            self._storage.resume_variants.add(reused)
            self._storage.commit()
            return SelectionResult(variant=reused, fit=best.fit, generated=False)

        # No good reuse -> intelligently fork from the best parent (best coverage).
        self._ensure_voice_for(campaign_id)  # constrain to the user's voice (FR-RESUME-5)
        parent = best.variant if best else None
        parent_source = variant_sources.get(str(parent.id), base_source) if parent else base_source
        # Generate the forked body through the same LLM-capable path the cover-letter /
        # essay generators use (deterministic truthful fallback when no LLM). #17: the
        # generated body — including any LLM-injected claim — is run through the
        # fabrication gate against the candidate's TRUE source (``base_source``, the
        # flattened real attribute set + history), NOT against the parent variant's own
        # text (which would be a vacuous source-to-self comparison).
        generated = self._generate_text(
            parent_source, jd_terms, kind="resume_variant", campaign_id=campaign_id
        )
        # Dark-engine audit #40: capture the degradation flag right after the pass
        # that set it (mirrors ``_last_provenance``), before it can be reset by any
        # later ``_generate_text`` call.
        degraded = self._last_degraded
        report = self.apply_post_filter(generated)
        # Fail-closed (NFR-TRUTH-1): the fabrication post-check runs BEFORE the variant
        # is persisted, so a forked variant whose generated body adds an unsupported
        # claim raises TruthfulnessViolation and nothing is stored. If generation
        # raised earlier (LLM/parse error), ``_generate_text`` already fell back to the
        # provably-truthful deterministic reframe — which still passes through this same
        # gate — so no unverified body can ever reach ``resume_variants.add``.
        self.assert_no_fabrication(base_source, report.text)
        new_variant = ResumeVariant(
            id=ResumeVariantId(new_id()),
            campaign_id=campaign_id,
            storage_path=f"variants/{new_id()}.tex",
            parent_id=parent.id if parent else None,
            targeted_jd_signature=",".join(sorted(jd_terms)),
            approved=False,
            # Dark-engine audit #40: flag a fallback-template draft so the review UI
            # can warn the user instead of presenting it as a real AI tailoring pass.
            # Stored in the existing ``fit_scores`` JSON dict (no migration needed).
            fit_scores=({self.DEGRADED_FIT_SCORE_KEY: True} if degraded else {}),
        )
        # P1-8: compute the deterministic keyword coverage of the GENERATED body vs
        # the JD terms and persist it with the variant, so the coverage the review
        # surface shows is stored (not recomputed ad hoc) and survives restarts.
        fit = self.score_fit(new_variant, posting_id, jd_terms, report.text)
        new_variant = replace(
            new_variant,
            fit_scores={**new_variant.fit_scores, **self._fit_scores_entry(fit)},
        )
        self._storage.resume_variants.add(new_variant)
        self._storage.commit()
        # #1 (FR-RESUME-1/8): a GENERATED variant is unreviewed output — materialize a
        # material_review pending action + the review-ready notification (mirroring
        # generate_cover_letter / generate_screening_answer) so there is something for
        # the user to approve and the pipeline parks at MATERIAL_REVIEW until they do.
        self._announce_variant_review_ready(new_variant, application_id)
        return SelectionResult(variant=new_variant, fit=fit, generated=True)

    def _converting_alignment_for(self, campaign_id: CampaignId):
        """Return ``variant -> alignment[0,1]`` vs the converting-role signature.

        Variants whose traits look like the roles that actually convert score higher
        (FR-LEARN-5), as a small tiebreak so JD coverage still dominates. Three
        complementary, read-only views are combined via ``max`` (never summed, so the
        same conversion evidence is not double-counted):

          * the Phase-1 embedding CENTROID over the variant's targeted-JD signature
            (``LearningService.converting_alignment``), and
          * the DISCRETE converting signature the LIVE conversion loop actually writes
            — which records the exact ``variant:{id}`` that converted, so a variant
            tied to a past conversion is preferred directly, plus a lexical match of
            the variant's targeted-JD signature against the converted role's features
            (``AdvancedLearningService.variant_alignment`` / ``text_alignment``), and
          * an advisory recall nudge (``AdvancedLearningService.recall_alignment``).

        When neither learning source has any signature/recall the bias is uniformly
        0.0 so selection falls back to coverage (byte-identical default).
        """
        base_model = None
        if self._learning is not None:
            try:
                base_model = self._learning.load_model(campaign_id)
            except Exception:  # pragma: no cover - defensive
                base_model = None
        adv = self._advanced_learning
        adv_model = None
        if adv is not None:
            try:
                adv_model = adv.load_model(campaign_id)
            except Exception:  # pragma: no cover - defensive
                adv_model = None

        has_vector = bool(
            base_model is not None
            and base_model.converting_role_signature.get("vector")
        )
        has_discrete = bool(
            adv_model is not None
            and any(
                k != "vector" for k in adv_model.converting_role_signature
            )
        )
        if not has_vector and not has_discrete and adv is None:
            return lambda _v: 0.0

        def _align(variant: ResumeVariant) -> float:
            sig = (variant.targeted_jd_signature or "").replace(",", " ").strip()
            # Role-likeness signals (how much this variant LOOKS like the converting
            # role): combined via ``max`` so the same conversion evidence is never
            # double-counted across the centroid / discrete / recall facets.
            likeness: list[float] = []
            if has_vector and sig:
                try:
                    likeness.append(self._learning.converting_alignment(base_model, sig))
                except Exception:  # pragma: no cover - defensive
                    pass
            if adv_model is not None and has_discrete and sig:
                try:
                    likeness.append(adv.text_alignment(adv_model, sig))
                except Exception:  # pragma: no cover - defensive
                    pass
            if adv is not None and sig:
                try:
                    likeness.append(adv.recall_alignment(campaign_id, sig))
                except Exception:  # pragma: no cover - defensive
                    pass
            score = max(likeness) if likeness else 0.0
            # EXACT-variant identity is a DISTINCT question ("which variant did past
            # conversions actually use?") from role-likeness, so it adds a bounded
            # bonus ON TOP — that's how, among two equally-likeness variants, the one
            # tied to a past conversion is strictly preferred. Capped to [0,1].
            if adv_model is not None and has_discrete:
                try:
                    vexact = adv.variant_alignment(adv_model, variant.id)
                except Exception:  # pragma: no cover - defensive
                    vexact = 0.0
                if vexact > 0.0:
                    score = min(1.0, score + 0.5 * vexact + 0.05)
            return score

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
                self._note_silent_degradation("material_service.py")
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

    def _resolve_true_source(self, campaign_id: CampaignId, true_source: str) -> str:
        """The ground-truth text for generation: the caller's, or derived server-side
        when omitted (on-demand generation, FR-RESUME-10 / FR-ANSWER-1).

        On-demand requests from the front-door supply only the application — the
        truthfulness ground truth is built HERE from the base résumé + the flattened
        attribute cloud + work history (the same source the agent loop uses), never
        from a caller-supplied blob. The fabrication guard always checks against this.
        """
        if (true_source or "").strip():
            return true_source
        try:
            return self.true_attribute_text(campaign_id, self._base_resume_text(campaign_id))
        except Exception:  # pragma: no cover - defensive
            return true_source or ""

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
        self._ensure_voice_for(campaign_id)  # constrain to the user's voice (FR-RESUME-5)
        true_source = self._resolve_true_source(campaign_id, true_source)
        # #299: best-effort, budget-aware pre-application company research folded into
        # the generation context so the letter can reference company-specific detail.
        # The block is added to the generation source AND the fabrication-check source
        # (it is researched context the letter is allowed to draw on, not a claim about
        # the candidate), mirroring the agent-loop auto-escalation. A no-op (and so
        # byte-identical) when research is off / unavailable / budget-spent.
        research_ctx = self._company_research_context(campaign_id, application_id)
        gen_source = (
            f"{true_source}\n\n{research_ctx}" if research_ctx else true_source
        )
        body = self._generate_text(
            gen_source, jd_terms, kind="cover_letter", campaign_id=campaign_id
        )
        report = self.apply_post_filter(body)
        # A cover letter is free prose (FR-RESUME-10): use the entity-shaped check so
        # narrative wording passes while invented skills/orgs/credentials are caught.
        # The target company + role title are the addressee/position, not claims about
        # the candidate, so allow them as context (else a letter naming the employer
        # it is addressed to would self-report as a fabrication). The fabrication
        # post-check is enforced fail-closed at the persistence boundary by
        # ``_store_document`` (NFR-TRUTH-1) — nothing is stored unless it passes.
        check_source = self._with_application_context(gen_source, application_id)
        doc = self._store_document(
            campaign_id,
            application_id,
            DocumentType.COVER_LETTER,
            report.text,
            # Dark-engine audit #40: append the degraded-fallback sentinel (no-op
            # tuple concat when the LLM ladder did not exhaust) so the review UI can
            # flag this draft as a basic template rather than a real AI tailoring.
            provenance=self._with_degraded_marker(self._last_provenance),
            verify_source=check_source,
            prose=True,
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
        self._ensure_voice_for(campaign_id)  # constrain to the user's voice (FR-RESUME-5)
        true_source = self._resolve_true_source(campaign_id, true_source)
        kind = (
            (ScreeningKind.ESSAY if essay else ScreeningKind.FACTUAL)
            if essay is not None
            else classify_screening_question(question)
        )
        # Only the essay path consults the learned-context block; the factual /
        # sensitive paths draw on nothing learned, so their provenance is empty.
        provenance: tuple[LearnedProvenance, ...] = ()
        if kind is ScreeningKind.ESSAY:
            answer = self._generate_text(
                true_source, [question], kind="essay_answer", campaign_id=campaign_id
            )
            # Dark-engine audit #40: same degraded-fallback sentinel as the cover
            # letter / résumé paths — the essay path is the only screening-answer
            # kind that actually calls the LLM, so it is the only one that can
            # degrade.
            provenance = self._with_degraded_marker(self._last_provenance)
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
        # compares against true_source) does not apply to them (FR-ATTR-6); they are
        # persisted as policy-exempt. Essay/factual answers ARE derived from the true
        # source, so the fabrication post-check is enforced fail-closed at the
        # persistence boundary by ``_store_document`` (NFR-TRUTH-1): essay answers are
        # free prose (entity-shaped check); factual answers stay on the strict
        # per-token check. The target company/role is legitimate context (the position
        # being answered about), not a claim.
        if kind is ScreeningKind.SENSITIVE:
            doc = self._store_document(
                campaign_id,
                application_id,
                DocumentType.SCREENING_ANSWER,
                report.text,
                provenance=provenance,
                verify_source=None,
                policy_exempt=True,
            )
        else:
            check_source = self._with_application_context(true_source, application_id)
            doc = self._store_document(
                campaign_id,
                application_id,
                DocumentType.SCREENING_ANSWER,
                report.text,
                provenance=provenance,
                verify_source=check_source,
                prose=(kind is ScreeningKind.ESSAY),
            )
            # Product-gaps backlog #20: build the reusable screening-answer library
            # over time. NEVER for SENSITIVE (EEO/demographic) answers -- those are
            # policy-driven, never AI-guessed, and must never leak into a cross-
            # application store (FR-ATTR-6, NFR-PRIV-1); the ``else`` branch above
            # already excludes them.
            self._save_to_screening_library(
                campaign_id, question, report.text, essay=(kind is ScreeningKind.ESSAY)
            )
        self._announce_review_ready(doc, "Screening answer ready for review")
        return doc

    def _save_to_screening_library(
        self, campaign_id: CampaignId, question: str, answer_text: str, *, essay: bool
    ) -> None:
        """Best-effort upsert into the reusable screening-answer library (#20).

        Keyed by the NORMALIZED question text so re-asking the same question later
        (in this or a future application) hits the same entry. A missing repo (an
        adapter that hasn't wired ``screening_answer_library``) or any failure is a
        silent no-op -- this is purely additive convenience on top of a generation
        that already succeeded and was already persisted as a reviewable document;
        it must never be able to break that.
        """
        repo = getattr(self._storage, "screening_answer_library", None)
        if repo is None:
            return
        key = normalize_screening_question(question)
        if not key:
            return
        try:
            repo.upsert(
                ScreeningAnswerLibraryEntry(
                    id=ScreeningAnswerLibraryEntryId(new_id()),
                    campaign_id=campaign_id,
                    question_key=key,
                    question_text=question.strip(),
                    answer_text=answer_text,
                    essay=essay,
                )
            )
        except Exception:  # pragma: no cover - defensive; never break generation
            self._note_silent_degradation("material_service.py")

    def list_screening_answer_library(self, campaign_id: CampaignId) -> list[dict]:
        """The saved screening-answer library for a campaign (#20), for the review/
        Tracker UI to browse and reuse. Empty list when unwired or empty."""
        repo = getattr(self._storage, "screening_answer_library", None)
        if repo is None:
            return []
        try:
            entries = repo.list_for_campaign(campaign_id)
        except Exception:  # pragma: no cover - defensive
            self._note_silent_degradation("material_service.py")
            return []
        return [
            {
                "question": e.question_text,
                "answer": e.answer_text,
                "essay": e.essay,
            }
            for e in sorted(entries, key=lambda e: e.question_text.lower())
        ]

    def reuse_screening_answer(
        self, campaign_id: CampaignId, application_id: ApplicationId, question: str
    ) -> GeneratedDocument | None:
        """Reuse a previously-generated library answer for a NEW application (#20).

        Looks the question up by its normalized key; when found, stores the SAME
        answer text as a new reviewable document for ``application_id`` -- no fresh
        LLM call. Reuse never bypasses truthfulness: the stored text is still
        RE-VERIFIED against this application's own true source at the persistence
        boundary (``_store_document``, NFR-TRUTH-1, fail-closed), same as a fresh
        generation, so a stale library entry can never slip an unsupported claim
        into a new application. Returns ``None`` when no library entry matches
        (caller falls back to full generation via ``generate_screening_answer``).
        """
        repo = getattr(self._storage, "screening_answer_library", None)
        if repo is None:
            return None
        key = normalize_screening_question(question)
        if not key:
            return None
        try:
            entry = repo.get(campaign_id, key)
        except Exception:  # pragma: no cover - defensive
            self._note_silent_degradation("material_service.py")
            return None
        if entry is None:
            return None
        self._ensure_voice_for(campaign_id)
        true_source = self._resolve_true_source(campaign_id, "")
        report = self.apply_post_filter(entry.answer_text)
        check_source = self._with_application_context(true_source, application_id)
        doc = self._store_document(
            campaign_id,
            application_id,
            DocumentType.SCREENING_ANSWER,
            report.text,
            provenance=(),
            verify_source=check_source,
            prose=entry.essay,
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

    # === interview prep (product-gaps backlog #30) =========================
    def _has_interview_signal(self, application_id: ApplicationId) -> bool:
        """True once ``application_id`` has an ``interview_invited`` outcome event.

        The gate for interview-prep generation: reads the SAME outcome trail the
        post-submission tracker layers "signals" from (``PostSubmissionService.
        list_tracker_rows``), enforced HERE server-side rather than trusted from a
        caller-supplied flag (CLAUDE.md: never let a caller-supplied input opt a
        gate in). Best-effort: an unreachable outcomes repo reads as "no signal
        yet" rather than raising.
        """
        try:
            events = self._storage.outcomes.list_for_application(application_id)
        except Exception:  # pragma: no cover - defensive
            return False
        return any(getattr(e, "type", None) == "interview_invited" for e in events)

    @staticmethod
    def _extract_key_requirements(posting) -> list[str]:
        """A short, PURELY EXTRACTIVE list of the posting's own stated requirements.

        Never generated/summarized by an LLM -- it just splits the posting's own
        description into short lines/sentences -- so it can never mis-describe the
        role or introduce a claim about the candidate (nothing here touches the
        truthfulness guardrail because nothing here is written ABOUT the candidate).
        Bounded to a handful of entries so the brief stays skimmable.
        """
        if posting is None:
            return []
        desc = (getattr(posting, "description", "") or "").strip()
        if not desc:
            return []
        parts = re.split(r"[\n\r]+|(?<=[.;])\s+", desc)
        lines = [p.strip(" -*•\t") for p in parts]
        return [ln for ln in lines if len(ln) >= 8][:8]

    def generate_interview_prep(
        self, campaign_id: CampaignId, application_id: ApplicationId
    ) -> dict | None:
        """A plain-language "things to review before your interview" brief (#30).

        Gated on the application having actually reached the ``interview_invited``
        signal (see ``_has_interview_signal``) -- returns ``None`` (the same "not
        warranted yet" convention ``generate_cover_letter`` uses) rather than
        fabricating a brief for an application that was never invited to interview.
        Reuses the SAME capped/deduped/cached company-research channel cover-letter
        generation already draws on (``_company_research_context`` -> the shared
        ``ResearchService``, #299) -- no second research pipeline -- plus the
        posting's own stated requirements (purely extractive, never generated).
        This is advisory/informational, not submitted material, so it is returned
        as a plain dict rather than a reviewable ``GeneratedDocument``: nothing here
        needs the review gate.
        """
        if not self._has_interview_signal(application_id):
            return None
        try:
            app = self._storage.applications.get(application_id)
        except Exception:  # pragma: no cover - defensive
            app = None
        if app is None:
            return None
        posting = None
        pid = getattr(app, "posting_id", None)
        if pid is not None:
            try:
                posting = self._storage.postings.get(pid)
            except Exception:  # pragma: no cover - defensive
                posting = None
        company, role = self._company_role_for(application_id)
        research_ctx = self._company_research_context(campaign_id, application_id)
        key_requirements = self._extract_key_requirements(posting)
        if not company and not role and not key_requirements and not research_ctx:
            # Nothing to build a brief FROM -- degrade to "not generated" rather
            # than hand back an empty, useless shell.
            return None
        notes: list[str] = []
        who = company or "the company"
        if role:
            notes.append(f"You're interviewing for {role} at {who}.")
        else:
            notes.append(f"You're interviewing with {who}.")
        if key_requirements:
            notes.append(
                "The posting calls out these points -- be ready to speak to each "
                "with a real example from your own history:"
            )
        return {
            "company": company,
            "role": role,
            "notes": notes,
            "key_requirements": key_requirements,
            "company_research": research_ctx,
        }

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
        # Constrain the revision to the candidate's own voice (FR-RESUME-5: on every
        # revision pass), extracting it from their résumé corpus the first time.
        if doc is not None:
            self._ensure_voice_for(doc.campaign_id)

        if len(session.turns) >= REFINEMENT_BUDGET:
            ai_response = "Refinement budget reached; please approve or decline."
            new_content = content
        else:
            new_content, ai_response = self._revise(content, kind, instruction)
            # Every revision pass re-applies the post-filter (FR-RESUME-5).
            new_content = self.apply_post_filter(new_content).text
            # Fabrication guardrail on revision too (FR-RESUME-2 / NFR-TRUTH-1) —
            # "a revision can never introduce an unsupported claim".
            effective_source = true_source
            guard_prose = bool(doc) and doc.type in (
                DocumentType.COVER_LETTER,
                DocumentType.SCREENING_ANSWER,
            )
            if effective_source is None and doc is not None:
                # The front-door does not send ``true_source`` on a turn, so the guard
                # was silently skipped. DERIVE the ground truth server-side from the
                # document's campaign attributes PLUS the already-approved content, and
                # use the lenient entity-shaped (prose) check: a revision of reviewed
                # content should reject only NEW entity-shaped fabrications (a fake
                # employer, a digit date/metric, an acronym) without re-litigating
                # carried-over text or rephrasing — so the guard always runs but never
                # false-flags a benign edit.
                try:
                    effective_source = self.true_attribute_text(
                        doc.campaign_id, base_source=content
                    )
                    guard_prose = True
                except Exception:  # pragma: no cover - derivation is best-effort
                    effective_source = None
            if effective_source:
                self.assert_no_fabrication(effective_source, new_content, prose=guard_prose)
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
        """Approve the material through the review gate (FR-RESUME-8, FR-NOTIF-4).

        "One-click approve only AFTER viewing": approval is refused until the redline
        review surface has been opened for this document (which durably creates its
        revision session via ``open_revision`` / ``apply_turn``). Enforced server-side
        so it can't be bypassed by a caller jumping straight from a notification to
        approve.
        """
        doc = self._storage.documents.get(document_id)
        if doc is None:
            raise NotFound(f"no such document {document_id}")
        if self._storage.revisions.get_for_material(document_id) is None:
            raise ReviewRequired(
                "Open the review for this document before approving it."
            )
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
            # Keep the "What I drew on" record through approval.
            provenance=doc.provenance,
        )
        self._storage.documents.add(approved)
        self._storage.commit()
        event_bus.emit(MaterialApproved(document_id=document_id))
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
                self._note_silent_degradation("material_service.py")
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
                self._note_silent_degradation("material_service.py")
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

    # --- learned context (FR-MIND-1/2/3/5; advisory only) -----------------
    def _learned_context(
        self, campaign_id: CampaignId | None, *, query: str
    ) -> str:
        """The bounded learned-context prompt block only (see
        :meth:`_learned_context_with_provenance`). Kept so any external caller of
        the historical signature still gets the prompt block unchanged."""
        block, _prov = self._learned_context_with_provenance(campaign_id, query=query)
        return block

    def _learned_context_with_provenance(
        self, campaign_id: CampaignId | None, *, query: str
    ) -> tuple[str, tuple[LearnedProvenance, ...]]:
        """A BOUNDED "what the assistant has learned" block for generation (FR-MIND-5)
        PLUS the advisory provenance of which learned items it drew on (FR-MIND-5/-11,
        FR-OBS-2).

        Mirrors the chatbot's advisory memory block but is local to this service (no
        cross-service import). Read fresh from the agent-memory trio on every call
        (never cached on the instance — FR-MIND-10):

          (a) a few curated-memory lines (the user's style/preferences/corrections),
          (b) the top matching saved-playbook hints (L0 metadata — e.g. how to phrase
              answers for a given company/ATS — cheap, no bodies, FR-MIND-2/-13), and
          (c) optionally one recall hit for a prior similar application.

        The returned provenance lists EXACTLY the items folded into the block — the
        same memory lines / playbook names / recall run-id, nothing more. It is purely
        descriptive ("What I drew on"): it confers NO authority and never asserts a
        fact about the user.

        SAFETY (FR-MIND-11 + FR-RESUME-2): every line is ADVISORY ONLY. It may shape
        phrasing / voice / approach, but it can NEVER invent facts about the user and
        it confers NO authority. Any memory line / skill / recall hit that *claims* a
        safety-gated authority (submit/account/CAPTCHA/skip-review) is DROPPED via the
        core ``claims_authority`` rule so it can never read as an instruction the
        assistant must obey (and so it is never recorded as provenance). The
        fabrication guard (``assert_no_fabrication``) still runs afterward against the
        user's TRUE source, so a "skill" that suggested inventing a credential cannot
        survive into the stored document.

        Degrades silently to ``("", ())`` when no ``agent_memory`` is wired
        (byte-identical to the prior behavior) or nothing relevant is on file.
        """
        am = self._agent_memory
        if am is None:
            return "", ()
        from applicant.core.rules.agent_memory import claims_authority

        scope = str(campaign_id) if campaign_id is not None else None
        lines: list[str] = []
        provenance: list[LearnedProvenance] = []

        # (a) curated memory — user style/preferences (bounded by the store).
        try:
            snap = am.memory.snapshot(campaign_id=scope)
        except Exception:
            self._note_silent_degradation("material_service.py")
            snap = None
        if snap is not None:
            mem_lines: list[str] = []
            for e in (tuple(snap.user) + tuple(snap.environment))[:8]:
                txt = getattr(e, "text", "")
                if not txt or claims_authority(txt):
                    # Advisory-only: never surface an authority claim as guidance.
                    continue
                mem_lines.append(f"- {txt}")
                provenance.append(
                    LearnedProvenance(kind="memory", label=txt.strip(), ref=txt.strip())
                )
            if mem_lines:
                lines.append(
                    "What you have learned about this user's style and preferences "
                    "(use for phrasing/voice only; never to invent facts):"
                )
                lines.extend(mem_lines)

        # (b) a few relevant saved playbooks (L0 metadata — cheap, no bodies).
        try:
            metas = am.skills.list_skills(campaign_id=scope)
        except Exception:
            self._note_silent_degradation("material_service.py")
            metas = ()
        if metas:
            q = {w for w in (query or "").lower().split() if len(w) > 3}
            scored = []
            for m in metas:
                hay = (
                    f"{getattr(m, 'description', '')} "
                    f"{getattr(m, 'when_to_use', '')}"
                ).lower()
                if claims_authority(hay):
                    # Advisory-only: drop a playbook that claims authority.
                    continue
                overlap = len(q & set(hay.split())) if q else 0
                scored.append((overlap, m))
            scored.sort(key=lambda t: t[0], reverse=True)
            top = scored[:3]
            skill_lines = []
            for _, m in top:
                name = getattr(m, "name", "")
                desc = getattr(m, "when_to_use", "") or getattr(m, "description", "")
                line = f"- {name}: {desc}"
                if not line.strip(" -:"):
                    continue
                skill_lines.append(line)
                if name:
                    provenance.append(
                        LearnedProvenance(
                            kind="playbook", label=f"the '{name}' playbook", ref=name
                        )
                    )
            if skill_lines:
                lines.append("Saved playbooks you may consult (advice only):")
                lines.extend(skill_lines)

        # (c) one recall hit for a prior similar application (on-demand, cheap).
        recall = getattr(am, "recall", None)
        if recall is not None and query:
            try:
                hits = recall.search(query, limit=1, campaign_id=scope)
            except Exception:
                self._note_silent_degradation("material_service.py")
                hits = ()
            for h in hits:
                txt = getattr(h, "text", "")
                if not txt or claims_authority(txt):
                    continue
                snippet = txt.strip().replace("\n", " ")[:200]
                if snippet:
                    lines.append(
                        "From a prior similar application (background only): "
                        + snippet
                    )
                    provenance.append(
                        LearnedProvenance(
                            kind="recall",
                            label="a prior similar application",
                            ref=str(getattr(h, "run_id", "") or ""),
                        )
                    )
                break

        if not lines:
            return "", ()
        # Hard-bound the whole block so learned context never bloats the prompt
        # (FR-MIND-13). A generous cap that still fits several lines + a recall hit.
        block = "\n".join(lines)
        return block[:1500], tuple(provenance)

    # --- internals --------------------------------------------------------
    def _generate_text(
        self,
        true_source: str,
        terms: list[str],
        *,
        kind: str,
        campaign_id: CampaignId | None = None,
    ) -> str:
        """1 LLM pass with deterministic truthful fallback when no LLM is wired.

        Records the advisory learned-item provenance for THIS pass on
        ``_last_provenance`` so the calling generator can attach it to the stored
        material (FR-MIND-5/-11, FR-OBS-2). Provenance reflects what was ACTUALLY
        drawn on: it is set only when the learned block was folded into the LLM
        prompt, and cleared on the deterministic fallback (which consults no learned
        context), so it never overstates the influence.
        """
        # Default: nothing was drawn on (the deterministic fallback path).
        self._last_provenance = ()
        # Reset the degraded marker for this pass; set only on ladder exhaustion.
        self._last_degraded = False
        # Neutralize untrusted scraped text before it enters the LLM prompt so an
        # attacker-controlled posting cannot steer tailoring/screening answers.
        safe_source = neutralize_untrusted_text(true_source)
        if self._llm is not None and getattr(self._llm, "is_configured", lambda: False)():
            try:
                from applicant.ports.driven.llm import ChatMessage

                # Voice-matching + the truthful-framing dial constrain generation on
                # every pass (FR-RESUME-5/9). The dial only biases framing.
                system = _SYSTEM_PROMPT + "\n" + self._voice.as_directive()
                system += "\n" + aggressiveness_directive(self._aggressiveness)
                if self._extra_banned:
                    system += "\nAvoid these phrases: " + "; ".join(self._extra_banned)
                # FR-MIND-1/2/5: append a BOUNDED, advisory-only "what the assistant has
                # learned" block (curated style/preferences + matching saved-playbook
                # hints + a prior-similar-application recall). Read fresh per call
                # (FR-MIND-10). No-op when no ``agent_memory`` is wired => byte-identical.
                # The provenance lists exactly the items folded in, recorded for the
                # review UI's "What I drew on" line.
                learned, provenance = self._learned_context_with_provenance(
                    campaign_id, query=" ".join([kind, *terms])
                )
                if learned:
                    system += "\n\n" + learned
                    self._last_provenance = provenance
                result = self._llm.complete(
                    [
                        ChatMessage(role="system", content=system),
                        ChatMessage(
                            role="user",
                            content=f"[{kind}] Source:\n{safe_source}\nEmphasize: {', '.join(terms)}",
                        ),
                    ],
                    # Heavy writing escalates straight to L2 (FR-LLM-3/4); it still
                    # climbs further on low confidence / context overflow.
                    start_tier=_HEAVY_WRITING_START_TIER,
                )
                return _strip_llm_preamble(result.text)
            except LLMLadderExhausted as exc:
                # A configured model exists but EVERY tier (up AND down) failed —
                # e.g. a misconfigured upper tier returning 401. This is NOT the
                # benign "no model wired" path: log it loudly and mark the result
                # degraded so the canned deterministic draft is visible as a
                # fallback rather than masquerading as a real generation.
                log.error(
                    "material generation degraded: LLM tier ladder exhausted "
                    "(kind=%s); falling back to deterministic draft: %s",
                    kind,
                    exc,
                )
                self._last_degraded = True
                self._note_silent_degradation("material_service.py")
                self._last_provenance = ()
            except Exception:
                self._note_silent_degradation("material_service.py")
                # Generation fell back to the deterministic path — no learned context
                # was actually used, so do not record provenance for it.
                self._last_provenance = ()
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
            self._note_silent_degradation("material_service.py")
            return None

    def _store_document(
        self,
        campaign_id: CampaignId,
        application_id: ApplicationId,
        dtype: DocumentType,
        content: str,
        *,
        provenance: tuple[LearnedProvenance, ...] = (),
        verify_source: str | None,
        prose: bool = False,
        policy_exempt: bool = False,
    ) -> GeneratedDocument:
        """Persist a generated document, fail-closed on truthfulness (NFR-TRUTH-1).

        The fabrication post-check runs HERE, at the persistence boundary, as the
        last gate before ``documents.add`` — so unverified generated text can NEVER
        reach storage even if a caller forgot to check or an earlier step raised
        before its own (caller-level) check. ``verify_source`` is the candidate's
        TRUE ground truth the content is checked against; ``prose`` selects the
        entity-shaped check for free-prose material (cover letters / essays).

        ``policy_exempt=True`` is the ONLY way to persist content that is not derived
        from ``verify_source`` (the EEO/sensitive path: a canned decline or an
        explicit stored answer, which the source-comparison check does not apply to,
        FR-ATTR-6). A non-exempt call MUST pass a ``verify_source``; passing ``None``
        without ``policy_exempt`` is a programming error and raises rather than
        silently persisting unchecked text.
        """
        if not policy_exempt:
            if verify_source is None:
                # White-label (principle #3): no requirement-id jargon in the message.
                raise TruthfulnessViolation(
                    "refusing to persist generated material without a truthfulness "
                    "ground-truth source to check it against"
                )
            # Mandatory fail-closed post-check at the persistence boundary. Raises
            # TruthfulnessViolation on any unsupported claim; nothing is stored.
            self.assert_no_fabrication(verify_source, content, prose=prose)
        doc = GeneratedDocument(
            id=GeneratedDocumentId(new_id()),
            campaign_id=campaign_id,
            application_id=application_id,
            type=dtype,
            content=content,
            approved=False,
            # Advisory "What I drew on" record (FR-MIND-5/-11, FR-OBS-2). Empty
            # unless the learned-context block was actually folded into generation.
            provenance=tuple(provenance),
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
            # Preserve the original draft's provenance across a revision turn —
            # the learned items it drew on still describe where the draft came from.
            provenance=doc.provenance,
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
