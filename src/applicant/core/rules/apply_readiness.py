"""Required-to-apply readiness — the minimum the agent needs to autonomously apply.

The onboarding form requires virtually nothing; the agent gathers the data it NEEDS
over time (chat, résumé parse, learning). But autonomous *applying* (discovery →
apply) is HARD-GATED: it cannot proceed until the minimum essentials exist. This
module is the single source of truth for that essentials set, kept pure so both the
gate (``SetupService.is_automated_work_allowed``) and the "what's still missing"
surface (setup-status + chat) compute it the same way from REAL campaign data.

The essentials (the agent literally cannot apply without them):

* **target roles / titles** — without these there is nothing to search or apply for;
* **work mode** (remote / hybrid / on-site) — scopes which postings even qualify;
* **locations** — where the user will work (a remote-only user may state "remote");
* **salary floor** — the floor below which an application is not worth filing;
* **key skills / keywords** — the terms that drive discovery + matching;
* **a résumé** — the document attached to every application and the seed of the
  attribute cloud.

"What's missing" is NEVER fabricated: each item is derived from the campaign's real
criteria + whether a résumé is actually present. When the set is complete the gate
opens and the loop may run; everything else keeps being learned later.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplyReadiness:
    """Computed readiness snapshot for the required-to-apply set.

    ``ready`` is True only when ``missing`` is empty. ``missing`` holds the plain,
    user-facing labels of the still-absent essentials (stable order); ``reason`` is a
    one-line, white-labeled explanation suitable for the front door + chat.
    """

    ready: bool
    missing: tuple[str, ...]
    reason: str


#: Plain, user-facing labels for each essential (no FR-/NFR- jargon).
LABEL_TARGET_ROLES = "target roles"
LABEL_WORK_MODE = "work mode (remote / hybrid / on-site)"
LABEL_LOCATIONS = "locations"
LABEL_SALARY_FLOOR = "salary floor"
LABEL_KEY_SKILLS = "key skills"
LABEL_RESUME = "a résumé"


def evaluate_apply_readiness(
    *,
    has_titles: bool,
    has_work_modes: bool,
    has_locations: bool,
    has_salary_floor: bool,
    has_keywords: bool,
    has_resume: bool,
) -> ApplyReadiness:
    """Compute the required-to-apply readiness from real campaign signals.

    Every argument is a plain truthiness flag derived by the caller from genuine
    campaign data (criteria fields + résumé presence) — this rule fabricates nothing.
    A title or skill set may also be expressed as a free-text criteria statement; the
    caller folds that into ``has_titles`` / ``has_keywords`` before calling.
    """
    missing: list[str] = []
    if not has_titles:
        missing.append(LABEL_TARGET_ROLES)
    if not has_work_modes:
        missing.append(LABEL_WORK_MODE)
    if not has_locations:
        missing.append(LABEL_LOCATIONS)
    if not has_salary_floor:
        missing.append(LABEL_SALARY_FLOOR)
    if not has_keywords:
        missing.append(LABEL_KEY_SKILLS)
    if not has_resume:
        missing.append(LABEL_RESUME)

    if not missing:
        return ApplyReadiness(
            ready=True,
            missing=(),
            reason="Ready to start applying — every essential is in place.",
        )
    return ApplyReadiness(
        ready=False,
        missing=tuple(missing),
        reason=(
            "To start applying, I still need: " + ", ".join(missing) + "."
        ),
    )
