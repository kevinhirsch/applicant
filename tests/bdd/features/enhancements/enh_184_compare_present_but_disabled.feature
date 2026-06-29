# Issue #184 — Compare surface present-but-disabled — workspace/src/applicant_features.py
# The Compare surface ships visible-but-greyed with zero engine backing. The feature
# layer marks it present_but_disabled, so it always reports "disabled" regardless of
# engine reachability. The GREEN scenarios pin that shipped product decision; the
# @pending scenario probes the residual gap — there is no engine endpoint that backs a
# real comparison of campaigns/applications/variants (the wiring lives in #297).

Feature: The Compare surface ships present-but-disabled with no engine backing

  Scenario: Compare is registered as a present-but-disabled section
    Given the Applicant feature-state layer
    When the Applicant section registry is inspected
    Then the Compare section is flagged present-but-disabled

  Scenario: Compare always resolves to disabled even when the engine is offline
    Given the Applicant feature-state layer
    When the per-section state is computed against an unreachable engine
    Then the Compare section reports the disabled state

  @pending
  Scenario: A backend comparison of two entities returns scored differences
    Given two campaigns that should be compared side by side
    When a cross-entity comparison is requested from the engine
    Then the engine returns a structured diff with per-entity metrics
