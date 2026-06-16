"""AdvancedLearningService — Phase 4 learning depth/breadth (FR-LEARN-2/3/4).

# STAGE B — owned by Phase 4. NEW module; does NOT touch Phase 1's
# learning_service.py (kept stable). This layer adds the *depth* hooks on top of
# the cheap statistical base:

- **Real-conversion learning (FR-LEARN-2):** a *conversion* for a campaign is
  approval **plus** submission (§10 "Conversion is approval plus submission").
  An outcome event (auto-detected OR one-tap mark-submitted, FR-LOG-4) folds the
  converting application's role signature into the campaign learning model so the
  next discovery/scoring run is biased toward what actually converts (FR-LEARN-5).
- **Cross-input learning (FR-LEARN-3):** every signal — approvals, declines (with
  feedback), and conversions — folds into the same per-campaign model. This module
  reuses the Phase 1 ``LearningService`` for the cheap feature/source folds and
  layers conversion weighting on top so the loop closes across all inputs.
- **Attribute cross-referencing (FR-LEARN-4):** when one input implies an
  attribute value (e.g. a resume says "8 years Python", a form answer says
  "remote-only"), propose it. **Non-integral** attributes auto-apply; **integral**
  attributes route through the core confirmation gate (FR-FB-3) and are held until
  the user confirms — never silently committed.

State lives on the immutable ``LearningModel`` (pure-functional updates), exactly
like Phase 1. The LLM is reserved for human-readable summaries, never the hot path
(FR-LEARN-7).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute, AttributeStore
from applicant.core.entities.learning_model import LearningModel
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.rules.confirmation_gate import ensure_change_allowed, requires_confirmation
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


@dataclass(frozen=True)
class AttributeProposal:
    """A proposed attribute value derived by cross-referencing inputs (FR-LEARN-4).

    ``applied`` is True when the proposal auto-applied (non-integral); when the
    target attribute is integral it stays ``applied=False`` and
    ``needs_confirmation=True`` until the user confirms via the gate (FR-FB-3).
    """

    name: str
    value: str
    source: str  # which input implied it (e.g. "resume", "screening_answer")
    is_integral: bool
    applied: bool
    needs_confirmation: bool


class AdvancedLearningService:
    """Phase-4 learning depth layered over the cheap Phase 1 base.

    Composes (does not subclass) ``LearningService`` so the stable Phase 1 folds
    stay authoritative and this module only adds conversion + cross-reference depth.
    """

    def __init__(self, base, storage=None) -> None:
        self._base = base
        self._storage = storage

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
        self, model: LearningModel, application: Application, outcomes: list[OutcomeEvent]
    ) -> LearningModel:
        """Fold a confirmed conversion's role signature into the campaign model.

        No-op (returns the model unchanged) unless the application is a true
        conversion, so a bare approval without submission never moves the needle
        (the loop only closes on real outcomes — FR-LEARN-2).
        """
        if not self.is_conversion(application, outcomes):
            return model
        signature = dict(model.converting_role_signature)
        for feature in self._role_features(application):
            signature[feature] = signature.get(feature, 0.0) + _CONVERSION_WEIGHT
        return replace(model, converting_role_signature=signature)

    def conversion_alignment(self, model: LearningModel, application: Application) -> float:
        """Cheap similarity of a candidate posting's role features to converters.

        Used to bias scoring/selection toward what actually converts (FR-LEARN-5);
        0.0 when nothing has converted yet (cold start).
        """
        sig = model.converting_role_signature
        if not sig:
            return 0.0
        feats = self._role_features(application)
        hit = sum(sig.get(f, 0.0) for f in feats)
        total = sum(sig.values()) or 1.0
        return hit / total

    @staticmethod
    def _role_features(application: Application) -> list[str]:
        """Cheap, deterministic role-signature features (no LLM, FR-LEARN-7)."""
        feats: list[str] = []
        if application.role_name:
            feats.append(f"role:{application.role_name.strip().lower()}")
        if application.work_mode:
            feats.append(f"work_mode:{application.work_mode.strip().lower()}")
        return feats

    # === cross-input learning (FR-LEARN-3) ================================
    def fold_decision(
        self, model: LearningModel, *, approved: bool, features: dict | None = None
    ) -> LearningModel:
        """Fold an approve/decline signal (delegates to the stable Phase 1 fold)."""
        return self._base.record_decision(model, approved=approved, features=features)

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
        Integral attributes route through ``ensure_change_allowed`` (FR-FB-3): if
        the user has not confirmed, the value is **not** committed and the proposal
        is returned with ``needs_confirmation=True`` (never silently committed).

        Returns the (possibly updated) store and the proposal record so callers can
        surface pending confirmations in the UI.
        """
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
            )

        # Either non-integral (auto-apply) or integral-and-confirmed: gate must pass.
        ensure_change_allowed(is_integral=is_integral, user_confirmed=user_confirmed)

        existing = store.find(name)
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
        )


def _synth_attribute_id():
    from applicant.core.ids import AttributeId, new_id

    return AttributeId(new_id())
