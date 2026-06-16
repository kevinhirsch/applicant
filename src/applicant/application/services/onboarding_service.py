"""OnboardingService — Workday-ready resumable intake (FR-ONBOARD-1/2/3).

Implements the :class:`OnboardingPort`. The comprehensive intake (identity,
work-auth, location/work-mode, target roles, compensation, dated work history,
education, references, certifications, key attributes, explicit EEO answers, base
resume, initial campaign criteria — see docs/onboarding-intake.md) is persisted to
the ``onboarding_profiles`` row (via the app-config store fallback in tests) so it
is resumable across steps (FR-ONBOARD-2).

The completion flag gates automated work (FR-ONBOARD-2): ``complete`` only sets it
once every required section is present.

On base-resume upload (FR-ONBOARD-3) the resume is parsed to bootstrap the
per-campaign attribute cloud (FR-ATTR-1) and reconciled with the interview
answers: non-integral parsed values auto-apply; integral conflicts are surfaced for
explicit confirmation (FR-FB-3). EEO answers are stored sensitive and default to
"decline to self-identify" (FR-ATTR-6).
"""

from __future__ import annotations

from typing import Any

from applicant.core.entities.attribute import Attribute
from applicant.core.ids import AttributeId, CampaignId, new_id
from applicant.core.rules.sensitive_fields import (
    DECLINE_TO_SELF_IDENTIFY,
    is_sensitive_field,
)
from applicant.observability.logging import get_logger
from applicant.ports.driving.onboarding import (
    REQUIRED_SECTIONS,
    IntakeSection,
    OnboardingState,
    ReconciliationConflict,
    ReconciliationResult,
)

log = get_logger(__name__)

#: app-config key prefix for resumable onboarding state (per campaign).
_KEY_PREFIX = "onboarding."

#: EEO fields are always stored sensitive (FR-ATTR-6); default decline.
_EEO_FIELDS = ("race_ethnicity", "gender", "veteran_status", "disability_status")

#: Attributes considered integral (core identity/history) — changing them needs
#: explicit confirmation (FR-FB-3).
_INTEGRAL_ATTRS = frozenset(
    {"full_name", "email", "phone"}
)


