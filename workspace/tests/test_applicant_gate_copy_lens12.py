"""Regression coverage for design-audit lens 12, finding #45
(``docs/design/audits/exhaustive2/12_help_selfexplain.md``, item 45):
a locked Applicant section's tooltip/toast used to say a generic
"``${title}`` unlocks once the Applicant engine is configured" no matter WHICH
gate was unmet, even though the engine already computes a specific per-section
``requirement`` (``workspace/src/applicant_features.py``'s ``requires``
predicates: ``onboarding_complete`` / ``llm_configured`` / ``channels_configured``).

Follows the convention of ``test_applicant_round2_wave2_firstlight.py``: every
fact is read from the actual static file content via ``pathlib`` (no browser,
no DOM, no real socket). Each assertion here was hand-verified to go red against
the pre-fix source (the generic-only ``reason`` line, no requirement map) and
green again once the fix (a ``requirement`` -> specific-reason map, consulted
before the generic fallback) is restored.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "workspace" / "static" / "app.js"


def _read() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _gating_block(src: str) -> str:
    """Slice out the `refreshApplicantFeatures` region (from the reasons map
    declaration through the end of the forEach loop body) so assertions can't
    accidentally match unrelated code elsewhere in this large file."""
    start = src.find("window.refreshApplicantFeatures = function")
    assert start != -1, "expected window.refreshApplicantFeatures to still exist"
    end = src.find("window._applicantFeaturesReady", start)
    assert end != -1, "expected the refreshApplicantFeatures block to end before _applicantFeaturesReady"
    # Include a little context before `start` too, since the reasons map is
    # declared just above the function assignment.
    lead_start = src.rfind("\n\n", 0, start)
    return src[lead_start:end]


def test_requirement_reason_map_declared():
    """A map from the engine's `requirement` values to specific, plain-language
    copy must exist (not just the generic fallback string)."""
    block = _gating_block(_read())
    assert "APPLICANT_REQUIREMENT_REASONS" in block, (
        "expected a requirement->reason map (e.g. APPLICANT_REQUIREMENT_REASONS) "
        "so the generic copy isn't the only option"
    )


def test_onboarding_complete_reason_is_specific_and_plain_language():
    block = _gating_block(_read())
    assert "onboarding_complete" in block
    assert "Finish setup to unlock this" in block


def test_llm_configured_reason_mentions_connecting_a_model():
    block = _gating_block(_read())
    assert "llm_configured" in block
    assert "Connect a model to unlock this" in block


def test_channels_configured_reason_mentions_notification_channel_in_settings():
    block = _gating_block(_read())
    assert "channels_configured" in block
    assert "Add a notification channel in Settings to unlock this" in block


def test_generic_fallback_copy_still_present_for_unrecognized_requirement():
    """An absent/unrecognized `requirement` value must still fall back to the
    pre-existing generic sentence -- it must not go blank or throw."""
    block = _gating_block(_read())
    assert "unlocks once the Applicant engine is configured" in block, (
        "expected the generic fallback copy to remain for unmapped requirement values"
    )


def test_reason_is_selected_from_the_map_before_falling_back():
    """The `reason` assignment must consult the per-requirement map (keyed by
    `section.requirement`) ahead of the generic string, with `||` (or
    equivalent) providing the fallback -- not the generic string used
    unconditionally."""
    block = _gating_block(_read())
    reason_start = block.find("const reason =")
    assert reason_start != -1, "expected a `const reason = ...` assignment"
    # Grab a bounded slice of the assignment (it spans a few lines, terminated
    # by the `;` that closes the ternary/expression).
    reason_end = block.find(";", reason_start)
    reason_expr = block[reason_start:reason_end]
    assert "section.requirement" in reason_expr, (
        "expected the reason expression to key off section.requirement"
    )
    assert "APPLICANT_REQUIREMENT_REASONS" in reason_expr, (
        "expected the reason expression to consult the requirement->reason map"
    )


def test_present_but_disabled_branch_untouched():
    """The present-but-disabled ('not available in this build') branch is a
    separate, already-correct case -- confirm the fix didn't touch it."""
    block = _gating_block(_read())
    assert "is not available in this build" in block


def test_launch_setup_wiring_still_present():
    """The click-guard's setup-wizard hand-off (design-audit #43) must still be
    wired -- this fix only changes the *copy*, not the unlock action."""
    block = _gating_block(_read())
    assert "window.launchApplicantSetup" in block
