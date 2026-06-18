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
def test_banned_phrase_matches_through_curly_apostrophe():
    # FR-RESUME-5: LLM output uses U+2019 (’) where the seed list uses ASCII '.
    # The filter must normalize curly->straight before matching/stripping.
    assert truthfulness.has_banned_phrase("it’s important to note that I shipped it")
    assert "it's important to note" in truthfulness.find_banned_phrases(
        "Well, it’s  important to note that…"
    )
    stripped = truthfulness.strip_banned_phrases("it’s important to note that I shipped it")
    assert "important to note" not in stripped.lower()
    assert "shipped it" in stripped


@pytest.mark.unit
def test_extra_emdash_variants_detected_and_normalized():
    # FR-RESUME-5: two-em (⸺) / three-em (⸻) / figure (‒) / fullwidth (－) dashes
    # and bare word--word must be handled.
    assert truthfulness.contains_emdash("Led teams ⸺ shipped fast")
    assert truthfulness.contains_emdash("word--word")
    assert "⸺" not in truthfulness.normalize_emdashes("a ⸺ b")
    assert truthfulness.normalize_emdashes("a ⸺ b") == "a, b"
    assert truthfulness.normalize_emdashes("word--word") == "word, word"
    assert truthfulness.normalize_emdashes("range 5‒10") == "range 5-10"


@pytest.mark.unit
def test_post_filter_pass():
    assert truthfulness.passes_post_filter("Shipped a payments system that cut latency 30%.")
    assert not truthfulness.passes_post_filter("A testament to my passion — truly.")


@pytest.mark.unit
def test_banned_phrase_stripped_deterministically_and_idempotent():
    # FR-RESUME-5: banned phrases are stripped by code, not left to the model.
    out = truthfulness.strip_banned_phrases("It's important to note that I shipped it.")
    assert "important to note" not in out.lower()
    assert "shipped it" in out
    # Idempotent.
    assert truthfulness.strip_banned_phrases(out) == out


@pytest.mark.unit
def test_ui_editable_banned_phrases_extend_the_list():
    # FR-RESUME-5: the UI-editable banned-phrase list supplements the seed list.
    extra = ("rockstar ninja",)
    assert truthfulness.has_banned_phrase("I am a rockstar ninja", extra)
    assert not truthfulness.has_banned_phrase("I am a rockstar ninja")  # not in seed
    assert "rockstar ninja" not in truthfulness.strip_banned_phrases(
        "I am a rockstar ninja", extra
    ).lower()


@pytest.mark.unit
def test_voice_profile_extraction_and_alignment():
    # FR-RESUME-5: a deterministic voice profile from the user's corpus.
    corpus = [
        "I built data pipelines. I shipped analytics dashboards. I led migrations.",
    ]
    profile = truthfulness.extract_voice_profile(corpus)
    assert not profile.is_empty
    assert profile.first_person_ratio > 0  # first-person voice detected
    assert "pipelines" in profile.vocabulary
    # On-voice text aligns higher than off-voice generic text.
    on = truthfulness.voice_alignment(profile, "I built more pipelines and dashboards")
    off = truthfulness.voice_alignment(profile, "Synergistic enterprise paradigms unlock value")
    assert on > off
    # Empty profile never penalizes.
    assert truthfulness.voice_alignment(truthfulness.VoiceProfile(), "anything") == 1.0


@pytest.mark.unit
def test_fabrication_detection_flags_unsupported_claims():
    # FR-RESUME-2/NFR-TRUTH-1: claims absent from the true history are flagged.
    true = "Built Python services and wrote SQL for analytics."
    flagged = truthfulness.unsupported_claims(true, "Expert in Kubernetes and Python.")
    assert "Kubernetes" in flagged
    assert "Python" not in flagged  # supported -> not flagged
    # Nothing fabricated -> no flags.
    assert truthfulness.unsupported_claims(true, "Python and SQL work.") == []


@pytest.mark.unit
def test_fabrication_guard_passes_natural_cover_letter_prose():
    # FR-RESUME-10/NFR-TRUTH-1: a free-prose cover letter whose only substantive
    # claims are grounded in the true source must NOT be flagged. Ordinary English /
    # connective / scaffolding words ("Dear", "spent", "would", "challenges") are not
    # fabrications — only named skills/tech/orgs/qualifications absent from the source
    # are. Regression: a narrow filler list flagged every prose word and blocked all
    # LLM-generated cover letters.
    true = (
        "Kevin Hirsch, staff software engineer. Skills: Python, Go, Kubernetes, "
        "distributed systems, leadership. Led a team of engineers. Shipped a data "
        "platform. Migrated to Kubernetes and reduced deployment time."
    )
    letter = (
        "Dear Hiring Manager, I have spent the last several years building "
        "distributed systems in Python and Go. I led a team of engineers and "
        "shipped a data platform. I migrated our infrastructure to Kubernetes and "
        "reduced deployment time. I would genuinely welcome the chance to talk about "
        "how my background aligns with this role. Warmly, Kevin Hirsch"
    )
    assert truthfulness.unsupported_claims(true, letter) == []


