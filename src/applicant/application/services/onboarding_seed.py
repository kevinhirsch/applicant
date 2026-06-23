"""Onboarding memory seed — remember the user from day one (FR-MIND-1/3/9/13).

When onboarding completes (profile saved + base résumé parsed) the agent should
not be cold-start: it should already hold a small, bounded set of curated
**memory** entries derived from the user's OWN data, and have the user's history
indexed into **recall** so "have I seen a role like this?" works on the first tick.

This module is the **pure derivation** layer: given the resumable onboarding intake
blob (see ``OnboardingService``), it produces

* a bounded list of :class:`MemoryEntry` — ``kind=user`` for stated style/preferences,
  ``kind=environment`` for durable target facts (titles, salary floor, work mode), and
* a bounded list of ``(run_id, text)`` recall items — the parsed prior roles +
  target profile — to feed ``RecallIndex.index``.

Hard rules it enforces (mirroring the spec):

* **Truthfulness (FR-MIND-11 / FR-RESUME-2).** It derives ONLY from the user's real
  intake fields; it never invents a preference. A derived line that trips
  ``claims_authority`` (advisory text masquerading as a grant) is dropped — seeded
  memory is context, never a gate.
* **Bounded (FR-MIND-13).** Each line is filtered through the core ``is_save_worthy``
  policy and the whole set is capped (``_MAX_SEED_ENTRIES``) so the snapshot never
  becomes a token furnace.

No IO and no engine deps beyond the core policy + the memory/recall value types, so
it unit-tests in isolation and respects hexagonal layering.
"""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.rules.agent_memory import claims_authority, is_save_worthy
from applicant.ports.driven.memory_store import (
    KIND_ENVIRONMENT,
    KIND_USER,
    SCOPE_CAMPAIGN,
    MemoryEntry,
)
from applicant.ports.driving.onboarding import IntakeSection

#: Hard cap on how many curated lines one onboarding may seed (FR-MIND-13). Keeps the
#: day-one snapshot small; the curation loop grows memory from real runs afterwards.
_MAX_SEED_ENTRIES = 12
#: Hard cap on recall items seeded from history (prior roles + the profile line).
_MAX_RECALL_ITEMS = 16


@dataclass(frozen=True)
class SeedPlan:
    """The bounded, derived seed for one completed onboarding (pure output).

    ``memory_entries`` are curated lines (already save-worthy + advisory-only);
    ``recall_items`` are ``(run_id, text)`` pairs to feed ``RecallIndex.index``.
    Empty when the intake carries no usable first-party data — the caller then
    no-ops, so absent onboarding data leaves behavior byte-identical.
    """

    memory_entries: tuple[MemoryEntry, ...] = ()
    recall_items: tuple[tuple[str, str], ...] = ()


