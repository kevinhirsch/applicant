# Issue #297 — Wire up the Compare surface — cross-entity comparison backend
# Builds on #184: Compare ships present-but-disabled with zero engine backing (GREEN that
# it is disabled). The feature wants real cross-entity comparison: resume variants,
# applications, campaigns, discovery sources, time periods — with scores and metadata. No
# comparison endpoint/service exists, so the wiring probes are @pending.

Feature: Compare surface — cross-entity comparison wiring

  Scenario: Compare ships disabled until it is wired
    Given the Applicant feature-state layer
    When the per-section state is computed against an unreachable engine
    Then the Compare section reports the disabled state

  @pending
  Scenario: Two applications are compared with the differing dimensions surfaced
    Given one application that converted and one that ghosted
    When a comparison is requested from the engine
    Then the differing dimensions are surfaced with metrics

  @pending
  Scenario: Campaign metrics are compared side by side
    Given two campaigns with discovery and conversion metrics
    When a campaign comparison is requested
    Then the engine returns side-by-side metrics for each campaign