@pytest.mark.unit
def test_fabrication_guard_still_catches_fabricated_skill_in_prose():
    # The prose-friendly stopword list must NOT weaken real detection: a named skill
    # the candidate never had is still flagged even amid natural cover-letter prose.
    true = "Kevin Hirsch, Python and Go engineer. Shipped a data platform."
    letter = (
        "Dear Hiring Manager, I would love this role. I am also a certified Rust "
        "expert with a PhD from Stanford. Warmly, Kevin Hirsch"
    )
    flagged = truthfulness.unsupported_claims(true, letter)
    assert "Rust" in flagged
    assert "PhD" in flagged
    assert "Stanford" in flagged


@pytest.mark.unit
def test_prose_claims_pass_open_vocabulary_cover_letter():
    # FR-RESUME-10: the prose check tolerates an open-ended narrative vocabulary
    # (content words absent from the terse source) and contractions, flagging only
    # entity-shaped fabrications. A grounded cover letter must produce no flags.
    true = (
        "Kevin Hirsch, staff software engineer. Python, Go, Kubernetes, distributed "
        "systems. Shipped an LLM-powered platform serving 5M requests."
    )
    letter = (
        "Dear Hiring Manager, I've spent years building distributed systems and I'm "
        "drawn to the low-latency, high-traffic problems your team is solving. I "
        "enjoy designing for reliability and tightening the feedback loop so teams "
        "ship with confidence. Lately I've explored practical applications of LLMs. "
        "I'd welcome the chance to talk. Warmly, Kevin"
    )
    assert truthfulness.unsupported_prose_claims(true, letter) == []


@pytest.mark.unit
def test_prose_claims_still_flag_entity_fabrications():
    # The prose check must still catch invented named entities: a degree, school,
    # and technology the candidate never had, even amid natural prose.
    true = "Kevin Hirsch, Python and Go engineer. Shipped a data platform."
    letter = (
        "I'd love this role. I hold a PhD from Stanford and I'm a certified Rust and "
        "Kubernetes expert who shipped on AWS in 2015."
    )
    flagged = truthfulness.unsupported_prose_claims(true, letter)
    for entity in ("PhD", "Stanford", "Rust", "Kubernetes", "AWS", "2015"):
        assert entity in flagged, f"{entity} should be flagged: {flagged}"


@pytest.mark.unit
def test_fabrication_detection_catches_lowercase_and_uses_whole_token():
    # FR-RESUME-2/NFR-TRUTH-1: (a) lowercase claims are not exempt from detection;
    # (b) whole-token membership, not substring, so "Java" never "supports"
    # "JavaScript".
    assert "kubernetes" in truthfulness.unsupported_claims(
        "Built Python services", "expert in kubernetes"
    )
    assert "JavaScript" in truthfulness.unsupported_claims(
        "Java Java", "Skilled JavaScript dev"
    )


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


@pytest.mark.unit
def test_short_markers_match_on_word_boundaries_not_substrings():
    # FR-ATTR-6/FR-PREFILL-3: "age"/"sex"/"race" must not match inside ordinary
    # words ("Manager", "Message", "language", "unisex", "embrace") and break
    # prefill, while real EEO fields still classify sensitive.
    for ordinary in ("Manager name", "Message to manager", "Preferred language", "Unisex size"):
        assert sensitive_fields.is_sensitive_field(ordinary) is False
    for eeo in ("What is your age?", "Sex:", "Gender", "Race / Ethnicity"):
        assert sensitive_fields.is_sensitive_field(eeo) is True
    # A previously-broken field no longer raises in decide_sensitive_fill.
    d = sensitive_fields.decide_sensitive_fill("Manager name", None, ai_suggested="Pat")
    assert d.is_sensitive is False


@pytest.mark.unit
def test_eeo_ethnicity_markers_classify_sensitive():
    # FR-ATTR-6: Hispanic/Latino/Latinx and military service are EEO markers.
    for label in (
        "Are you Hispanic or Latino?",
        "Latinx",
        "Military / veteran status",
    ):
        assert sensitive_fields.is_sensitive_field(label) is True


@pytest.mark.unit
def test_non_sensitive_empty_answer_not_from_explicit():
    # Consistency with the sensitive branch: an empty string is not an explicit
    # answer, so from_explicit_answer must be False.
    d = sensitive_fields.decide_sensitive_fill("First name", "")
    assert d.is_sensitive is False
    assert d.from_explicit_answer is False
    d2 = sensitive_fields.decide_sensitive_fill("First name", "Kevin")
    assert d2.from_explicit_answer is True


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
