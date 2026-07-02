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
from applicant.core.rules.apply_readiness import (
    ApplyReadiness,
    evaluate_apply_readiness,
)
from applicant.core.rules.ats_parseability import check_render_parseability
from applicant.core.rules.field_normalization import values_match
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

#: The resume parse extracts canonical identity scalars; the "About you" intake
#: form (the wizard) renders them under these field names. Prefilling the intake
#: under the FORM names is what lets the resume-first flow populate the editable
#: fields the user then corrects (FR-ONBOARD-3). ``email``/``phone`` share the same
#: name on both sides; the legal name maps to the form's ``full_legal_name`` input.
_IDENTITY_FORM_FIELD = {
    "full_name": "full_legal_name",
    "email": "email",
    "phone": "phone",
}


class OnboardingService:
    """Implements the OnboardingPort with persistent, resumable state."""

    def __init__(self, *, storage, config_store, resume_parser) -> None:
        self._storage = storage
        self._config = config_store
        self._parser = resume_parser
        # #6: bridges into the engine, wired additively (set_* below) to avoid a
        # construction cycle. When present, onboarding criteria flow into
        # CriteriaService and typed intake sections upsert into the attribute cloud.
        self._criteria_service = None
        self._attribute_cloud_service = None
        # FR-MIND-1/3: the agent-memory substrate (curated memory + recall). Wired
        # additively (set_* below) and OPTIONAL — when absent, completion seeds nothing
        # and behavior is byte-identical (the hermetic lane / no-substrate boot).
        self._agent_memory = None

    def set_criteria_service(self, criteria_service) -> None:
        """Wire the CriteriaService so CAMPAIGN_CRITERIA intake reaches the engine (#6)."""
        self._criteria_service = criteria_service

    def set_attribute_cloud_service(self, attribute_cloud_service) -> None:
        """Wire the AttributeCloudService so typed intake upserts attributes (#6)."""
        self._attribute_cloud_service = attribute_cloud_service

    def set_agent_memory(self, agent_memory) -> None:
        """Wire the agent-memory substrate so completion can seed memory/recall (FR-MIND-1/3).

        ``agent_memory`` is the container's ``AgentMemory`` bundle (``.memory`` /
        ``.recall``). Optional + additive: when unset, ``complete`` seeds nothing.
        """
        self._agent_memory = agent_memory

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

        # #6: bridge the onboarding intake into the engine so criteria + attributes are
        # not stranded in the onboarding blob (the loop reads them via get_criteria /
        # the attribute cloud). Best-effort: a bridge hiccup never breaks intake save.
        self._bridge_section_to_engine(campaign_id, section, data)

        log.info("onboarding_section_saved", campaign_id=campaign_id, section=section.value)
        return self._to_state(campaign_id, rec)

    # --- #6: onboarding -> engine bridge ----------------------------------
    def _bridge_section_to_engine(
        self, campaign_id: str, section: IntakeSection, data: dict[str, Any]
    ) -> None:
        """Flow saved intake into CriteriaService / the attribute cloud (#6)."""
        try:
            if section is IntakeSection.CAMPAIGN_CRITERIA:
                self._bridge_criteria(campaign_id, data)
            else:
                self._bridge_attributes(campaign_id, section, data)
        except Exception:  # pragma: no cover - never let the bridge break intake save
            log.warning(
                "onboarding_bridge_failed", campaign_id=campaign_id, section=section.value
            )

    def _bridge_criteria(self, campaign_id: str, data: dict[str, Any]) -> None:
        """CAMPAIGN_CRITERIA intake -> CriteriaService.edit_criteria(confirm=True) (#6)."""
        if self._criteria_service is None:
            return
        changes: dict[str, Any] = {}
        for key in ("titles", "locations", "work_modes", "keywords"):
            val = data.get(key)
            if val:
                changes[key] = list(val) if not isinstance(val, list) else val
        if data.get("salary_floor") not in (None, ""):
            changes["salary_floor"] = data["salary_floor"]
        if data.get("human_readable"):
            changes["human_readable"] = data["human_readable"]
        if not changes:
            return
        # confirm=True: onboarding is the user's own explicit intake, so integral
        # criteria fields (titles/locations/salary_floor) are user-confirmed (FR-FB-3).
        self._criteria_service.edit_criteria(
            CampaignId(campaign_id), changes=changes, confirm=True
        )

    def _bridge_attributes(
        self, campaign_id: str, section: IntakeSection, data: dict[str, Any]
    ) -> None:
        """Typed intake section -> attribute-cloud upserts (#6)."""
        if self._attribute_cloud_service is None:
            return
        integral_sections = {IntakeSection.IDENTITY}
        is_integral = section in integral_sections
        for name, value in data.items():
            if value in (None, "") or isinstance(value, (dict, list)):
                continue
            # confirm=True: onboarding is the user's explicit, first-party data entry.
            self._attribute_cloud_service.upsert(
                CampaignId(campaign_id),
                str(name),
                str(value),
                is_integral=is_integral,
                confirm=True,
            )

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
        # FR-ONBOARD-2: persist the completion record to the dedicated
        # ``onboarding_profiles`` row (not only the app-config blob) so onboarding
        # state lives in its own first-class table and survives as a queryable record.
        self._persist_profile(campaign_id, rec, complete=True)
        # FR-MIND-1/3: remember the user from day one. Seed a bounded set of curated
        # memory entries + index their history into recall, ONCE per campaign, from the
        # user's OWN intake/résumé. Idempotent (guarded by ``memory_seeded`` in rec);
        # no-op when no substrate is wired; never breaks the completion gate.
        self._seed_agent_memory(campaign_id, rec)
        log.info("onboarding_complete", campaign_id=campaign_id)
        return self._to_state(campaign_id, rec)

    def _seed_agent_memory(self, campaign_id: str, rec: dict[str, Any]) -> None:
        """One-time, idempotent day-one seed of curated memory + recall (FR-MIND-1/3).

        Derives a bounded, advisory-only seed from the user's REAL intake/résumé and
        applies it through the existing memory store + recall index. Treated like the
        rest of onboarding — the user's own first-party data — so non-integral entries
        apply directly (matching the ``confirm=True`` bridge posture, FR-FB-3); the
        derivation already drops any authority-claiming line (FR-MIND-11). Guarded so a
        re-run of ``complete`` never duplicates. Best-effort: a hiccup never breaks the
        completion gate, and an absent substrate is a clean no-op.
        """
        if self._agent_memory is None:
            return
        if rec.get("memory_seeded"):
            return
        try:
            from applicant.application.services.onboarding_seed import build_seed_plan

            plan = build_seed_plan(campaign_id, dict(rec.get("intake", {})))
            memory = getattr(self._agent_memory, "memory", None)
            recall = getattr(self._agent_memory, "recall", None)
            seeded_mem = 0
            if memory is not None:
                for entry in plan.memory_entries:
                    memory.add(entry)
                    seeded_mem += 1
            seeded_recall = 0
            if recall is not None:
                for run_id, text in plan.recall_items:
                    try:
                        recall.index(run_id, text, campaign_id)
                        seeded_recall += 1
                    except Exception:  # recall is advisory — degrade, never break
                        log.debug("onboarding_seed_recall_failed", campaign_id=campaign_id)
            # Mark seeded only after a successful pass so a transient failure can retry
            # on a later ``complete`` rather than silently leaving the agent cold-start.
            rec["memory_seeded"] = True
            self._store(campaign_id, rec)
            log.info(
                "onboarding_memory_seeded",
                campaign_id=campaign_id,
                memory_entries=seeded_mem,
                recall_items=seeded_recall,
            )
        except Exception:  # pragma: no cover - never let seeding break the gate
            log.warning("onboarding_memory_seed_failed", campaign_id=campaign_id)

    def _persist_profile(self, campaign_id: str, rec: dict[str, Any], *, complete: bool) -> None:
        """Write the onboarding completion record to ``onboarding_profiles``."""
        repo = getattr(self._storage, "onboarding_profiles", None)
        if repo is None:
            return
        from applicant.core.entities.onboarding_profile import OnboardingProfile
        from applicant.core.ids import OnboardingProfileId

        cid = CampaignId(campaign_id)
        try:
            existing = repo.get_for_campaign(cid)
            profile = OnboardingProfile(
                id=existing.id if existing else OnboardingProfileId(new_id()),
                campaign_id=cid,
                completion_flag=complete,
                wizard_state={"sections_complete": rec.get("sections_complete", [])},
                intake=dict(rec.get("intake", {})),
            )
            repo.add(profile)
            self._storage.commit()
        except Exception:  # pragma: no cover - never let persistence break the gate
            log.warning("onboarding_profile_persist_failed", campaign_id=campaign_id)

    def is_complete(self, campaign_id: str) -> bool:
        return bool(self._load(campaign_id).get("complete", False))

    # --- required-to-apply readiness (the hard gate on autonomous applying) ---
    def has_base_resume(self, campaign_id: str) -> bool:
        """True once a base résumé has actually been ingested for the campaign.

        Derived from REAL state — the parsed ``BASE_RESUME`` intake section (set only
        by ``ingest_base_resume``) — never fabricated. The résumé is one of the
        required-to-apply essentials: it is attached to every application and seeds
        the attribute cloud.
        """
        rec = self._load(campaign_id)
        section = (rec.get("intake", {}) or {}).get(IntakeSection.BASE_RESUME.value) or {}
        return bool(section.get("document_path") or section.get("parsed"))

    def apply_readiness(self, campaign_id: str) -> ApplyReadiness:
        """Compute the required-to-apply readiness for the campaign (single source).

        This is THE check the automated-work gate and the setup-status surface both
        use, so "blocked / what's missing" is computed once from real campaign data:
        the per-campaign search criteria (titles, work mode, locations, salary floor,
        key skills/keywords) plus whether a base résumé is present. A criteria set
        expressed only as a free-text statement still counts toward target-roles /
        key-skills, so a chat-only setup can satisfy the gate without the typed forms.

        Nothing here is invented: every signal is read back from persisted state.
        """
        titles = locations = work_modes = keywords = ()
        salary_floor = None
        human_readable = ""
        if self._criteria_service is not None:
            try:
                crit = self._criteria_service.get_criteria(CampaignId(campaign_id))
                titles = tuple(crit.titles or ())
                locations = tuple(crit.locations or ())
                work_modes = tuple(crit.work_modes or ())
                keywords = tuple(crit.keywords or ())
                salary_floor = crit.salary_floor
                human_readable = crit.human_readable or ""
            except Exception:  # pragma: no cover - never let a read break the gate
                log.warning("apply_readiness_criteria_read_failed", campaign_id=campaign_id)
        has_statement = bool(human_readable.strip())
        return evaluate_apply_readiness(
            # A free-text criteria statement stands in for typed titles/skills: the
            # user described the search in their own words.
            has_titles=bool(titles) or has_statement,
            has_work_modes=bool(work_modes),
            has_locations=bool(locations),
            has_salary_floor=salary_floor is not None,
            has_keywords=bool(keywords) or has_statement,
            has_resume=self.has_base_resume(campaign_id),
        )

    def is_ready_to_apply(self, campaign_id: str) -> bool:
        """True only when the required-to-apply essentials are all present."""
        return self.apply_readiness(campaign_id).ready

    # --- base resume parse + reconciliation (FR-ONBOARD-3) -----------------
    def ingest_base_resume(self, campaign_id: str, document_path: str) -> ReconciliationResult:
        parsed = self._parser.parse(document_path)
        rec = self._load(campaign_id)
        intake = dict(rec.get("intake", {}))
        identity = dict(intake.get(IntakeSection.IDENTITY.value, {}))

        auto_applied: list[str] = []
        conflicts: list[ReconciliationConflict] = []

        # Reconcile identity scalars. Uploading the resume FIRST is the intended
        # entry point: when the user has not yet typed a value we PREFILL the
        # editable intake field from the parse (resume-first); when they already
        # typed one we only surface an integral *conflict* if the values genuinely
        # differ — format-only differences (a reformatted phone, a case change) are
        # NOT flagged (FR-ONBOARD-3, FR-FB-3).
        scalar_map = {
            "full_name": parsed.full_name,
            "email": parsed.email,
            "phone": parsed.phone,
        }
        for name, parsed_val in scalar_map.items():
            if not parsed_val:
                continue
            # The intake form renders identity scalars under its own field names;
            # read/write under that name so prefill populates the form, but also
            # honour a value stored under the canonical name (e.g. an attribute-cloud
            # bridge or an older record) so an existing answer is still reconciled.
            form_field = _IDENTITY_FORM_FIELD.get(name, name)
            interview_val = str(
                identity.get(form_field, "") or identity.get(name, "") or ""
            )
            integral = name in _INTEGRAL_ATTRS
            same = bool(interview_val) and values_match(name, interview_val, parsed_val)
            if interview_val and not same:
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
                identity[form_field] = parsed_val
                auto_applied.append(name)
            elif not interview_val:
                # Resume-first prefill: populate the editable field + seed the cloud.
                identity[form_field] = parsed_val
                auto_applied.append(name)
                self._upsert_attribute(campaign_id, name, parsed_val, is_integral=integral)

        intake[IntakeSection.IDENTITY.value] = identity

        # Resume-first prefill of the structured intake sections (FR-ONBOARD-3): the
        # parse seeds the editable work-history / education / skills forms so the user
        # corrects parsing mistakes instead of typing everything by hand. Only fill a
        # section the user hasn't already entered, so re-uploading never clobbers edits.
        self._prefill_sections_from_parse(intake, parsed)

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

        # Record the parsed resume + detected fonts for the font/conversion steps, and
        # keep the raw résumé text as ground truth for the fabrication guard: the
        # attribute cloud only captures parsed/structured fields (work-history
        # flattening can drop the achievement prose + its metrics), so the truthful
        # generators read this back via ``true_attribute_text`` (FR-RESUME-2).
        intake[IntakeSection.BASE_RESUME.value] = {
            "document_path": document_path,
            "detected_fonts": list(parsed.detected_fonts),
            "parsed": True,
            "raw_text": parsed.raw_text,
        }
        rec["intake"] = intake
        done = set(rec.get("sections_complete", []))
        done.add(IntakeSection.BASE_RESUME.value)
        rec["sections_complete"] = sorted(done)
        self._store(campaign_id, rec)

        attrs = self._storage.attributes.list_for_campaign(CampaignId(campaign_id))
        # Resume-health at upload (product-gaps #48 / activation backlog §7.5): reuse
        # the existing ats_parseability self-check (issue #370) — previously only
        # run on the GENERATED render right before submission — against the
        # UPLOADED resume's own extractable text, so a formatting problem (no
        # recoverable text layer, unreadable contact info, no recognizable section
        # headers) is an instant signal at the moment of upload rather than a
        # silent risk discovered only much later at submit time.
        health = check_render_parseability(parsed.raw_text)
        log.info(
            "base_resume_ingested",
            campaign_id=campaign_id,
            auto_applied=len(auto_applied),
            conflicts=len(conflicts),
            resume_parseable=health.parseable,
        )
        return ReconciliationResult(
            auto_applied=auto_applied,
            conflicts=conflicts,
            attribute_count=len(attrs),
            parseable=health.parseable,
            parseability_issues=list(health.issues),
        )

    def confirm_conflict(self, campaign_id: str, attribute: str, value: str) -> None:
        """Apply a previously-flagged integral change after explicit confirmation.

        The confirmation gate (FR-FB-3) is satisfied by the user calling this with
        the chosen value; we then upsert the integral attribute and identity field.
        """
        rec = self._load(campaign_id)
        intake = dict(rec.get("intake", {}))
        identity = dict(intake.get(IntakeSection.IDENTITY.value, {}))
        # Write under BOTH the intake form's field name (so the editable field
        # reflects the confirmed choice) and the canonical attribute name (so any
        # reader keyed on the canonical name sees it too); the conflict carries the
        # canonical name. Keeping both in sync avoids a stale value lingering.
        identity[attribute] = value
        identity[_IDENTITY_FORM_FIELD.get(attribute, attribute)] = value
        intake[IntakeSection.IDENTITY.value] = identity
        rec["intake"] = intake
        self._store(campaign_id, rec)
        self._upsert_attribute(
            campaign_id, attribute, value, is_integral=attribute in _INTEGRAL_ATTRS
        )
        log.info("onboarding_conflict_confirmed", campaign_id=campaign_id, attribute=attribute)

    # --- resume-first prefill (FR-ONBOARD-3) -------------------------------
    @staticmethod
    def _prefill_sections_from_parse(intake: dict[str, Any], parsed) -> None:
        """Seed the editable intake forms from the parsed resume (resume-first).

        Only sections the user hasn't already filled are prefilled, so re-uploading
        never clobbers a hand-typed value. The work-history / education forms in the
        wizard are REPEATABLE (a user can hold several jobs/degrees), so EVERY parsed
        role/degree is carried over as an ``entries`` list — not just the most recent
        one — otherwise a multi-job resume would still leave the user re-typing every
        earlier role by hand, undercutting the whole point of parsing the resume
        first. The wizard already understands this ``{"entries": [...]}`` shape (it's
        the same shape it saves back after the user edits), so this needs no
        front-door change. The user then corrects any parsing mistakes in-place and
        every field stays editable.
        """

        def _empty(section_key: str) -> bool:
            cur = intake.get(section_key) or {}
            return not any(v not in (None, "", [], {}) for v in cur.values())

        # Skills & strengths: the parsed skills prefill the "Technical skills" box.
        if parsed.skills and _empty(IntakeSection.KEY_ATTRIBUTES.value):
            existing = dict(intake.get(IntakeSection.KEY_ATTRIBUTES.value, {}))
            existing.setdefault("technical_skills", ", ".join(parsed.skills))
            intake[IntakeSection.KEY_ATTRIBUTES.value] = existing

        # Every parsed role -> the work-history form's `entries` list.
        if parsed.work_history and _empty(IntakeSection.WORK_HISTORY.value):
            intake[IntakeSection.WORK_HISTORY.value] = {
                "entries": [
                    {
                        "title": w.title,
                        "company": w.company,
                        "location": w.location,
                        "start_date": w.start_date,
                        "end_date": w.end_date,
                    }
                    for w in parsed.work_history
                ]
            }

        # Every parsed degree -> the education form's `entries` list.
        if parsed.education and _empty(IntakeSection.EDUCATION.value):
            intake[IntakeSection.EDUCATION.value] = {
                "entries": [
                    {
                        "degree": e.degree,
                        "institution": e.institution,
                        "start_year": e.start_year,
                        "end_year": e.end_year,
                    }
                    for e in parsed.education
                ]
            }

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