def _clean(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _join(values: object) -> str:
    """Render a scalar or a list/tuple of scalars as a comma-joined string."""
    if isinstance(values, (list, tuple)):
        parts = [_clean(v) for v in values]
        return ", ".join(p for p in parts if p)
    return _clean(values)


def _section(intake: dict, section: IntakeSection) -> dict:
    data = intake.get(section.value)
    return data if isinstance(data, dict) else {}


def _candidate_memory_lines(intake: dict) -> list[tuple[str, str]]:
    """Derive ``(kind, text)`` candidate curated lines from the user's REAL intake.

    Only fields the user actually supplied yield a line; nothing is invented. The
    caller filters these through the save-worthiness + advisory-only gates.
    """
    out: list[tuple[str, str]] = []

    # --- durable target facts (environment) -------------------------------
    roles = _section(intake, IntakeSection.TARGET_ROLES)
    criteria = _section(intake, IntakeSection.CAMPAIGN_CRITERIA)
    titles = _join(roles.get("titles") or criteria.get("titles"))
    if titles:
        out.append((KIND_ENVIRONMENT, f"Targets roles like: {titles}."))

    location = _section(intake, IntakeSection.LOCATION)
    work_mode = _join(
        location.get("work_modes")
        or location.get("work_mode")
        or criteria.get("work_modes")
    )
    locations = _join(location.get("locations") or criteria.get("locations"))
    if work_mode and locations:
        out.append(
            (KIND_ENVIRONMENT, f"Prefers {work_mode} work; locations: {locations}.")
        )
    elif work_mode:
        out.append((KIND_ENVIRONMENT, f"Prefers {work_mode} work."))
    elif locations:
        out.append((KIND_ENVIRONMENT, f"Targets locations: {locations}."))

    comp = _section(intake, IntakeSection.COMPENSATION)
    salary_floor = _clean(
        comp.get("salary_floor")
        or comp.get("minimum_salary")
        or criteria.get("salary_floor")
    )
    if salary_floor:
        out.append(
            (KIND_ENVIRONMENT, f"Compensation floor stated by the user: {salary_floor}.")
        )

    work_auth = _section(intake, IntakeSection.WORK_AUTHORIZATION)
    auth = _join(work_auth.get("status") or work_auth.get("work_authorization"))
    if auth:
        out.append((KIND_ENVIRONMENT, f"Work authorization: {auth}."))

    skills = _section(intake, IntakeSection.KEY_ATTRIBUTES)
    key_skills = _join(skills.get("technical_skills") or skills.get("skills"))
    if key_skills:
        out.append((KIND_ENVIRONMENT, f"Key skills the user listed: {key_skills}."))

    # --- the user's own style / preferences (user) ------------------------
    # Free-text the user wrote about how they want to be represented / written to.
    for src in (roles, skills, criteria):
        for field_name in (
            "communication_style",
            "communication_preferences",
            "tone",
            "voice",
            "writing_style",
            "preferences",
            "notes",
        ):
            val = _clean(src.get(field_name))
            if val:
                out.append((KIND_USER, f"User's stated preference: {val}"))

    return out


def _recall_items(campaign_id: str, intake: dict) -> list[tuple[str, str]]:
    """Derive ``(run_id, text)`` recall items from the user's history (FR-MIND-3).

    Indexes the parsed prior roles and a target-profile line so the agent can answer
    "have I seen a role like this?" from the first tick. The run ids are stable +
    namespaced to this campaign so a re-seed overwrites rather than duplicates.
    """
    items: list[tuple[str, str]] = []

    work = _section(intake, IntakeSection.WORK_HISTORY)
    title = _clean(work.get("title"))
    company = _clean(work.get("company"))
    if title or company:
        bits = [b for b in (title, company, _clean(work.get("location"))) if b]
        dates = ""
        if work.get("start_date") or work.get("end_date"):
            dates = f" ({_clean(work.get('start_date'))}-{_clean(work.get('end_date'))})"
        items.append(
            (
                f"onboarding:{campaign_id}:work:0",
                "Prior role: " + " at ".join(bits[:2]) + dates,
            )
        )

    # A single profile line so semantic recall has the target shape from day one.
    roles = _section(intake, IntakeSection.TARGET_ROLES)
    criteria = _section(intake, IntakeSection.CAMPAIGN_CRITERIA)
    titles = _join(roles.get("titles") or criteria.get("titles"))
    skills = _section(intake, IntakeSection.KEY_ATTRIBUTES)
    key_skills = _join(skills.get("technical_skills") or skills.get("skills"))
    profile_bits = [b for b in (titles, key_skills) if b]
    if profile_bits:
        items.append(
            (
                f"onboarding:{campaign_id}:profile",
                "Target profile — " + "; ".join(profile_bits),
            )
        )

    return items[:_MAX_RECALL_ITEMS]


def build_seed_plan(campaign_id: str, intake: dict) -> SeedPlan:
    """Derive the bounded, advisory-only day-one seed for a completed onboarding.

    Pure: same intake in ⇒ same plan out. Drops any line that is not save-worthy or
    that trips ``claims_authority`` (seeded memory is context, never authorization —
    FR-MIND-11). Returns an empty plan when there is no usable first-party data.
    """
    if not isinstance(intake, dict) or not intake:
        return SeedPlan()

    entries: list[MemoryEntry] = []
    seen: set[str] = set()
    for kind, text in _candidate_memory_lines(intake):
        line = text.strip()
        if line in seen:
            continue
        # Bounded + curated (FR-MIND-13) and advisory-only (FR-MIND-11): a derived
        # line that claims a safety-gated authority is dropped, never seeded.
        if not is_save_worthy(line) or claims_authority(line):
            continue
        seen.add(line)
        entries.append(
            MemoryEntry(
                text=line,
                kind=kind,
                scope=SCOPE_CAMPAIGN,
                campaign_id=campaign_id,
            )
        )
        if len(entries) >= _MAX_SEED_ENTRIES:
            break

    return SeedPlan(
        memory_entries=tuple(entries),
        recall_items=tuple(_recall_items(campaign_id, intake)),
    )
