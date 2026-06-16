"""Unit tests for the load-bearing domain rules (core/rules/)."""

from __future__ import annotations

import pytest

from applicant.core.errors import (
    ConfirmationRequired,
    PrefillBoundaryViolation,
    ReviewRequired,
    SensitiveFieldViolation,
)
from applicant.core.rules import (
    confirmation_gate,
    prefill_boundary,
    review_gate,
    sensitive_fields,
    truthfulness,
)
from applicant.core.rules.prefill_boundary import StepKind
from applicant.core.rules.review_gate import ReviewableMaterial
from applicant.core.rules.sensitive_fields import DECLINE_TO_SELF_IDENTIFY


# --- truthfulness ----------------------------------------------------------
@pytest.mark.unit
def test_emdash_stripped_deterministically():
    assert "—" not in truthfulness.normalize_emdashes("Led teams — shipped fast")
    assert truthfulness.normalize_emdashes("a — b") == "a, b"
    assert truthfulness.normalize_emdashes("range 5–10") == "range 5-10"
    # idempotent
    once = truthfulness.normalize_emdashes("x — y")
    assert truthfulness.normalize_emdashes(once) == once


@pytest.mark.unit
def test_emdash_detection_and_double_hyphen():
    assert truthfulness.contains_emdash("a — b")
    assert truthfulness.contains_emdash("a -- b")
    assert not truthfulness.contains_emdash("a - b")
    assert not truthfulness.contains_emdash("plain text")


@pytest.mark.unit
def test_banned_phrase_checker():
    assert truthfulness.has_banned_phrase("Let me delve into my experience")
    assert "delve into" in truthfulness.find_banned_phrases("I will Delve Into this")
    assert not truthfulness.has_banned_phrase("Built and shipped a payments system")


@pytest.mark.unit
def test_post_filter_pass():
    assert truthfulness.passes_post_filter("Shipped a payments system that cut latency 30%.")
    assert not truthfulness.passes_post_filter("A testament to my passion — truly.")


# --- sensitive fields ------------------------------------------------------
@pytest.mark.unit
def test_eeo_defaults_to_decline_when_no_answer():
    d = sensitive_fields.decide_sensitive_fill("Race / Ethnicity", None)
    assert d.is_sensitive
    assert d.value == DECLINE_TO_SELF_IDENTIFY
    assert not d.from_explicit_answer


@pytest.mark.unit
def test_eeo_uses_explicit_answer():
    d = sensitive_fields.decide_sensitive_fill("Gender", "Prefer not to say")
    assert d.value == "Prefer not to say"
    assert d.from_explicit_answer


@pytest.mark.unit
def test_eeo_never_ai_guessed():
    with pytest.raises(SensitiveFieldViolation):
        sensitive_fields.decide_sensitive_fill("Disability status", None, ai_suggested="No")


@pytest.mark.unit
def test_non_sensitive_field_passthrough():
    d = sensitive_fields.decide_sensitive_fill("First name", "Kevin")
    assert not d.is_sensitive
    assert d.value == "Kevin"


# --- prefill boundary ------------------------------------------------------
@pytest.mark.unit
@pytest.mark.parametrize(
    "step",
    [StepKind.ACCOUNT_CREATE_SUBMIT, StepKind.CAPTCHA, StepKind.EMAIL_VERIFY, StepKind.SMS_VERIFY],
)
def test_irreducible_human_steps_blocked(step):
    assert prefill_boundary.is_irreducible_human_step(step)
    with pytest.raises(PrefillBoundaryViolation):
        prefill_boundary.ensure_action_allowed(step)


@pytest.mark.unit
def test_fillable_steps_allowed():
    for step in (StepKind.FILL_FIELD, StepKind.NAVIGATE, StepKind.SCREENSHOT):
        prefill_boundary.ensure_action_allowed(step)  # no raise


@pytest.mark.unit
def test_final_submit_requires_authorization():
    with pytest.raises(PrefillBoundaryViolation):
        prefill_boundary.ensure_action_allowed(StepKind.FINAL_SUBMIT)
    prefill_boundary.ensure_action_allowed(StepKind.FINAL_SUBMIT, engine_submit_authorized=True)


# --- confirmation gate -----------------------------------------------------
@pytest.mark.unit
def test_integral_change_requires_confirmation():
    with pytest.raises(ConfirmationRequired):
        confirmation_gate.ensure_change_allowed(is_integral=True, user_confirmed=False)
    confirmation_gate.ensure_change_allowed(is_integral=True, user_confirmed=True)


@pytest.mark.unit
def test_non_integral_change_auto_applies():
    confirmation_gate.ensure_change_allowed(is_integral=False, user_confirmed=False)  # no raise
    assert not confirmation_gate.requires_confirmation(False)


# --- review gate -----------------------------------------------------------
@pytest.mark.unit
def test_unapproved_generated_material_blocks_submission():
    mats = [ReviewableMaterial("doc-1", is_generated=True, approved=False)]
    assert not review_gate.can_submit(mats)
    with pytest.raises(ReviewRequired):
        review_gate.ensure_submittable(mats)


@pytest.mark.unit
def test_approved_generated_material_submittable():
    mats = [ReviewableMaterial("doc-1", is_generated=True, approved=True)]
    assert review_gate.can_submit(mats)
    review_gate.ensure_submittable(mats)  # no raise


@pytest.mark.unit
def test_pristine_base_resume_not_gated():
    mats = [ReviewableMaterial("base", is_generated=False, approved=False)]
    assert review_gate.can_submit(mats)
