Feature: Résumé aggressiveness dial is wired backend-side and never relaxes truthfulness
  # Issue #187 — résumé aggressiveness tuning control is greyed out (slider does nothing)
# Engine: core/rules/materials.py (clamp_aggressiveness / aggressiveness_directive,
# FR-RESUME-9) + application/services/material_service.py (set_aggressiveness). GREEN:
# the backend dial is fully wired and clamped, and the guardrail proof holds — at every
# setting the framing directive still forbids adding any unsupported claim, so the dial
# can never relax the truthfulness constraint (FR-RESUME-2). PENDING: per-campaign
# persistence of the chosen value is not yet implemented.

  Scenario: The framing dial clamps every value into the supported range
    Given the truthful-framing dial
    When an out-of-range value is applied
    Then the stored setting is clamped into the supported range

  Scenario: Raising the dial never relaxes the truthfulness constraint
    Given the truthful-framing dial
    When the most assertive framing is requested
    Then the generation directive still forbids adding any unsupported claim

  Scenario: The material service accepts and clamps the dial setting
    Given a material service with no model wired
    When the operator sets an above-maximum aggressiveness
    Then the service reports the clamped maximum

  @pending
  Scenario: The chosen dial value persists per job search across requests
    Given a material service with a chosen aggressiveness for a job search
    When a fresh service is built for the same job search
    Then it recalls the previously chosen aggressiveness
