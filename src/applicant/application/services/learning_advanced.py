"""AdvancedLearningService — Phase 4 learning depth/breadth (FR-LEARN-2/3/4).

# STAGE B — owned by Phase 4. NEW module; does NOT touch Phase 1's
# learning_service.py (kept stable). This layer adds the *depth* hooks on top of
# the cheap statistical base:

- **Real-conversion learning (FR-LEARN-2):** a *conversion* for a campaign is
  approval **plus** submission (§10 "Conversion is approval plus submission").
  An outcome event (auto-detected OR one-tap mark-submitted, FR-LOG-4) folds the
  converting application's *rich* role signature (title, seniority, skills, comp
  band, work mode, source, resume-variant traits) into the campaign learning model
  so the next discovery/scoring/variant-selection run is biased toward what
  actually converts (FR-LEARN-5). A bare approval **never** moves the needle.
- **Cross-input learning (FR-LEARN-3):** EVERY signal folds into the same
  per-campaign model — digest approvals/declines + decline free-text, submissions/
  conversions, resume/career parsed attributes, chat/survey feedback, redline
  revision feedback (the edits the user makes), pre-fill soft-error resolutions,
  and source yield. This module reuses the Phase 1 ``LearningService`` for the
  cheap feature/source folds and layers conversion + cross-reference depth on top so
  the loop closes across all inputs.
- **Attribute cross-referencing (FR-LEARN-4):** continuously reconcile newly-observed
  values across all inputs into the attribute cloud. **Non-integral** attributes
  auto-apply; **integral** attributes route through the core confirmation gate
  (FR-FB-3) and are held until the user confirms — never silently committed.
  **Sensitive (EEO)** values are NEVER auto-learned (FR-ATTR-6). Conflicting
  observations (the same attribute implied two different values by two inputs) are
  detected and surfaced rather than silently last-write-wins.

State lives on the immutable ``LearningModel`` (pure-functional updates), exactly
like Phase 1, and persists per campaign via ``LearningService.persist_model`` so it
survives restart. The LLM is reserved for human-readable summaries, never the hot
path (FR-LEARN-7).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute, AttributeStore
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.learning_model import LearningModel
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.rules.confirmation_gate import ensure_change_allowed, requires_confirmation
from applicant.core.rules.sensitive_fields import is_sensitive_field
from applicant.core.state_machine import ApplicationState

#: Weight a confirmed conversion carries into the role signature (vs a bare approve).
_CONVERSION_WEIGHT = 1.0

#: A campaign-level conversion requires the application to have reached an approval
#: state AND have a submission outcome event (§10 "approval plus submission").
_APPROVAL_STATES: frozenset[ApplicationState] = frozenset(
    {
        ApplicationState.APPROVED,
        ApplicationState.AWAITING_FINAL_APPROVAL,
        ApplicationState.MATERIAL_REVIEW,
        ApplicationState.SUBMITTED_BY_USER,
        ApplicationState.FINISHED_BY_ENGINE,
    }
)

#: Outcome event types that count as a submission (auto or manual, FR-LOG-4).
_SUBMISSION_TYPES: frozenset[str] = frozenset({"submitted", "converted"})

#: Common seniority tokens we lift out of a title into a coarse band signal.
_SENIORITY_BANDS: tuple[str, ...] = (
    "intern",
    "junior",
    "associate",
    "mid",
    "senior",
    "staff",
    "principal",
    "lead",
    "director",
    "vp",
    "head",
)

#: A small, cheap skill lexicon for deterministic skill extraction (no LLM).
_SKILL_LEXICON: tuple[str, ...] = (
    "python",
    "java",
    "go",
    "golang",
    "rust",
    "typescript",
    "javascript",
    "react",
    "fastapi",
    "django",
    "flask",
    "postgres",
    "postgresql",
    "mysql",
    "kubernetes",
    "docker",
    "aws",
    "gcp",
    "azure",
    "terraform",
    "kafka",
    "spark",
    "ml",
    "nlp",
    "llm",
)


@dataclass(frozen=True)
class AttributeProposal:
    """A proposed attribute value derived by cross-referencing inputs (FR-LEARN-4).

    ``applied`` is True when the proposal auto-applied (non-integral); when the
    target attribute is integral it stays ``applied=False`` and
    ``needs_confirmation=True`` until the user confirms via the gate (FR-FB-3).
    ``conflict`` is True when an existing value disagrees with the proposed value
    (surfaced rather than silently overwritten).
    """

    name: str
    value: str
    source: str  # which input implied it (e.g. "resume", "screening_answer")
    is_integral: bool
    applied: bool
    needs_confirmation: bool
    conflict: bool = False
    current_value: str | None = None


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of reconciling a batch of observed values into the attribute cloud.

    ``applied`` were auto-committed (non-integral, no conflict). ``pending`` need
    user confirmation (integral). ``conflicts`` disagree with an existing value and
    are surfaced for the user to resolve (never silently overwritten). ``skipped``
    were sensitive (EEO) and never auto-learned (FR-ATTR-6).
    """

    applied: list[AttributeProposal] = field(default_factory=list)
    pending: list[AttributeProposal] = field(default_factory=list)
    conflicts: list[AttributeProposal] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class AdvancedLearningService:
    """Phase-4 learning depth layered over the cheap Phase 1 base.

    Composes (does not subclass) ``LearningService`` so the stable Phase 1 folds
    stay authoritative and this module only adds conversion + cross-reference depth.
    """

    def __init__(self, base, storage=None, *, recall=None) -> None:
        self._base = base
        self._storage = storage
        # Optional RecallIndex (FR-MIND-3): a cheap, on-demand "roles like the ones
        # that converted" probe used as an ADVISORY nudge for the discovery/scoring/
        # variant-selection bias (FR-LEARN-5). ``None`` (the default) => no recall
        # term, so behavior is byte-identical to before.
        self._recall = recall

    # === real-conversion detection (FR-LEARN-2 / §10) =====================
    def is_conversion(self, application: Application, outcomes: list[OutcomeEvent]) -> bool:
        """A conversion = approval **plus** submission (§10, FR-LEARN-2/FR-LOG-4).

        Approval is read from the application's lifecycle state; submission is any
        outcome event (auto-detected or one-tap mark-submitted) for that app.
        """
        approved = application.status in _APPROVAL_STATES
        submitted = any(
            e.application_id == application.id and e.type in _SUBMISSION_TYPES
            for e in outcomes
        )
        return approved and submitted

    def record_conversion(
        self,
        model: LearningModel,
        application: Application,
        outcomes: list[OutcomeEvent],
        *,
        posting: JobPosting | None = None,
    ) -> LearningModel:
        """Fold a confirmed conversion's rich role signature into the campaign model.

        No-op (returns the model unchanged) unless the application is a true
        conversion, so a bare approval without submission never moves the needle
        (the loop only closes on real outcomes — FR-LEARN-2). When the originating
        ``posting`` is supplied, salary/skill/location features are mined from the JD
        too so the converting-role signature is rich (FR-LEARN-5).
        """
        if not self.is_conversion(application, outcomes):
            return model
        signature = dict(model.converting_role_signature)
        for feature in self._role_features(application, posting=posting):
            signature[feature] = signature.get(feature, 0.0) + _CONVERSION_WEIGHT
        # #238: also fold the converting role's text into the Phase-1 embedding CENTROID
        # (``converting_role_signature["vector"]``) so the live loop populates it — not
        # just the discrete features. Previously ``record_converting_role`` (the only
        # writer of the centroid vector) was never called by the live loop, so the
        # Phase-1 ``converting_alignment`` stayed 0.0 forever. The centroid and the
        # discrete features are complementary facets of the SAME conversion; folding
        # both here keeps ``converting_samples`` a single source of truth (incremented
        # once below) and feeds every reader (scoring/discovery/variant selection).
        signature = self._fold_centroid_vector(
            signature,
            sample_count=model.converting_samples,
            application=application,
            posting=posting,
        )
        return replace(
            model,
            converting_role_signature=signature,
            converting_samples=model.converting_samples + 1,
        )

    def _fold_centroid_vector(
        self,
        signature: dict,
        *,
        sample_count: int,
        application: Application,
        posting: JobPosting | None,
    ) -> dict:
        """Incrementally fold the converting role's JD text into the centroid vector.

        Mirrors ``LearningService.record_converting_role``'s running-mean math but
        WITHOUT bumping the sample count (the discrete fold owns the single increment),
        so the centroid and the discrete features share one ``converting_samples``.
        Requires an embedding (via the Phase-1 base); degrades to leaving the centroid
        untouched when no embedding/text is available, so the discrete fold still lands.

        """
        embedding = getattr(self._base, "_embedding", None)
        if embedding is None:
            return signature
        title = application.job_title or application.role_name or ""
        description = ""
        if posting is not None:
            title = title or posting.title
            description = posting.description or ""
        jd_text = f"{title} {description}".strip()
        if not jd_text:
            return signature
        try:
            vecs = embedding.embed([jd_text])
        except Exception:  # pragma: no cover - embedding must never break a conversion
            return signature
        if not vecs or not vecs[0]:
            return signature
        vec = vecs[0]
        prior = signature.get("vector")
        n = sample_count
        if prior and len(prior) == len(vec):
            merged = [(prior[i] * n + vec[i]) / (n + 1) for i in range(len(vec))]
        else:
            merged = list(vec)
        out = dict(signature)
        out["vector"] = merged
        # Deliberately do NOT also write a ``titles`` list here: the discrete fold
        # already records the role title as a ``role:`` feature (read by
        # ``converting_titles``), and the discrete bias readers (``conversion_alignment``
        # / ``text_alignment`` / ``variant_alignment``) sum over signature VALUES — a
        # list under ``titles`` would break that sum. ``vector`` is the only non-numeric
        # key and is already skipped by every discrete reader.
        return out

    def record_and_persist_conversion(
        self, campaign_id, application: Application, *, posting: JobPosting | None = None
    ) -> LearningModel:
        """Storage-backed close-the-loop: read outcomes, fold, persist (FR-LEARN-2).

        Convenience for the application layer / endpoints: it reads the application's
        outcome events from storage, records the conversion, and persists the updated
        per-campaign model so the next run is biased and the state survives restart.
        Requires a storage-bound ``base`` LearningService.
        """
        if self._storage is None:
            raise RuntimeError("record_and_persist_conversion requires storage")
        outcomes = self._storage.outcomes.list_for_application(application.id)
        model = self._base.load_model(campaign_id)
        model = self.record_conversion(model, application, outcomes, posting=posting)
        self._base.persist_model(model)
        return model

    def conversion_alignment(
        self,
        model: LearningModel,
        application: Application,
        *,
        posting: JobPosting | None = None,
    ) -> float:
        """Cheap similarity of a candidate posting's role features to converters.

        Used to bias scoring/selection toward what actually converts (FR-LEARN-5);
        0.0 when nothing has converted yet (cold start). Only counts the discrete
        feature buckets (ignores the centroid ``vector`` Phase 1 may also store).
        """
        sig = {k: v for k, v in model.converting_role_signature.items() if k != "vector"}
        if not sig:
            return 0.0
        feats = set(self._role_features(application, posting=posting))
        hit = sum(sig.get(f, 0.0) for f in feats)
        total = sum(sig.values()) or 1.0
        return hit / total

    def converting_signature_summary(self, model: LearningModel) -> dict[str, list[str]]:
        """A human-readable digest of what converts, grouped by facet (FR-LEARN-5).

        Cheap + deterministic (no LLM): groups the discrete signature features by
        their facet (role/seniority/skill/work_mode/comp/source/variant) ordered by
        learned weight, so the UI can transparently show the learned bias and the
        user can override it (FR-CRIT-2 transparency).
        """
        grouped: dict[str, list[tuple[str, float]]] = {}
        for feat, weight in model.converting_role_signature.items():
            if feat == "vector" or ":" not in feat:
                continue
            facet, value = feat.split(":", 1)
            grouped.setdefault(facet, []).append((value, float(weight)))
        return {
            facet: [v for v, _ in sorted(vals, key=lambda x: -x[1])]
            for facet, vals in grouped.items()
        }

    def load_model(self, campaign_id) -> LearningModel:
        """Load the per-campaign learning model (passthrough to the Phase-1 base).

        Lets bias readers (discovery/scoring/variant-selection) fetch the model
        through the advanced service without reaching into ``_base``.
        """
        return self._base.load_model(campaign_id)

    # === discrete-signature bias readers (FR-LEARN-5) =====================
    # The LIVE conversion loop (submission_service -> record_and_persist_conversion)
    # folds ONLY the discrete role-feature signature here (``role:``/``skill:``/
    # ``comp:``/``variant:``/...), bumping ``converting_samples``. The Phase-1
    # centroid ``vector`` is a SEPARATE facet that the live loop does not currently
    # populate. These readers let discovery/scoring/variant-selection bias off the
    # discrete signature that conversions ACTUALLY write, complementing the cheap
    # statistical base WITHOUT re-folding any signal (read-only; no double-count).

    def converting_titles(self, model: LearningModel) -> list[str]:
        """Titles of roles that actually converted, for discovery title bias.

        Derived from the ``role:`` features of the discrete converting signature this
        module folds on a real conversion (FR-LEARN-2/5). Ordered by learned weight
        (most-converting first). Empty at cold start (no bias). Complements — does not
        duplicate — the Phase-1 ``LearningService.converting_titles`` (which reads the
        centroid's ``titles`` list); the agent loop merges both, de-duped.
        """
        roles = [
            (feat.split(":", 1)[1], float(weight))
            for feat, weight in model.converting_role_signature.items()
            if feat != "vector" and feat.split(":", 1)[0] == "role" and ":" in feat
        ]
        return [v for v, _ in sorted(roles, key=lambda x: -x[1]) if v]

    def text_alignment(self, model: LearningModel, text: str) -> float:
        """Cheap lexical alignment in [0,1] of free ``text`` (a JD / variant sig) to
        the discrete converting signature (FR-LEARN-5, no LLM).

        Counts the share of the signature's learned weight whose feature VALUE token
        appears in ``text`` — so a posting that reads like the roles/skills/seniority
        that actually converted scores higher. 0.0 at cold start (nothing converted)
        or empty text, so the caller applies no bias. This reads the SAME signature
        the conversion fold wrote; it never re-folds, so it cannot double-count.
        """
        if not text or not text.strip():
            return 0.0
        haystack = text.lower()
        hit = 0.0
        total = 0.0
        for feat, weight in model.converting_role_signature.items():
            if feat == "vector" or ":" not in feat:
                continue
            w = float(weight)
            total += w
            value = feat.split(":", 1)[1].strip().lower()
            if value and value in haystack:
                hit += w
        if total <= 0.0:
            return 0.0
        return max(0.0, min(1.0, hit / total))

    def variant_alignment(self, model: LearningModel, variant_id) -> float:
        """Share of the discrete signature's weight carried by ``variant:{id}`` —
        i.e. how strongly THIS résumé variant is the one that past conversions used
        (FR-LEARN-5). 0.0 when no conversion used it (cold start / different variant),
        so variant selection falls back to coverage unchanged.
        """
        if variant_id is None:
            return 0.0
        target = f"variant:{variant_id}"
        sig = {k: float(v) for k, v in model.converting_role_signature.items() if k != "vector"}
        total = sum(sig.values())
        if total <= 0.0:
            return 0.0
        return max(0.0, min(1.0, sig.get(target, 0.0) / total))

    def recall_titles(self, campaign_id, *, limit: int = 3) -> list[str]:
        """ADVISORY: a few role titles recalled from "roles like the ones that
        converted" via the recall index (FR-MIND-3), for discovery title bias.

        On-demand + bounded (FR-MIND-13); returns ``[]`` when no recall index is
        wired or nothing is on file, so it never floods criteria and is byte-identical
        to before when recall is absent. Heuristic title extraction (no LLM): the
        leading short line of a recalled excerpt.
        """
        if self._recall is None:
            return []
        try:
            hits = self._recall.search(
                "roles like the ones that converted",
                limit=limit,
                campaign_id=str(campaign_id) if campaign_id is not None else None,
            )
        except Exception:  # pragma: no cover - recall must never break discovery
            return []
        titles: list[str] = []
        for h in hits:
            txt = (getattr(h, "text", "") or "").strip()
            if not txt:
                continue
            first = txt.splitlines()[0].strip()
            # Keep it title-shaped (short); drop long prose lines.
            if 0 < len(first) <= 80 and first not in titles:
                titles.append(first)
        return titles

    def recall_alignment(self, campaign_id, text: str) -> float:
        """ADVISORY recall nudge in [0,1]: relevance of ``text`` to "roles like the
        ones that converted" (FR-MIND-3 recall) for scoring/variant bias (FR-LEARN-5).

        Returns the top recall hit's relevance score, bounded. 0.0 when no recall is
        wired or nothing relevant is recalled, so it adds no bias by default. Used as a
        SMALL secondary term blended via ``max`` with the signature alignment (never
        additively stacked) so the same conversion evidence is not double-counted.
        """
        if self._recall is None or not (text or "").strip():
            return 0.0
        try:
            hits = self._recall.search(
                text,
                limit=1,
                campaign_id=str(campaign_id) if campaign_id is not None else None,
            )
        except Exception:  # pragma: no cover - recall must never break scoring
            return 0.0
        if not hits:
            return 0.0
        return max(0.0, min(1.0, float(getattr(hits[0], "score", 0.0) or 0.0)))

    @staticmethod
    def _role_features(
        application: Application, *, posting: JobPosting | None = None
    ) -> list[str]:
        """Cheap, deterministic role-signature features (no LLM, FR-LEARN-7).

        Mines the converting application (and its JD, when available) for: role
        title, seniority band, skills, work mode, salary/comp band, source, and the
        resume variant that converted — so the signature is rich (FR-LEARN-5).
        """
        feats: list[str] = []
        title = application.job_title or application.role_name
        work_mode = application.work_mode
        location = None
        salary = None
        description = ""
        if posting is not None:
            title = title or posting.title
            work_mode = work_mode or posting.work_mode
            location = posting.location
            salary = posting.salary
            description = posting.description or ""

        if title:
            title_low = title.strip().lower()
            feats.append(f"role:{title_low}")
            for band in _SENIORITY_BANDS:
                if band in title_low:
                    feats.append(f"seniority:{band}")
                    break
        if work_mode:
            feats.append(f"work_mode:{work_mode.strip().lower()}")
        if location:
            feats.append(f"location:{location.strip().lower()}")

        haystack = f"{title or ''} {description}".lower()
        seen_skills: set[str] = set()
        for skill in _SKILL_LEXICON:
            if skill in haystack and skill not in seen_skills:
                seen_skills.add(skill)
                feats.append(f"skill:{skill}")

        comp = _comp_band(salary)
        if comp:
            feats.append(f"comp:{comp}")

        if application.resume_variant_id is not None:
            feats.append(f"variant:{application.resume_variant_id}")
        if posting is not None and posting.source_key:
            feats.append(f"source:{posting.source_key}")
        return feats

    # === cross-input learning (FR-LEARN-3) ================================
    def fold_decision(
        self, model: LearningModel, *, approved: bool, features: dict | None = None
    ) -> LearningModel:
        """Fold an approve/decline signal (delegates to the stable Phase 1 fold)."""
        return self._base.record_decision(model, approved=approved, features=features)

    def fold_decline_feedback(
        self, model: LearningModel, *, feedback_text: str, criteria_delta: dict | None = None
    ) -> LearningModel:
        """Fold a decline's free-text + criteria delta (FR-DIG-5 / FR-FB-1)."""
        return self._base.ingest_decline_feedback(
            model, feedback_text=feedback_text, criteria_delta=criteria_delta
        )

    def fold_revision_feedback(
        self, model: LearningModel, *, edits: list[dict] | None = None, free_text: str = ""
    ) -> LearningModel:
        """Fold redline revision feedback — the edits the user makes (FR-RESUME-8).

        Each edit is ``{"op": "add"|"subtract", "text": "..."}``. Adds are folded as
        *approved* features (the user wants more of this) and subtracts as *declined*
        features (less of this), so material generation/selection learns the user's
        taste. Cheap keyword folding; no LLM (FR-LEARN-7).
        """
        for edit in edits or []:
            op = str(edit.get("op", "")).lower()
            text = str(edit.get("text", "")).lower()
            approved = op == "add"
            feats = {
                f"revision:{tok}": tok for tok in text.split() if len(tok) > 3
            }
            if feats:
                model = self._base.record_decision(model, approved=approved, features=feats)
        if free_text.strip():
            feats = {
                f"revision_note:{tok}": tok
                for tok in free_text.lower().split()
                if len(tok) > 3
            }
            if feats:
                model = self._base.record_decision(model, approved=True, features=feats)
        return model

    def fold_revision_feedback_atomic(
        self, campaign_id, *, edits: list[dict] | None = None, free_text: str = ""
    ) -> LearningModel:
        """Atomically load -> fold redline revision feedback -> persist (FR-LEARN-3).

        Storage-backed close-the-loop for the material-revision/redline turn endpoint:
        serializes the load->fold->persist under the shared per-campaign lock (Batch F)
        so it can't lose-update against a concurrent funnel/decline/approval fold.
        """
        from applicant.application.services.learning_service import _campaign_lock

        with _campaign_lock(campaign_id):
            model = self._base.load_model(campaign_id)
            model = self.fold_revision_feedback(model, edits=edits, free_text=free_text)
            self._base.persist_model(model)
        return model

    def fold_soft_error_resolution_atomic(
        self, campaign_id, *, attribute_name: str, site_key: str = ""
    ) -> LearningModel:
        """Atomically load -> fold a soft-error resolution -> persist (FR-LEARN-4).

        Storage-backed close-the-loop for the missing-attribute resolve flow
        (FR-ATTR-5): the system learns the field is commonly required for the site.
        Serialized under the shared per-campaign lock (Batch F).
        """
        from applicant.application.services.learning_service import _campaign_lock

        with _campaign_lock(campaign_id):
            model = self._base.load_model(campaign_id)
            model = self.fold_soft_error_resolution(
                model, attribute_name=attribute_name, site_key=site_key
            )
            self._base.persist_model(model)
        return model

    def fold_soft_error_resolution(
        self, model: LearningModel, *, attribute_name: str, site_key: str = ""
    ) -> LearningModel:
        """Fold a pre-fill missing-attribute soft-error resolution (FR-ATTR-5).

        When the user supplies a missing attribute during pre-fill, record that this
        field is commonly required for this site so future pre-fills anticipate it.
        """
        feats = {f"required_field:{attribute_name.strip().lower()}": site_key or "any"}
        return self._base.record_decision(model, approved=True, features=feats)

    def fold_source_yield(
        self, model: LearningModel, funnels: dict[str, dict]
    ) -> LearningModel:
        """Fold per-source funnel yield (delegates to the stable Phase 1 fold)."""
        return self._base.record_source_funnel(model, funnels)

    # === attribute cross-referencing (FR-LEARN-4 + FR-FB-3 gate) ==========
    def cross_reference_attribute(
        self,
        store: AttributeStore,
        *,
        name: str,
        value: str,
        source: str,
        is_integral: bool,
        user_confirmed: bool = False,
        attribute_factory=None,
    ) -> tuple[AttributeStore, AttributeProposal]:
        """Propose an attribute value implied by one input; gate integral changes.

        Non-integral attributes auto-apply (FR-LEARN-4 "auto-apply non-integral").
        Sensitive (EEO) attributes are NEVER auto-learned (FR-ATTR-6): the proposal
        is returned un-applied. Integral attributes route through
        ``ensure_change_allowed`` (FR-FB-3): if the user has not confirmed, the value
        is **not** committed and the proposal is returned with
        ``needs_confirmation=True`` (never silently committed). When an existing value
        disagrees with the proposed value, the proposal carries ``conflict=True`` so
        callers can surface it instead of silently overwriting.

        Returns the (possibly updated) store and the proposal record so callers can
        surface pending confirmations / conflicts in the UI.
        """
        existing = store.find(name)
        current_value = existing.value if existing is not None else None
        conflict = bool(
            existing is not None and existing.value and existing.value != value
        )

        # FR-ATTR-6: sensitive fields are never auto-learned from inputs.
        if is_sensitive_field(name) or (existing is not None and existing.is_sensitive):
            return store, AttributeProposal(
                name=name,
                value=value,
                source=source,
                is_integral=is_integral,
                applied=False,
                needs_confirmation=False,
                conflict=conflict,
                current_value=current_value,
            )

        needs_confirm = requires_confirmation(is_integral)
        if needs_confirm and not user_confirmed:
            # Hold integral change at the gate; do not mutate the store.
            return store, AttributeProposal(
                name=name,
                value=value,
                source=source,
                is_integral=is_integral,
                applied=False,
                needs_confirmation=True,
                conflict=conflict,
                current_value=current_value,
            )

        # Either non-integral (auto-apply) or integral-and-confirmed: gate must pass.
        ensure_change_allowed(is_integral=is_integral, user_confirmed=user_confirmed)

        if attribute_factory is not None:
            attr = attribute_factory(name, value, is_integral)
        elif existing is not None:
            attr = replace(existing, value=value, is_integral=is_integral)
        else:
            attr = Attribute(
                id=_synth_attribute_id(),
                campaign_id=store.campaign_id,
                name=name,
                value=value,
                is_integral=is_integral,
            )
        new_store = store.upsert(attr)
        return new_store, AttributeProposal(
            name=name,
            value=value,
            source=source,
            is_integral=is_integral,
            applied=True,
            needs_confirmation=False,
            conflict=conflict,
            current_value=current_value,
        )

    def reconcile_inputs(
        self,
        store: AttributeStore,
        observations: list[dict],
    ) -> tuple[AttributeStore, ReconcileResult]:
        """Continuously reconcile a batch of observed values into the cloud (FR-LEARN-4).

        Each observation is ``{"name", "value", "source", "is_integral"?}``. Walks
        every observation through :meth:`cross_reference_attribute`, auto-applying
        non-integral non-conflicting values, holding integral ones for the
        confirmation gate, surfacing conflicts, and skipping sensitive (EEO) values —
        so EVERY input continuously feeds the attribute cloud without friction while
        respecting the policy boundaries.
        """
        result = ReconcileResult()
        for obs in observations:
            name = str(obs.get("name", "")).strip()
            value = str(obs.get("value", "")).strip()
            if not name or not value:
                continue
            is_integral = bool(obs.get("is_integral", False))
            source = str(obs.get("source", "input"))

            if is_sensitive_field(name) or (
                store.find(name) is not None and store.find(name).is_sensitive
            ):
                result.skipped.append(name)
                continue

            existing = store.find(name)
            if existing is not None and existing.value and existing.value != value:
                # Surface conflict; do not silently overwrite (FR-LEARN-4 reconcile).
                result.conflicts.append(
                    AttributeProposal(
                        name=name,
                        value=value,
                        source=source,
                        is_integral=is_integral,
                        applied=False,
                        needs_confirmation=is_integral,
                        conflict=True,
                        current_value=existing.value,
                    )
                )
                continue

            store, proposal = self.cross_reference_attribute(
                store,
                name=name,
                value=value,
                source=source,
                is_integral=is_integral,
            )
            if proposal.applied:
                result.applied.append(proposal)
            elif proposal.needs_confirmation:
                result.pending.append(proposal)
        return store, result


def _synth_attribute_id():
    from applicant.core.ids import AttributeId, new_id

    return AttributeId(new_id())


def _comp_band(salary: str | None) -> str | None:
    """Map a free-text salary into a coarse comp band (cheap, deterministic).

    Pulls the largest plausible annual figure out of the string and buckets it.
    Returns ``None`` when no number is found (no signal).
    """
    if not salary:
        return None
    import re

    nums: list[float] = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*([kKmM]?)", salary):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        suffix = m.group(2).lower()
        if suffix == "k":
            val *= 1_000
        elif suffix == "m":
            val *= 1_000_000
        elif val < 1000:  # bare "180" almost always means thousands in comp
            val *= 1_000
        nums.append(val)
    if not nums:
        return None
    top = max(nums)
    if top < 80_000:
        return "<80k"
    if top < 120_000:
        return "80-120k"
    if top < 160_000:
        return "120-160k"
    if top < 200_000:
        return "160-200k"
    return "200k+"