class OnboardingService:
    """Implements the OnboardingPort with persistent, resumable state."""

    def __init__(self, *, storage, config_store, resume_parser) -> None:
        self._storage = storage
        self._config = config_store
        self._parser = resume_parser

    # --- persistence -------------------------------------------------------
    def _key(self, campaign_id: str) -> str:
        return f"{_KEY_PREFIX}{campaign_id}"

    def _load(self, campaign_id: str) -> dict[str, Any]:
        rec = self._config.get(self._key(campaign_id))
        if not rec:
            return {"intake": {}, "sections_complete": [], "complete": False}
        rec.setdefault("intake", {})
        rec.setdefault("sections_complete", [])
        rec.setdefault("complete", False)
        return rec

    def _store(self, campaign_id: str, rec: dict[str, Any]) -> None:
        self._config.set(self._key(campaign_id), rec)

    def _to_state(self, campaign_id: str, rec: dict[str, Any]) -> OnboardingState:
        done = set(rec.get("sections_complete", []))
        missing = [s.value for s in REQUIRED_SECTIONS if s.value not in done]
        return OnboardingState(
            campaign_id=campaign_id,
            complete=bool(rec.get("complete", False)),
            sections_complete=sorted(done),
            missing_sections=missing,
            intake=rec.get("intake", {}),
        )

    # --- port methods ------------------------------------------------------
    def get_state(self, campaign_id: str) -> OnboardingState:
        return self._to_state(campaign_id, self._load(campaign_id))

    def save_section(
        self, campaign_id: str, section: IntakeSection, data: dict[str, Any]
    ) -> OnboardingState:
        rec = self._load(campaign_id)
        intake = dict(rec.get("intake", {}))

        if section is IntakeSection.EEO:
            data = self._normalize_eeo(data)

        intake[section.value] = data
        rec["intake"] = intake

        done = set(rec.get("sections_complete", []))
        if self._section_filled(data):
            done.add(section.value)
        else:
            done.discard(section.value)
        rec["sections_complete"] = sorted(done)
        # Any edit re-opens the completion flag until re-confirmed.
        rec["complete"] = False
        self._store(campaign_id, rec)

        # Persist EEO answers into the attribute cloud immediately (sensitive).
        if section is IntakeSection.EEO:
            self._store_eeo_attributes(campaign_id, data)

        log.info("onboarding_section_saved", campaign_id=campaign_id, section=section.value)
        return self._to_state(campaign_id, rec)

    def complete(self, campaign_id: str) -> OnboardingState:
        rec = self._load(campaign_id)
        done = set(rec.get("sections_complete", []))
        missing = [s.value for s in REQUIRED_SECTIONS if s.value not in done]
        if missing:
            rec["complete"] = False
            self._store(campaign_id, rec)
            log.info("onboarding_incomplete", campaign_id=campaign_id, missing=missing)
            return self._to_state(campaign_id, rec)
        rec["complete"] = True
        self._store(campaign_id, rec)
        log.info("onboarding_complete", campaign_id=campaign_id)
        return self._to_state(campaign_id, rec)

    def is_complete(self, campaign_id: str) -> bool:
        return bool(self._load(campaign_id).get("complete", False))

    # --- base resume parse + reconciliation (FR-ONBOARD-3) -----------------
    def ingest_base_resume(self, campaign_id: str, document_path: str) -> ReconciliationResult:
        parsed = self._parser.parse(document_path)
        rec = self._load(campaign_id)
        intake = dict(rec.get("intake", {}))
        identity = dict(intake.get(IntakeSection.IDENTITY.value, {}))

        auto_applied: list[str] = []
        conflicts: list[ReconciliationConflict] = []

        # Reconcile identity scalars.
        scalar_map = {
            "full_name": parsed.full_name,
            "email": parsed.email,
            "phone": parsed.phone,
        }
        for name, parsed_val in scalar_map.items():
            if not parsed_val:
                continue
            interview_val = str(identity.get(name, "") or "")
            integral = name in _INTEGRAL_ATTRS
            if interview_val and interview_val != parsed_val:
                if integral:
                    # FR-FB-3: integral conflict requires explicit confirmation.
                    conflicts.append(
                        ReconciliationConflict(
                            attribute=name,
                            interview_value=interview_val,
                            parsed_value=parsed_val,
                        )
                    )
                    continue
                # non-integral: auto-apply
                identity[name] = parsed_val
                auto_applied.append(name)
            elif not interview_val:
                identity[name] = parsed_val
                auto_applied.append(name)
                self._upsert_attribute(campaign_id, name, parsed_val, is_integral=integral)

        intake[IntakeSection.IDENTITY.value] = identity

        # Bootstrap the attribute cloud from non-integral parsed data (FR-ATTR-1).
        for skill in parsed.skills:
            self._upsert_attribute(campaign_id, f"skill:{skill}", skill, is_integral=False)
            auto_applied.append(f"skill:{skill}")
        for i, w in enumerate(parsed.work_history):
            val = f"{w.title} at {w.company} ({w.start_date} - {w.end_date})".strip()
            self._upsert_attribute(campaign_id, f"work_history:{i}", val, is_integral=False)
        for i, e in enumerate(parsed.education):
            val = f"{e.degree} {e.institution} ({e.start_year}-{e.end_year})".strip()
            self._upsert_attribute(campaign_id, f"education:{i}", val, is_integral=False)

        # Record the parsed resume + detected fonts for the font/conversion steps.
        intake[IntakeSection.BASE_RESUME.value] = {
            "document_path": document_path,
            "detected_fonts": list(parsed.detected_fonts),
            "parsed": True,
        }
        rec["intake"] = intake
        done = set(rec.get("sections_complete", []))
        done.add(IntakeSection.BASE_RESUME.value)
        rec["sections_complete"] = sorted(done)
        self._store(campaign_id, rec)

        attrs = self._storage.attributes.list_for_campaign(CampaignId(campaign_id))
        log.info(
            "base_resume_ingested",
            campaign_id=campaign_id,
            auto_applied=len(auto_applied),
            conflicts=len(conflicts),
        )
        return ReconciliationResult(
            auto_applied=auto_applied,
            conflicts=conflicts,
            attribute_count=len(attrs),
        )

    def confirm_conflict(self, campaign_id: str, attribute: str, value: str) -> None:
        """Apply a previously-flagged integral change after explicit confirmation.

        The confirmation gate (FR-FB-3) is satisfied by the user calling this with
        the chosen value; we then upsert the integral attribute and identity field.
        """
        rec = self._load(campaign_id)
        intake = dict(rec.get("intake", {}))
        identity = dict(intake.get(IntakeSection.IDENTITY.value, {}))
        identity[attribute] = value
        intake[IntakeSection.IDENTITY.value] = identity
        rec["intake"] = intake
        self._store(campaign_id, rec)
        self._upsert_attribute(
            campaign_id, attribute, value, is_integral=attribute in _INTEGRAL_ATTRS
        )
        log.info("onboarding_conflict_confirmed", campaign_id=campaign_id, attribute=attribute)

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _section_filled(data: dict[str, Any]) -> bool:
        if not data:
            return False
        return any(v not in (None, "", [], {}) for v in data.values())

    def _normalize_eeo(self, data: dict[str, Any]) -> dict[str, Any]:
        """EEO defaults to decline; never AI-guessed (FR-ATTR-6)."""
        out: dict[str, Any] = {}
        for field_name in _EEO_FIELDS:
            val = data.get(field_name)
            out[field_name] = val if val else DECLINE_TO_SELF_IDENTIFY
        return out

    def _store_eeo_attributes(self, campaign_id: str, data: dict[str, Any]) -> None:
        for field_name, val in data.items():
            self._upsert_attribute(
                campaign_id,
                field_name,
                str(val),
                is_integral=False,
                is_sensitive=True,
            )

    def _upsert_attribute(
        self,
        campaign_id: str,
        name: str,
        value: str,
        *,
        is_integral: bool = False,
        is_sensitive: bool | None = None,
    ) -> None:
        cid = CampaignId(campaign_id)
        if is_sensitive is None:
            is_sensitive = is_sensitive_field(name)
        existing = None
        for a in self._storage.attributes.list_for_campaign(cid):
            if a.name == name:
                existing = a
                break
        attr = Attribute(
            id=existing.id if existing else AttributeId(new_id()),
            campaign_id=cid,
            name=name,
            value=value,
            is_integral=is_integral,
            is_sensitive=is_sensitive,
        )
        self._storage.attributes.add(attr)
        self._storage.commit()
